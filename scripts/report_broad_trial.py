"""Summarize the broad-view trial without counting old jobs as new discoveries."""
import argparse
import html
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.job_url import canonical_job_url


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def report(folder):
    baseline = read(folder / "baseline.json")
    final = read(folder / ("final.json" if (folder / "final.json").exists() else "latest.json"))
    complete = read(folder / "complete.json") if (folder / "complete.json").exists() else None
    progress = complete or read(folder / "progress.json")
    rounds = [read(p) for p in sorted(folder.glob("round-*.json"))]
    old = {canonical_job_url(j["source_url"]) for j in baseline["jobs"] if j["source_url"]}
    jobs = {j["id"]: j for j in final["jobs"]}
    audit = read(folder / "audit.json") if (folder / "audit.json").exists() else []
    audit_by_id = {a["id"]: a for a in audit}
    rows = {}
    evidence = folder / "evidence"
    evidence.mkdir(exist_ok=True)
    for match in final["library"]["result_matches"]:
        job = jobs[match["job_posting_id"]]
        key = canonical_job_url(job["source_url"]) if job["source_url"] else job["id"]
        if key in rows:
            raise ValueError(f"Duplicate library identity: {job['id']}")
        rows[key] = {"id": job["id"], "title": job["title"], "company": job["company"],
            "url": job["source_url"], "new": key not in old, "match": match,
            "audit": audit_by_id.get(job["id"]), "evidence": f"evidence/{job['id']}.txt"}
        (evidence / f"{job['id']}.txt").write_text(job["raw_content"], encoding="utf-8")
    values = list(rows.values())
    counts = Counter(r["match"]["review_status"] for r in values)
    new_counts = Counter(r["match"]["review_status"] for r in values if r["new"])
    pending_ai = sum(any(c.get("diagnosis") == "not_extracted" and "当前版本AI" in c["reason"]
        for c in r["match"]["checks"]) for r in values if r["match"]["review_status"] == "pending")
    metrics = Counter()
    errors = Counter()
    for round_ in rounds:
        for key in ("source_read_attempts", "source_read_successes", "read_attempts", "read_successes",
                    "cache_hits", "retry_attempts", "retry_recovered", "source_retry_attempts", "source_retry_recovered"):
            metrics[key] += (round_["metrics"] or {}).get(key, 0)
        for event in round_["trace"]:
            error = event.get("error_code") or (event.get("details") or {}).get("error_code")
            if error:
                errors[f"{event['tool']}:{error}"] += 1
    references = []
    buffered = {canonical_job_url(item["id"])
        for state in final["company_search_state"].get("sources", {}).values()
        for item in state.get("buffer", []) if str(item.get("id", "")).startswith("http")}
    with sqlite3.connect((folder / "trial.db").as_uri() + "?mode=ro", uri=True) as database:
        linked = {canonical_job_url(row[0]) for row in database.execute(
            "SELECT l.source_url FROM job_leads l JOIN discovery_runs r ON r.id=l.discovery_run_id "
            "WHERE r.search_goal_id=? AND r.search_goal_version=? AND l.job_posting_id IS NULL",
            (final["goal"]["id"], final["goal"]["version"]))}
    for cohort in ("final-acceptance", "final-coverage", "final-ranking-acceptance"):
        for ref in read(ROOT / "artifacts/quality-pipeline-20261019" / cohort / "results.json")["results"]:
            found = rows.get(canonical_job_url(ref["url"]))
            basis = "canonical_url"
            if found is None:
                # Compare frozen references, never merge database records. A
                # listing filter (e.g. department) can change on the same detail.
                reference_url = urlsplit(ref["url"])
                alternatives = [r for r in values if r["title"] == ref["title"]
                    and (urlsplit(r["url"]).netloc, urlsplit(r["url"]).path, urlsplit(r["url"]).fragment)
                    == (reference_url.netloc, reference_url.path, reference_url.fragment)]
                if len(alternatives) == 1:
                    found, basis = alternatives[0], "same_host_path_and_title"
            references.append({"title": ref["title"], "url": ref["url"],
                "previous": ref.get("match", {}).get("filter_status"),
                "current": found["match"]["review_status"] if found else "buffered" if canonical_job_url(ref["url"]) in buffered
                    else "linked" if canonical_job_url(ref["url"]) in linked else "not_in_library",
                "new": found["new"] if found else None, "comparison_basis": basis if found else None})
    first_new = [r["trial_elapsed_seconds"] - r["elapsed_seconds"] + r["metrics"]["first_new_recommended_ms"] / 1000
        for r in rounds if r["metrics"].get("first_new_recommended_ms") is not None]
    summary = {"complete": complete, "elapsed_seconds": progress["elapsed_seconds"], "rounds": len(rounds),
        "counts": dict(counts), "new_counts": dict(new_counts), "new_unique": sum(new_counts.values()),
        "default_visible": counts["recommended"] + counts["pending"], "pending_ai": pending_ai,
        "old_recommended": counts["recommended"] - new_counts["recommended"],
        "first_new_recommended_seconds": min(first_new) if first_new else None,
        "metrics": dict(metrics), "errors": dict(errors), "review_queue": final["library"].get("review_queue"),
        "company_discovery_queue": final["library"].get("company_discovery_queue"),
        "company_progress": final["library"].get("company_progress"), "references": references, "audit": audit,
        "rows": values,
        "limits": "本次为同一网络与模型环境的连续试用；复核由助手基于保存原文完成，未做全网召回率估计。推荐不代表个人全部申请资格通过。"}
    summary["library_performance"] = read(folder / "library-performance.json") if (folder / "library-performance.json").exists() else None
    summary["validation"] = read(folder / "validation.json") if (folder / "validation.json").exists() else None
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    esc = lambda value: html.escape(str(value if value is not None else ""))
    labels = {"recommended": "推荐", "pending": "值得看看", "excluded": "明确不符", "not_in_library": "尚未进入本次岗位库",
        "buffered": "已在列表发现，等待公司续查", "linked": "已有链接，详情待核验"}
    cards = []
    for row in sorted(values, key=lambda r: (not r["new"], {"recommended": 0, "pending": 1, "excluded": 2}[r["match"]["review_status"]], r["company"] or "", r["title"])):
        match = row["match"]
        checks = ''.join(f'<li>{esc(c["field"])}：{esc(c["reason"])}</li>' for c in match["checks"])
        hints = ''.join(f'<li>{esc(h["label"])}：{esc(h["reason"])}</li>' for h in match.get("personal_requirements", []))
        note = row["audit"]["note"] if row["audit"] else "未单独人工复核；以下为系统判断。"
        cards.append(f'<article data-new="{int(row["new"])}" data-status="{esc(match["review_status"])}" data-search="{esc((row["company"] or "") + row["title"])}"><small>{"本次新入库" if row["new"] else "原有岗位"} · {esc(labels[match["review_status"]])} · {esc(row["company"] or "公司待确认")}</small><h3><a href="{esc(row["url"])}">{esc(row["title"])}</a></h3><p>{esc(note)}</p><details><summary>查看筛选依据与个人门槛</summary><ul>{checks}{hints}</ul><a href="{esc(row["evidence"])}">保存的岗位原文</a></details></article>')
    reference_html = ''.join(f'<tr><td><a href="{esc(r["url"])}">{esc(r["title"])}</a></td><td>{esc(r["previous"])}</td><td>{esc(labels[r["current"]])}</td></tr>' for r in references)
    timeline = ''.join(f'<tr><td>{r["round"]}</td><td>{esc(r["continue_company"] or "更新搜索")}</td><td>{r["elapsed_seconds"]:.1f} 秒</td><td>{r["trial_elapsed_seconds"]/60:.1f} 分</td><td>{r["library_counts"]["recommended"]}</td></tr>' for r in rounds)
    findings = read(folder / "findings.json") if (folder / "findings.json").exists() else []
    findings_html = ''.join(f'<li><strong>{esc(r["title"])}</strong>：{esc(r["detail"])}</li>' for r in findings)
    ui = read(folder / "ui-checks.json") if (folder / "ui-checks.json").exists() else {}
    ui_text = "桌面与手机均通过默认展示、原文阅读、收藏保持、忽略后恢复、页面无横向溢出与无前端报错检查。" if len(ui) == 2 and all(all(checks.values()) for checks in ui.values()) else "尚未全部通过。"
    performance = summary["library_performance"]
    speed_note = (f'同一254条岗位副本的岗位库计算：{performance["before_seconds"]:.2f}秒 → {performance["after_seconds"]:.2f}秒，岗位结论、计数、更新项与链接集合均保持一致。此优化与轮询修复在试用期间发现并单独验收；未中断正在运行的搜索。' if performance else "")
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>宽松发现 · 半小时试用</title>
<style>body{{font:16px/1.65 system-ui;background:#f2f5f8;color:#22334a;margin:0}}main{{max-width:1100px;margin:auto;padding:32px 20px}}section,article{{background:white;padding:22px;margin:16px 0;border-radius:12px}}h1,h2,h3{{line-height:1.3}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.metric{{background:#e8eef8;padding:18px;border-radius:10px}}.metric strong{{display:block;font-size:30px}}small,.muted{{color:#526176}}a{{color:#1554b1;overflow-wrap:anywhere}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #ddd}}select,input{{font:inherit;padding:8px;max-width:100%;margin:6px}}summary{{cursor:pointer}}article[hidden]{{display:none}}li{{margin:8px 0}}.scroll{{overflow-x:auto}}@media(max-width:700px){{.grid{{grid-template-columns:1fr 1fr}}main{{padding:20px 12px}}}}</style>
<main><small>北京 / 上海 · 2027届 · Agent / RAG / AI产品 · 2026-10-19</small><h1>推荐＋值得看看</h1><p>{"已完成" if complete else "正在运行"} {progress["elapsed_seconds"]/60:.1f} 分钟，共 {len(rounds)} 轮。搜索、已存正文复核与公司发现同时工作；每家公司每轮仍检查最多3条。</p>
<div class="grid"><div class="metric"><strong>{sum(new_counts.values())}</strong>新入库（去重）</div><div class="metric"><strong>{new_counts["recommended"]}</strong>新增推荐</div><div class="metric"><strong>{new_counts["pending"]}</strong>新增值得看看</div><div class="metric"><strong>{new_counts["excluded"]}</strong>新增后明确排除</div></div>
<section><h2>数量怎样理解</h2><p>个人库最终共 {len(values)} 条：推荐 {counts["recommended"]}、值得看看 {counts["pending"]}、明确不符 {counts["excluded"]}。推荐中 {summary["old_recommended"]} 条来自原有岗位；它们不算本次新发现。默认可见 {summary["default_visible"]} 条，包括仍等待当前AI解释的 {pending_ai} 条。</p><p>本轮首个新增推荐约 {summary["first_new_recommended_seconds"] or 0:.1f} 秒出现。官网列表读取成功 {metrics["source_read_successes"]}/{metrics["source_read_attempts"]} 次；详情读取成功 {metrics["read_successes"]}/{metrics["read_attempts"]} 次。均为尝试次数，包含重复访问。详情失败续查恢复 {metrics["retry_recovered"]}/{metrics["retry_attempts"]} 次；官网重试恢复 {metrics["source_retry_recovered"]}/{metrics["source_retry_attempts"]} 次。</p></section>
<section><h2>漏岗、误荐与操作体验</h2><ul>{findings_html or '<li>尚在复核，最终结论待补充。</li>'}</ul><p>{esc(ui_text)}</p><p>{esc(speed_note)}</p><p><a href="broad-desktop.png">桌面列表截图</a> · <a href="broad-mobile.png">手机列表截图</a> · <a href="detail-mobile.png">手机岗位详情</a> · <a href="audit.json">助手逐条原文审阅</a> · <a href="ui-checks.json">操作验收</a> · <a href="validation.json">代码验证</a></p><p class="muted">{esc(summary["limits"])}</p></section>
<section><h2>38条已有原文对照</h2><p>只检查这组已知岗位的去向；无法据此声称覆盖了所有官网。前次结论为 matched / pending / excluded，此次列出实际个人库的展示层级。</p><div class="scroll"><table><tr><th>岗位</th><th>前次原文核验</th><th>此次去向</th></tr>{reference_html}</table></div></section>
<section><h2>连续运行记录</h2><div class="scroll"><table><tr><th>轮次</th><th>操作</th><th>本轮用时</th><th>累计用时</th><th>库中推荐数（含旧岗）</th></tr>{timeline}</table></div><details><summary>后台与读取状态</summary><pre style="white-space:pre-wrap">{esc(json.dumps({k:summary[k] for k in ['review_queue','company_discovery_queue','errors']}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>实际岗位清单</h2><label>范围<select id="scope"><option value="new">本次新入库</option><option value="all">全部岗位</option></select></label><label>展示<select id="status"><option value="visible">推荐＋值得看看</option><option value="recommended">推荐</option><option value="pending">值得看看</option><option value="excluded">明确不符</option><option value="all">全部</option></select></label><input id="query" placeholder="按公司 / 职位名称搜索"><p id="count"></p></section><div id="jobs">{''.join(cards)}</div>
<p><a href="summary.json">完整统计与岗位数据</a> · <a href="baseline.json">开始前快照</a> · <a href="{'final.json' if complete else 'latest.json'}">结束快照</a> · <a href="configuration.json">测试配置</a></p></main>
<script>function filter(){{let n=0;document.querySelectorAll('#jobs article').forEach(e=>{{let s=document.querySelector('#status').value,q=document.querySelector('#query').value.toLowerCase();e.hidden=(document.querySelector('#scope').value==='new'&&e.dataset.new!=='1')||(s==='visible'?e.dataset.status==='excluded':s!=='all'&&e.dataset.status!==s)||!e.dataset.search.toLowerCase().includes(q);if(!e.hidden)n++}});document.querySelector('#count').textContent='当前显示 '+n+' 条'}}document.querySelectorAll('select,input').forEach(e=>e.addEventListener('input',filter));filter();</script></html>'''
    (folder / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["elapsed_seconds", "rounds", "counts", "new_counts", "pending_ai"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    report(parser.parse_args().folder.resolve())

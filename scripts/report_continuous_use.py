"""Summarize persisted continuous-use observations without changing judgments."""

import argparse
import html
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.job_url import canonical_job_url


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def queue_ids(snapshot):
    return {(r["kind"], r["id"]) for r in snapshot["review_items"]}


def report(folder):
    baseline = read(folder / "visit-01/before.json")
    latest = read(folder / "latest.json")
    complete = read(folder / "complete.json")
    visits, rounds, snapshots, errors = [], [], [], Counter()
    for directory in sorted(folder.glob("visit-*")):
        if not directory.is_dir():
            continue
        before, idle, after = [read(directory / name) for name in ("before.json", "idle-start.json", "after.json")]
        events = read(directory / "events.json", [])
        if not before:
            continue
        visit_rounds = [read(p) for p in sorted(directory.glob("round-*.json"))]
        rounds.extend(visit_rounds)
        snapshots.extend(read(p) for p in sorted(directory.glob("after-round-*.json")))
        if after:
            snapshots.append(after)
        visits.append({"visit": directory.name, "complete": bool(after),
            "seconds": (read(directory / "complete.json", {}) or {}).get("elapsed_seconds"),
            "rounds": len(visit_rounds), "before": before["library"]["review_queue"],
            "idle_start": idle["library"]["review_queue"] if idle else None,
            "after": after["library"]["review_queue"] if after else None,
            "counts_after": (after or latest)["library"]["counts"],
            "idle_completed_counter_delta": after["library"]["review_queue"]["completed"] - idle["library"]["review_queue"]["completed"]
                if idle and after else None,
            "worker_errors": read(directory / "worker-errors.json", []),
            "events": events})
    old_jobs = {canonical_job_url(j["source_url"]) if j["source_url"] else j["id"] for j in baseline["jobs"]}
    jobs = {j["id"]: j for j in latest["jobs"]}
    rows, identities = [], set()
    evidence = folder / "evidence"
    evidence.mkdir(exist_ok=True)
    duplicates = []
    for match in latest["library"]["result_matches"]:
        job = jobs[match["job_posting_id"]]
        identity = canonical_job_url(job["source_url"]) if job["source_url"] else job["id"]
        if identity in identities:
            duplicates.append(job["id"])
        identities.add(identity)
        row = {"id": job["id"], "title": job["title"], "company": job["company"],
            "url": job["source_url"], "new": identity not in old_jobs, "match": match}
        rows.append(row)
        (evidence / f'{job["id"]}.txt').write_text(job["raw_content"], encoding="utf-8")
    new_counts = Counter(r["match"]["review_status"] for r in rows if r["new"])
    metrics = Counter()
    for run in rounds:
        for key in ("source_read_attempts", "source_read_successes", "read_attempts", "read_successes",
                    "cache_hits", "retry_attempts", "retry_recovered", "source_retry_attempts", "source_retry_recovered"):
            metrics[key] += (run["metrics"] or {}).get(key, 0)
        for event in run["trace"]:
            code = event.get("error_code") or (event.get("details") or {}).get("error_code")
            if code:
                errors[f'{event["tool"]}:{code}'] += 1
    restarts = []
    for number in range(2, len(visits) + 1):
        previous = read(folder / f"visit-{number-1:02d}/after.json")
        current = read(folder / f"visit-{number:02d}/before.json")
        if previous and current:
            events = read(folder / f"visit-{number:02d}/events.json", [])
            resumed = next((e["elapsed_seconds"] for e in events
                if (e.get("queue") or {}).get("processed", 0) > current["library"]["review_queue"]["processed"]), None)
            restarts.append({"visit": number,
                "first_observed_background_progress_seconds": resumed,
                "job_ids_preserved": {j["id"] for j in previous["jobs"]} == {j["id"] for j in current["jobs"]},
                "queue_items_preserved": queue_ids(previous) == queue_ids(current),
                "company_progress_preserved": previous["company_search_state"] == current["company_search_state"],
                "saved_candidates_preserved": {r["id"] for r in previous["candidates"] if r["status"] == "SAVED"}
                    <= {r["id"] for r in current["candidates"] if r["status"] == "SAVED"}})
    ui = [value for p in sorted(folder.glob("ui-*.json"))
        if p.is_file() and "viewport" in (value := read(p))]
    library_ms = [r["milliseconds"] for check in ui for r in check.get("requests", []) if r["path"].endswith("/library")]
    audit = read(folder / "audit.json", [])
    by_id = {r["id"]: r for r in rows}
    for item in audit:
        row = by_id.get(item["id"])
        item["actual_status"] = row["match"]["review_status"] if row else "not_in_library"
        attempt = (jobs.get(item["id"], {}).get("recruitment_context") or {}).get("source_review_attempt", {})
        item["last_attempt_error"] = attempt.get("error_code")
        item["last_attempt_at"] = attempt.get("attempted_at")
        item["queued_at"] = attempt.get("queued_at")
        if item["actual_status"] == "pending" and attempt.get("queued_at"):
            item["observed_wait_minutes"] = round((datetime.fromisoformat(latest["at"])
                - datetime.fromisoformat(attempt["queued_at"])).total_seconds() / 60, 1)
        elif attempt.get("queued_at") and attempt.get("attempted_at") and not attempt.get("error_code"):
            item["current_body_review_finished_after_minutes"] = round((datetime.fromisoformat(attempt["attempted_at"])
                - datetime.fromisoformat(attempt["queued_at"])).total_seconds() / 60, 1)
    baseline_pending = queue_ids(baseline)
    final_pending = queue_ids(latest)
    summary = {"complete": complete, "sessions": visits, "round_count": len(rounds),
        "new_unique_jobs": sum(new_counts.values()), "new_counts": dict(new_counts),
        "library_counts": latest["library"]["counts"], "queue_before": baseline["library"]["review_queue"],
        "queue_after": latest["library"]["review_queue"],
        "baseline_items_still_pending": len(baseline_pending & final_pending),
        "baseline_items_no_longer_pending": len(baseline_pending - final_pending),
        "new_items_pending": len(final_pending - baseline_pending), "metrics": dict(metrics),
        "errors": dict(errors), "restarts": restarts, "ui": ui, "duplicate_library_identities": duplicates,
        "library_latency": {"samples": len(library_ms), "median_ms": statistics.median(library_ms) if library_ms else None,
            "max_ms": max(library_ms) if library_ms else None}, "audit": audit, "rows": rows,
        "personal_hint_defects": read(folder / "personal-hint-defects.json", []),
        "integrity": read(folder / "integrity.json"),
        "validation": read(folder / "validation.json"),
        "initial_ui_failure": read(folder / "ui-initial-failure.json"),
        "limits": ["同一天的真实网络和模型试用；压缩的是使用会话之间的间隔，没有把时钟、缓存或证据时间推进几天。",
            "使用上次试用库的隔离副本；没有修改个人库、执行投递或上传简历。",
            "推荐仅代表搜索条件，个人资格需结合原文；助手原文抽查不等于全网召回率或独立准确率。",
            "后台任务完成数不同于新增岗位数；首次页面测试超出5秒等待，放宽到30秒后通过，慢加载问题仍然存在。",
            "每25秒采样队列、每轮保存快照，也有本地计算开销；吞吐不是无监测条件下的性能上限。",
            "第三次会话额外优先对列表读取失败、仍可续查的公司执行一次重试；产品搜索和判断代码全程未修改。"]}
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    esc = lambda value: html.escape(str(value if value is not None else "—"))
    labels = {"recommended": "推荐", "pending": "值得看看 / 待确认", "excluded": "明确不符"}
    table = "".join(f'<tr><td>{i+1}</td><td>{v["rounds"]}</td><td>{(v["seconds"] or 0)/60:.1f}分</td>'
        f'<td>{v["before"]["remaining"]}</td><td>{(v["idle_start"] or {}).get("remaining", "—")}</td>'
        f'<td>{(v["after"] or {}).get("remaining", "—")}</td><td>{v["idle_completed_counter_delta"] if v["idle_completed_counter_delta"] is not None else "—"}</td></tr>'
        for i, v in enumerate(visits))
    audits = "".join(f'<li><strong>{esc(r["title"])}</strong>（当前：{esc(labels.get(r["actual_status"], r["actual_status"]))}）：'
        f'{esc(r["finding"])}'
        + (f' 截止结束已等待{esc(r["observed_wait_minutes"])}分钟。' if "observed_wait_minutes" in r else "")
        + f' <a href="evidence/{esc(r["id"])}.txt">原文</a></li>' for r in audit)
    cards = "".join(f'<article data-status="{r["match"]["review_status"]}" data-new="{int(r["new"])}">'
        f'<small>{"本次新入库" if r["new"] else "原有岗位"} · {esc(r["company"])} · {labels[r["match"]["review_status"]]}</small>'
        f'<h3><a href="{esc(r["url"])}">{esc(r["title"])}</a></h3><details><summary>查看判断依据</summary><ul>'
        + "".join(f'<li>{esc(c["field"])}：{esc(c["reason"])}</li>' for c in r["match"]["checks"])
        + f'</ul><a href="evidence/{r["id"]}.txt">保存的岗位原文</a></details></article>' for r in rows)
    finding = read(folder / "findings.json", [])
    finding_html = "".join(f'<li><strong>{esc(r["title"])}</strong>：{esc(r["detail"])}</li>' for r in finding)
    elapsed = (complete or {}).get("elapsed_seconds", 0)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>连续使用模拟验收</title>
<style>body{{font:16px/1.7 system-ui;background:#f4f6fa;color:#182d43;margin:0}}main{{max-width:1080px;margin:auto;padding:28px 20px}}section,article{{background:white;border:1px solid #dce4ee;border-radius:12px;padding:22px;margin:16px 0}}h1,h2,h3{{line-height:1.35}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.metrics div{{background:#e6eef8;border-radius:10px;padding:16px}}.metrics strong{{display:block;font-size:30px}}small{{color:#587083}}a{{color:#1658ac;overflow-wrap:anywhere}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #dde4ec}}.scroll{{overflow:auto}}summary{{cursor:pointer}}select{{font:inherit;padding:8px;margin:8px}}article[hidden]{{display:none}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}@media(max-width:700px){{.metrics{{grid-template-columns:1fr 1fr}}main{{padding:20px 12px}}}}</style>
<main><small>北京 / 上海 · 2027届 · Agent / RAG / AI产品</small><h1>连续使用模拟验收</h1><p>{"实测完成" if complete else "实测进行中"} · {elapsed/60:.1f}分钟 · {len(visits)}次使用会话 · {len(rounds)}轮搜索/续查。会话之间实际退出并重新启动后台进程，离开页面后继续处理已有正文。</p>
<div class="metrics"><div><strong>{sum(new_counts.values())}</strong>本次新入库（去重）</div><div><strong>{new_counts['recommended']}</strong>新岗位中推荐</div><div><strong>{baseline['library']['review_queue']['remaining']} → {latest['library']['review_queue']['remaining']}</strong>待处理队列</div><div><strong>{len(restarts)}</strong>已检查的进程重启</div></div>
<section><h2>发现了什么</h2><ul>{finding_html or '<li>等待试用完成后整理。</li>'}</ul><p>新入库岗位：推荐{new_counts['recommended']}，值得看看/待确认{new_counts['pending']}，明确不符{new_counts['excluded']}。旧队列还有{summary['baseline_items_still_pending']}项，期间新进入且尚未完成{summary['new_items_pending']}项。</p></section>
<section><h2>搜索与后台能否跟上</h2><div class="scroll"><table><tr><th>会话</th><th>搜索轮次</th><th>时长</th><th>开始积压</th><th>停止搜索时</th><th>后台运行后</th><th>仅后台阶段完成任务</th></tr>{table}</table></div><p>官网列表成功{metrics['source_read_successes']}/{metrics['source_read_attempts']}次；详情成功{metrics['read_successes']}/{metrics['read_attempts']}次；详情失败恢复{metrics['retry_recovered']}/{metrics['retry_attempts']}次，列表失败恢复{metrics['source_retry_recovered']}/{metrics['source_retry_attempts']}次。均为尝试次数，不是独立网站覆盖率。</p><details><summary>后台、错误和重启明细</summary><pre>{esc(json.dumps({k:summary[k] for k in ('queue_after','errors','restarts')}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>实际操作体验</h2><p>已完成{len(ui)}个真实页面检查（首次与再次使用，桌面/手机）。岗位库接口延迟：中位数{(summary['library_latency']['median_ms'] or 0)/1000:.2f}秒，最大{(summary['library_latency']['max_ms'] or 0)/1000:.2f}秒，共{len(library_ms)}次采样。包含正在搜索时的本地开发服务，不作为生产环境延迟承诺。</p><p><a href="first-desktop.png">首次桌面</a> · <a href="first-mobile.png">首次手机</a> · <a href="return-desktop.png">再次桌面</a> · <a href="return-mobile.png">再次手机</a> · <a href="library-profile.txt">岗位库耗时定位</a></p></section>
<section><h2>原文抽查</h2><ul>{audits or '<li>待完成原文抽查。</li>'}</ul></section>
<section><h2>本次证据的边界</h2><ul>{''.join(f'<li>{esc(x)}</li>' for x in summary['limits'])}</ul><p>队列状态来自进程退出前的最后快照；三次测试进程均已退出。通过的回归与页面检查不代表下列已发现问题得到修复。</p><p><a href="summary.json">完整统计</a> · <a href="manifest.json">试用配置</a> · <a href="backend-tests.xml">本地回归</a> · <a href="lifecycle-tests.xml">生命周期回归</a> · <a href="validation.json">验证记录</a> · <a href="integrity.json">原文与去重完整性</a></p></section>
<section><h2>实际岗位清单</h2><label>范围<select id="scope"><option value="new">本次新入库</option><option value="all">全部岗位</option></select></label><label>结果<select id="status"><option value="visible">推荐＋值得看看</option><option value="recommended">推荐</option><option value="pending">值得看看</option><option value="excluded">明确不符</option><option value="all">全部</option></select></label><p id="count"></p></section><div id="jobs">{cards}</div></main>
<script>function filter(){{let n=0;document.querySelectorAll('#jobs article').forEach(e=>{{let s=document.querySelector('#status').value;e.hidden=(document.querySelector('#scope').value==='new'&&e.dataset.new!=='1')||(s==='visible'?e.dataset.status==='excluded':s!=='all'&&e.dataset.status!==s);if(!e.hidden)n++}});document.querySelector('#count').textContent='当前显示 '+n+' 条'}}document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filter));filter();</script></html>'''
    (folder / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("new_unique_jobs", "new_counts", "queue_after", "round_count", "library_latency")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    report(parser.parse_args().folder.resolve())

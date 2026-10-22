"""Summarize a timed live trial without modifying its database or judgments."""

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def identity(url):
    parts = urlsplit(url or "")
    job = re.search(r"/position/(?:detail/)?(\d+)", parts.path)
    if job:
        return parts.netloc + ":" + job[1]
    return (url or "").rstrip("/")


def reference_results(references, rounds, latest):
    matches = {m["job_posting_id"]: m for m in latest["library"]["result_matches"]}
    jobs = {identity(j["source_url"]): j for j in latest["jobs"]}
    pools, leads = set(), set()
    for run in rounds:
        leads.update(identity(l["url"]) for l in run["leads"])
        for event in run["trace"]:
            if event["tool"] == "listing_candidates":
                pools.update(identity(c["url"]) for c in event["details"].get("candidates", []))
    result = []
    for ref in references:
        key = identity(ref["url"])
        job = jobs.get(key)
        match = matches.get(job["id"], {}) if job else {}
        status = match.get("review_status")
        stage = {"recommended": "已推荐", "pending": "正文已保存，待核实", "excluded": "系统排除"}.get(status)
        if stage is None:
            stage = "列表候选待处理" if key in pools else "仅有链接线索" if key in leads else "未找回"
        result.append({**ref, "stage": stage, "status": status, "job_id": job["id"] if job else None,
                       "reasons": match.get("mismatch_labels", []),
                       "found": job is not None or key in pools or key in leads})
    return result


def main(folder):
    baseline = read(folder / "baseline.json")
    latest = read(folder / ("final.json" if (folder / "final.json").exists() else "latest.json"))
    complete = read(folder / "complete.json") if (folder / "complete.json").exists() else None
    progress = read(folder / "progress.json")
    rounds = [read(p) for p in sorted(folder.glob("round-*.json"))]
    old = {identity(j["source_url"]) for j in baseline["jobs"]}
    jobs = {j["id"]: j for j in latest["jobs"]}
    library = latest["library"]
    recommendation_rows = [jobs[m["job_posting_id"]] | {"match": m}
                       for m in library["result_matches"] if m["review_status"] == "recommended"]
    deduped = {}
    duplicate_groups = {}
    for job in recommendation_rows:
        key = identity(job["source_url"])
        duplicate_groups.setdefault(key, []).append({"id": job["id"], "url": job["source_url"], "title": job["title"]})
        deduped.setdefault(key, job)
    recommendations = list(deduped.values())
    new = [j for j in recommendations if identity(j["source_url"]) not in old]
    stored_new = {identity(j["source_url"]) for j in latest["jobs"]} - old
    audit = read(folder / "recommendation-audit.json")["rows"]
    audited = {r["id"]: r for r in audit}
    refs = read(folder / "independent-references.json")["references"]
    independent = reference_results(refs, rounds, latest)
    previous = folder.parent / "retrieval-audit-20261019"
    labels = read(previous / "labels.json")["labels"]
    frozen = reference_results([r | labels[r["id"]] for r in read(previous / "manifest.json")], rounds, latest)
    queue_refs = read(folder / "queue-references.json") if (folder / "queue-references.json").exists() else []
    queue = reference_results(queue_refs, rounds, latest)
    totals = Counter()
    for r in rounds:
        for k in ("source_read_attempts", "source_read_successes", "read_attempts", "read_successes",
                  "cache_hits", "retry_attempts", "retry_recovered", "source_retry_attempts", "source_retry_recovered"):
            totals[k] += r["metrics"].get(k, 0)
    semantics = [e for r in rounds for e in r["trace"] if e["tool"] == "source_understanding"]
    semantic_errors = Counter(e.get("error_code") or e.get("details", {}).get("error_code") or "success" for e in semantics)
    discovery_errors = Counter(e.get("error_code") or "unknown" for r in rounds for e in r["trace"]
                               if e["tool"] == "company_discovery_deferred")
    pending = [m for m in library["result_matches"] if m["review_status"] == "pending"]
    unreviewed = [m for m in pending if any("等待当前版本AI理解" in x for x in m["mismatch_labels"])]
    attempt_companies = [c for c in library["company_progress"] if c["status"] != "not_checked"]
    source_read_companies = set()
    source_errors = Counter()
    for r in rounds:
        for e in r["trace"]:
            if e["tool"] == "direct_search":
                d = e.get("details", {})
                if d.get("source_id"):
                    source_read_companies.add(d["source_id"])
                if d.get("reason"):
                    source_errors[d["reason"]] += 1
    timeline = [{"round": r["round"], "kind": r["continue_company"] or "更新全公司轮转",
                 "seconds": r["elapsed_seconds"], "trial_seconds": r["trial_elapsed_seconds"],
                 "recommended_total": r["library_counts"]["recommended"],
                 "new_recommended_this_round": r["metrics"].get("new_recommended_jobs", 0),
                 "status": r["status"]} for r in rounds]
    summary = {"complete": complete, "elapsed_seconds": (complete or progress)["elapsed_seconds"],
               "rounds": len(rounds), "new_stored_unique": len(stored_new),
               "recommended_unique": len({identity(j["source_url"]) for j in recommendations}),
               "new_recommended_unique": len({identity(j["source_url"]) for j in new}),
               "old_recommended_unique": len({identity(j["source_url"]) for j in recommendations if identity(j["source_url"]) in old}),
               "counts": library["counts"], "metrics": dict(totals),
               "semantic_events": dict(semantic_errors), "pending_current_ai": len(unreviewed),
               "company_discovery_errors": dict(discovery_errors),
               "companies_attempted": len(attempt_companies), "companies_total": len(library["company_progress"]),
               "company_discovery": library["company_discovery"],
               "timeline": timeline, "independent_references": independent, "frozen_references": frozen,
               "queue_references": queue, "audit": audit,
               "duplicate_groups": [group for group in duplicate_groups.values() if len(group) > 1],
               "limitations": "单次本地网络与模型运行；推荐复核为助手逐条原文审阅；对照非随机样本，不是全网召回率。搜索条件通过不等于个人全部任职条件通过。"}
    (folder / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    esc = lambda v: html.escape(str(v if v is not None else ""))
    def refs_table(rows):
        return '<div class="scroll"><table><tr><th>岗位</th><th>原文复核</th><th>系统最终去向</th></tr>' + ''.join(
            f'<tr><td><a href="{esc(r["url"])}">{esc(r.get("title", r["id"]))}</a></td><td>{esc(r["reason"])}</td><td>{esc(r["stage"])}</td></tr>' for r in rows) + '</table></div>'
    job_cards = []
    for j in sorted(recommendations, key=lambda j: (identity(j["source_url"]) in old, j["company"] or "", j["title"])):
        a = audited.get(j["id"], {})
        caveats = j["match"].get("mismatch_labels", [])
        card = f'<article data-search="{esc((j["company"] or "") + " " + j["title"])}"><div class="tags"><span>{"本次新增" if identity(j["source_url"]) not in old else "旧岗位复核"}</span><span>{esc(j["company"] or "公司待确认")}</span></div><h3><a href="{esc(j["source_url"])}">{esc(j["title"])}</a></h3>'
        card += f'<p>{esc(a.get("note", "尚未逐条进行助手复核；系统推荐，不代表全部申请资格通过。"))}</p>'
        if a.get("search_scope_verdict") == "borderline":
            card += '<p class="warning">方向边界推荐：应作为相邻方向单列。</p>'
        if a.get("personal_issue"):
            card += f'<p class="warning">{esc(a["personal_issue"])}</p>'
        if caveats:
            card += f'<p class="muted">系统提示：{esc("；".join(caveats))}</p>'
        card += '<details><summary>查看四项筛选判断</summary><ul>' + ''.join(f'<li>{esc(c["field"])}：{esc(c["reason"])}</li>' for c in j["match"]["checks"]) + '</ul></details></article>'
        job_cards.append(card)
    source_fraction = f'{totals["source_read_successes"]}/{totals["source_read_attempts"]}'
    detail_fraction = f'{totals["read_successes"]}/{totals["read_attempts"]}'
    duration = summary["elapsed_seconds"] / 60
    issues = read(folder / "ux-findings.json") if (folder / "ux-findings.json").exists() else []
    issues_html = ''.join(f'<li><strong>{esc(i["title"])}</strong>：{esc(i["detail"])}' + (f' <a href="{esc(i["evidence"])}">证据</a>' if i.get("evidence") else '') + '</li>' for i in issues)
    ui_checks = read(folder / "ui-checks.json") if (folder / "ui-checks.json").exists() else {}
    ui_passes = "；".join(k for k, v in ui_checks.items() if v is True)
    frozen_relevant = [r for r in frozen if r["label"] == "relevant"]
    independently_relevant = [r for r in independent if r["label"] == "relevant"]
    audit_counts = Counter(a.get("search_scope_verdict") for a in audit if a["id"] in {j["id"] for j in recommendations})
    first_new = rounds[0]["metrics"].get("first_new_recommended_ms")
    heading = "连续真实试用完成" if complete else "连续真实试用进行中"
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>JobFlow · 连续真实试用</title>
<style>body{{margin:0;background:#f4f6fa;color:#213149;font:15px/1.7 system-ui,"Microsoft Yahei",sans-serif}}main{{max-width:1120px;margin:auto;padding:34px 20px}}h1{{font-size:30px;margin:10px 0}}h2{{font-size:21px}}h3{{font-size:17px;margin:8px 0}}p{{margin:8px 0}}section,article{{background:white;border:1px solid #dbe2ec;border-radius:12px;padding:22px;margin:20px 0}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.metric{{background:#eaf3ef;padding:16px;border-radius:10px}}.metric strong{{font-size:29px;display:block;color:#246450}}.muted,small{{color:#69778b}}.warning{{background:#fff3d9;color:#705019;padding:10px;border-radius:6px}}a{{color:#235bb4}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid #e3e8ef}}.scroll{{overflow-x:auto}}li{{margin:9px 0}}.tags span{{display:inline-block;background:#eef2f7;padding:3px 9px;margin-right:6px;border-radius:6px;font-size:12px}}input{{box-sizing:border-box;width:100%;padding:12px;border:1px solid #aebbcf;border-radius:7px;font:inherit}}summary{{cursor:pointer}}img{{max-width:100%;border:1px solid #dae1ea;border-radius:8px}}@media(max-width:680px){{.grid{{grid-template-columns:1fr 1fr}}main{{padding:18px 12px}}section{{padding:16px}}}}</style>
<main><p class="muted">2026-10-19 · 北京 / 上海 · 2027届校招 · Agent / RAG / AI 产品</p><h1>{heading}</h1><p>同一个独立数据库连续运行 <strong>{duration:.1f} 分钟</strong>，共 <strong>{len(rounds)} 轮</strong>更新与公司续查。使用当前真实搜索、模型和官网读取流程；未调整业务代码、未重置游标、未突破每公司每轮三条上限。</p>
<div class="grid"><div class="metric"><strong>{len(stored_new)}</strong>新入库岗位（去重）</div><div class="metric"><strong>{summary["recommended_unique"]}</strong>最终可优先查看</div><div class="metric"><strong>{summary["new_recommended_unique"]}</strong>新岗位获得推荐</div><div class="metric"><strong>{summary["old_recommended_unique"]}</strong>旧岗位复核后推荐</div></div>
<section><h2>如何理解这些数量</h2><p>“新入库”包括仍待核实或不符目标的岗位，不等于有效推荐。推荐按官方岗位链接 / 职位ID去重；同一岗位跨轮出现只计算一次。本次个人库基线有 {baseline["library"]["counts"]["recommended"]} 条当前版本推荐，旧结论需要重新理解，故有一部分成果来自旧岗位复核。</p><p>首轮首个新推荐约 {first_new/1000 if first_new else 0:.1f} 秒。结束时仍有 {library["counts"]["needs_review"]} 条待核实，其中 {len(unreviewed)} 条仍提示等待当前版本 AI 理解。覆盖尝试 {len(attempt_companies)}/{len(library["company_progress"])} 家公司；“尝试”不等于官网岗位查完。</p><p>官网列表读取 {source_fraction} 次成功；详情读取 {detail_fraction} 次成功；正文缓存命中 {totals["cache_hits"]} 次。这里按读取尝试计数，包括重复访问，不能当作不同公司的覆盖率。</p></section>
<section><h2>1 · 有没有漏掉好岗位</h2><p>原有冻结对照中的 7 条相关岗位，最终推荐 {sum(r["status"] == "recommended" for r in frozen_relevant)}/7。此次另外通过独立搜索和浏览器核对的 4 条相关岗位，最终推荐 {sum(r["status"] == "recommended" for r in independently_relevant)}/4。这两组都不是全网随机样本。</p>{refs_table(independent)}<details><summary>查看原有 21 条冻结对照</summary>{refs_table(frozen)}</details><details><summary>查看已保存正文却等待复核的对照</summary>{refs_table(queue)}</details><p class="muted">独立对照没有人工添加到被测数据库。它石智航岗位实际已下线，未计入相关岗位分母。证据：<a href="independent-source-texts.json">本次浏览器正文</a>。</p></section>
<section><h2>2 · 有没有推荐错</h2><p>逐条复核 {len(audit)} 条推荐记录的保存原文，对应去重后的 {summary["recommended_unique"]} 个岗位；其中 {audit_counts.get("relevant",0)} 条搜索方向证据明确，{audit_counts.get("borderline",0)} 条属于职责边界偏宽，需要单列相邻方向。这是助手依据原文的审阅，不是独立人工金标准，也不代表个人任职资格全部通过。</p><p class="warning">个人适配存在明确缺口：蔚来“车端 AI Agent 与应用生态系统架构工程师”要求博士，当前个人资料为硕士；列表仍显示全部条件已确认。小米“AI Agent产品经理”还存在院校门槛，“大模型智能体算法工程师”要求一作顶会论文，需要额外核实。当前标签只检查搜索条件，不是个人完整投递资格。</p><p>四个边界样本为字节“AI数据运营（ToB Agent方向）”“Agent数据策略”、360“AI应用开发工程师”和MiniMax“预训练”岗位，分别偏数据运营、策略评测、AI Coding工具引入和通用模型预训练。可以作为相邻方向保留，但不宜与直接承担Agent研发或AI产品设计的岗位同等排序。</p><p><a href="recommendation-audit.json">逐条复核记录</a> · 页面下方提供岗位链接及风险提示。</p></section>
<section><h2>3 · 有没有操作麻烦</h2><ul>{issues_html}</ul><p>操作验证通过：{esc(ui_passes or "搜索中可查看原文和依据；刷新恢复当前搜索进度。收藏与忽略验证待完成")}</p><p>收藏与忽略操作在最终搜索库的另一个副本中执行，不影响上面的搜索数量。</p><details><summary>查看表格使用截图</summary><img src="ui-table-density.png" alt="桌面表格内部横向滚动，操作列在右侧"></details><details><summary>查看忽略后重新收藏的结果</summary><img src="ui-saved-restored.png" alt="收藏夹中重新出现商汤岗位，状态为已保存"></details></section>
<section><h2>为什么还会卡住</h2><p>本次记录到新公司发现阶段 {discovery_errors.get("discovery_timeout",0)} 次超时。当前公司库可以轮转查询，但新增公司并未稳定变成可读来源。</p><p>原文理解事件中，{semantic_errors.get("semantic_timeout",0)} 次超时，{semantic_errors.get("semantic_budget",0)} 次触及本轮语义预算。预算事件不是实际模型请求成功后的误判；它表示部分正文还没得到当前AI结论。应先改善队列和重试调度，再分别处理已完成判断中的语义边界问题。</p><p>正文读取失败续查：{totals["retry_attempts"]} 次尝试，恢复 {totals["retry_recovered"]} 次；官网列表重试单独记录为 {totals["source_retry_recovered"]}/{totals["source_retry_attempts"]}。不能将正文恢复数说成官网列表已恢复。</p></section>
<section><h2>每轮实际产出</h2><div class="scroll"><table><tr><th>轮次</th><th>操作</th><th>耗时</th><th>结束于</th><th>系统累计推荐（未去重）</th><th>本轮新岗位推荐</th></tr>{''.join(f'<tr><td>{r["round"]}</td><td>{esc(r["kind"])}</td><td>{r["seconds"]:.1f} 秒</td><td>{r["trial_seconds"]/60:.1f} 分钟</td><td>{r["recommended_total"]}</td><td>{r["new_recommended_this_round"]}</td></tr>' for r in timeline)}</table></div><p class="muted">此表保留系统当时显示的数量，顶部总数和下方岗位清单已按职位ID去重。本轮“新岗位推荐”只指当轮首次入库即推荐；之前入库待核实、后续才推荐的岗位，在最终累计中仍算本次新岗位推荐，所以不能直接求和。</p></section>
<section><h2>优先改进顺序</h2><ol><li>按官网职位ID统一链接身份，合并推广参数导致的重复记录、计数及收藏状态。</li><li>让已保存、明显相关的正文稳定完成当前版本复核；为历史复核提供独立任务和可见进度，避免只有反复搜索才能消化。</li><li>将个人硬门槛与搜索条件区分展示；对博士、院校限制等提前提示，将数据运营、工具提效等相邻方向单独分组。</li><li>扩大可产出岗位的公司来源；用独立找到的沐瞳、智元、德赛西威等岗位验证发现、入口核验和读取的完整链路。</li><li>简化岗位列表：主列表保留关键信息，把解释移入详情；详情可直接收藏，并保留刷新前的筛选条件。</li></ol></section>
<section><h2>实际岗位清单</h2><p>共 {summary["recommended_unique"]} 条系统推荐；标明本次新增或旧岗复核。个人资格和开放状态仍以投递前官网核对为准。</p><input id="filter" placeholder="按公司或岗位名称筛选" aria-label="筛选岗位清单"><div id="jobs">{''.join(job_cards)}</div></section>
<p class="muted">{esc(summary["limitations"])} 个人原库未修改，测试结果在独立副本中；未投递任何申请。<a href="report.json">汇总数据</a> · <a href="configuration.json">测试配置（不含密钥）</a> · <a href="complete.json">起止时间</a></p></main>
<script>document.querySelector('#filter').addEventListener('input',e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('#jobs article').forEach(x=>x.hidden=!x.dataset.search.toLowerCase().includes(q))}})</script></html>'''
    (folder / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({k:summary[k] for k in ("elapsed_seconds","rounds","new_stored_unique","recommended_unique","new_recommended_unique","old_recommended_unique","pending_current_ai")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    main(parser.parse_args().folder)

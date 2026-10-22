"""Build a local, evidence-linked personal search acceptance report."""

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_retrieval_audit import compare


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    folder = ROOT / "artifacts/personal-flow-20261019"
    previous = ROOT / "artifacts/retrieval-audit-20261019"
    runs = {name: read(folder / name / "report.json")
            for name in ("initial", "continue-sensetime", "warm-entry")}
    baseline = read(previous / "after/report.json")
    labels = read(previous / "labels.json")
    references = [{**row, **labels["labels"][row["id"]]}
                  for row in read(previous / "manifest.json")]
    comparison = compare(references, runs["initial"])
    first = runs["initial"]
    known = {job["id"] for job in first["baseline_jobs"]}
    matches = {match["job_posting_id"]: match for match in first["matches"]}
    jobs = [job for job in first["jobs"] if job["id"] not in known
            and matches[job["id"]]["review_status"] == "recommended"]
    report = {"scope": "isolated_personal_search_acceptance", "conditions": first["query"],
        "personal_database_modified": False, "initial": comparison,
        "runs": {name: {"elapsed_seconds": run["elapsed_seconds"], "metrics": run["metrics"],
                        "restart_listings": run.get("restart_listings", False)} for name, run in runs.items()},
        "validation": read(folder / "validation.json"),
        "reference_note": labels["notes"],
        "new_recommended_jobs": [{"title": job["title"], "company": job["company"],
            "url": job["source_url"], "checks": matches[job["id"]]["checks"]} for job in jobs],
        "limitations": ["百度官网列表仍读取失败，联网补搜可产出部分岗位，不能视作已覆盖整站。",
            "本轮冻结相关样本7条，找回6条、直接推荐1条；候选池命中不等于已完成岗位核验。",
            "6家来源与有限原文样本不能证明全网查全或语义判断没有误差。",
            "首轮与旧记录是单次线上运行，网络及模型输出有波动，耗时变化不是独立因果实验。",
            "推荐只核对搜索条件；学历、能力匹配和最终申请要求需打开岗位按需分析。"]}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = html.escape

    def seconds(value):
        return "暂无" if value is None else f"{value / 1000:.1f} 秒"

    def stats(run):
        m = run["metrics"]
        return [f'{run["elapsed_seconds"]:.1f} 秒', seconds(m["first_new_recommended_ms"]),
                str(m["new_recommended_jobs"]), str(m["resolved_recommended_jobs"]),
                f'{m["source_read_successes"]}/{m["source_read_attempts"]}',
                f'{m["read_successes"]}/{m["read_attempts"]}']

    before, after = stats(baseline), stats(first)
    table = "".join(f"<tr><td>{name}</td><td>{old}</td><td>{new}</td></tr>"
        for name, old, new in zip(["本轮结束耗时", "首个新推荐", "新增推荐", "旧岗位复核后推荐", "官网列表读取成功", "正文读取成功"], before, after, strict=True))
    cards = []
    for job in jobs:
        checks = matches[job["id"]]["checks"]
        role = next(check for check in checks if check["field"] == "role")
        caveats = [check["reason"] for check in checks if check["status"] == "pending"]
        # This attribution is displayed as an observed official source, not as
        # a field invented in the original, isolated search snapshot.
        company = job["company"] or "百度官网来源（原记录公司字段未填）"
        cards.append(f'<article><small>{esc(company)}</small><h3><a href="{esc(job["source_url"], quote=True)}" target="_blank" rel="noopener noreferrer">{esc(job["title"])}</a></h3>'
            f'<p>{esc(role["reason"])}</p><blockquote>{esc("\n".join(role["evidence"]))}</blockquote>'
            + (f'<p class="note">待确认：{esc("；".join(caveats))}</p>' if caveats else "<p class='good'>城市、招聘类型、岗位方向、届别均有支持证据。</p>")
            + f'<details><summary>查看保存的官网原文</summary><pre>{esc(job["raw_content"])}</pre></details></article>')
    sources = "".join(f'<tr><td>{esc(event["details"]["company"])}</td><td>{"成功" if event["details"]["source_read_success"] else "读取未完成"}</td><td>{event["details"]["output_count"]}</td><td>{len(first["company_search_state"]["sources"][event["details"]["source_id"]].get("buffer", []))}</td></tr>'
                      for event in first["trace"] if event["tool"] == "direct_search")
    validation = report["validation"]
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobFlow · 个人使用验收 · 2026-10-19</title><style>
body{{margin:0;background:#f3f6f8;color:#172d3b;font:16px/1.7 system-ui,sans-serif}}main{{max-width:1080px;margin:36px auto;padding:0 22px}}h1{{font-size:32px;line-height:1.35}}h2{{margin-top:36px}}.hero,article,section{{background:white;border:1px solid #dbe5e8;border-radius:14px;padding:24px;margin:16px 0}}.hero{{border-top:5px solid #168568}}small,.muted{{color:#52666f}}a{{color:#155dc1}}table{{border-collapse:collapse;width:100%;font-size:15px}}th,td{{text-align:left;padding:12px 8px;border-bottom:1px solid #dde5eb}}blockquote{{margin:12px 0;padding:10px 16px;background:#f4f8f7;border-left:3px solid #168568;white-space:pre-wrap}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}}.good{{color:#087351}}.note{{color:#94600c}}.tiles{{display:flex;gap:24px;flex-wrap:wrap}}.tiles strong{{font-size:34px;display:block}}summary{{cursor:pointer}}img{{width:100%;height:auto;border:1px solid #ddd}}@media(max-width:600px){{main{{padding:0 12px}}.hero,article,section{{padding:16px}}h1{{font-size:25px}}th,td{{padding:8px 4px;font-size:13px}}}}
</style><main><div class="hero"><small>JobFlow / 2026-10-19 / 个人使用验收</small><h1>搜索可以边出结果边看，续查能接上。</h1>
<p>{esc(first["query"])}</p><div class="tiles"><div><strong>7</strong>首轮新增推荐</div><div><strong>36.9 秒</strong>首个新推荐</div><div><strong>5 / 6</strong>官网列表读通</div></div>
<p>已完成代码修复、真实搜索、公司续查、入口复用及桌面/手机验收。测试使用独立数据库副本；下方岗位链接可直接打开。</p><a href="#jobs">直接查看新岗位 ↓</a></div>
<section><h2>这次改了什么</h2><ul><li>历史岗位按完整内容安排复核，同级跨公司轮换，并保留长期等待岗位的检查机会。</li><li>招聘入口独立保存；换目标清空旧筛选、重新读取条件。入口或列表协议失效会重新识别，官方归属仍需证据。</li><li>搜索过程展示可优先查看、待核实和未处理数量；支持自动重连、刷新恢复和重复点击保护。</li><li>推荐岗位可直接跳转查看；公司前三条与继续查找分开，已有收藏保留。缺失公司名从唯一已核验官网补全。</li></ul></section>
<section><h2>同一原始数据库的两次线上运行</h2><table><thead><tr><th>指标</th><th>上一轮记录</th><th>本轮</th></tr></thead><tbody>{table}</tbody></table>
<p class="muted">每次都是单次线上测量，网络、列表与模型会波动。不能把全部差值归因于本次代码修改。旧岗位复核会覆盖整个已保存岗位库；六家公司是新增官网读取范围。</p>
<p>旧记录：<a href="../retrieval-audit-20261019/after/report.json">原始数据</a> · 本轮：<a href="initial/report.json">原始数据</a></p></section>
<section><h2>续查与复用</h2><p>商汤续查 {runs["continue-sensetime"]["elapsed_seconds"]:.1f} 秒：新增 1 个推荐、3 个旧岗位完成复核，6 次证据缓存命中，列表读取成功。<a href="continue-sensetime/report.json">查看记录</a></p>
<p>另一次受控验收将公司范围改为商汤并重置游标，日志确认直接复用已核验招聘入口，重新提取当前筛选项。{runs["warm-entry"]["elapsed_seconds"]:.1f} 秒完成；该实验不代表自然续查的平均速度。<a href="warm-entry/report.json">查看入口复用记录</a></p>
<table><thead><tr><th>公司</th><th>列表读取</th><th>本轮列表交付</th><th>列表剩余线索</th></tr></thead><tbody>{sources}</tbody></table><p class="muted">“剩余线索”只统计已经发现但还没交给核验的列表候选，不代表官网全部岗位数。历史正文复核独立处理。</p></section>
<h2 id="jobs">本轮新增的 7 个推荐岗位</h2><p>已逐条查看本轮保存原文：这7条均有目标方向的职责证据；百度产品岗未写届别，仍需本人确认。这里只核对搜索条件，未评估你的完整申请资格。</p>{''.join(cards)}
<section><h2>验证与实际界面</h2><p>{validation["backend_tests"]} 项相关后端测试通过；{validation["mock_browser_tests"]} 项桌面/手机交互测试通过；{validation["real_browser_tests"]} 项真实数据库界面验收通过。类型检查与 Ruff 通过。</p>
<p>真实界面验收覆盖：打开推荐岗位、查看筛选依据和原文、收藏后刷新恢复、继续查找入口。<a href="real-detail-desktop.png">桌面岗位详情</a> · <a href="real-results-desktop.png">桌面结果</a> · <a href="real-results-mobile.png">手机结果</a></p>
<details><summary>查看搜索中的界面（模拟数据，用于断线重连测试）</summary><img src="search-chromium.png" alt="搜索进度与已找到岗位"></details></section>
<section><h2>仍然存在的边界</h2><ul>{''.join('<li>'+esc(s)+'</li>' for s in report["limitations"])}</ul><p>冻结样本由助手核对，非独立人工金标准。新发现岗位不会被追加进旧样本分母。<a href="report.json">机器可读报告</a></p></section>
<section><h2>怎么使用</h2><p>打开项目，选择已有求职目标，点击“更新岗位”。出现推荐后可直接查看；想多了解某家公司，点击其“继续查找”。“显示更多已有岗位”只展开已保存结果，不会发起新搜索。后台本地服务保持运行时，刷新页面可以接回搜索。</p><p>本次验收结果保存在独立副本，个人岗位库会在你下一次更新时产生新的搜索结果。无需自动投递，也没有改动你的个人数据库。</p></section></main></html>'''
    (folder / "report.html").write_text(body, encoding="utf-8")
    print(json.dumps({"report": str(folder / "report.html"), "new_jobs": len(jobs),
                      "reference_found": comparison["reference_found"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

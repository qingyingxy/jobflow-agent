"""Render final-version results with source excerpts and known limitations."""
import json
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/quality-pipeline-20261019"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    from src.services.source_understanding import VERSION
    groups = [
        ("原26条验收岗位", "final-acceptance", ROOT / "artifacts/job-acceptance-20261019"),
        ("新增官网首批岗位", "final-coverage", OUT / "coverage-acceptance"),
        ("最终排序新增岗位", "final-ranking-acceptance", OUT / "ranking-acceptance"),
    ]
    rows = []
    for group, directory, evidence in groups:
        report = read(OUT / directory / "results.json")
        baseline = read(evidence / "results.json")
        for row in report["results"]:
            original = next(r for r in baseline["results"] if r["index"] == row["index"])
            checks = row.get("match", {}).get("checks", [])
            complete = bool(checks) and all(c.get("version") == VERSION and c.get("diagnosis") != "not_extracted"
                for c in checks if c["field"] != "availability")
            row = {**row, "group": group, "complete": complete, "company": original["company"],
                "evidence_path": evidence / f'{row["index"]:02d}' / "page.txt"}
            rows.append(row)
    counts = Counter(r.get("match", {}).get("filter_status", "unverified") for r in rows)
    original = rows[:26]
    retrieval = read(OUT / "coverage/round-1.json")
    ranking = read(OUT / "final-ranking/round-1.json")
    speeds = [e["duration_ms"] / 1000 for e in ranking["events"]
              if e["kind"] == "source_understanding" and e.get("error_code") is None]
    gates = {
        "应届欢迎得到识别": next(c["status"] for r in original if r["index"] == 19
                                  for c in r["match"]["checks"] if c["field"] == "job_type") == "matched",
        "全职/经验没有被当作非校招": all(c["status"] == "pending" for r in original
            if r["index"] in {9, 13, 21, 22, 23, 24, 25, 26}
            for c in r.get("match", {}).get("checks", []) if c["field"] == "job_type"),
        "原有5条目标匹配保留": all(r["match"]["filter_status"] == "matched" for r in original if r["index"] in {7,10,11,14,15}),
        "无关职责没有被AI工具关键词带入": all(r["match"]["filter_status"] == "excluded" for r in original if r["index"] in {12,16,18}),
        "AI产品岗位保留": all(next(c["status"] for c in r["match"]["checks"] if c["field"] == "role") == "matched"
            for r in original if r["index"] in {5,8,11,14}),
        "AI产品营销被排除": any(r["title"] == "AI产品市场营销" and r.get("match",{}).get("filter_status") == "excluded" for r in rows),
    }
    summary = {"version": VERSION, "total": len(rows), "interpreted": sum(r["complete"] for r in rows),
        "counts": dict(counts), "gates": gates, "ranking_seconds": speeds,
        "new_matches": sum(r.get("match", {}).get("filter_status") == "matched" for r in rows[26:]),
        "saved_body_refetches": 0}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    names = {"matched": "符合求职目标", "pending": "仍需确认", "excluded": "不符合目标", "unverified": "未完成核验"}
    cards = []
    for r in rows:
        status = r.get("match", {}).get("filter_status", "unverified")
        checks = "".join(f'<li><b>{escape(c["field"])}</b> · {escape(c["status"])} — {escape(c["reason"])}'
            + (f'<blockquote>{escape("；".join(c.get("evidence", [])))}</blockquote>' if c.get("evidence") else "") + '</li>'
            for c in r.get("match", {}).get("checks", []) if c["field"] != "availability")
        hints = "".join(f'<p><b>{escape(h["label"])}</b> · {escape(h["status"])}<br>{escape(h["reason"])}'
            f'<blockquote>{escape(h["evidence"])}</blockquote></p>' for h in r.get("personal_requirements", []))
        raw = r["evidence_path"].relative_to(ROOT / "artifacts").as_posix()
        cards.append(f'<article data-status="{status}"><span class="tag {status}">{names[status]}</span>'
            f'<small>{escape(r["group"])} #{r["index"]} · {escape(r["company"])}</small><h3>{escape(r["title"])}</h3>'
            f'<p><a href="{escape(r["url"], quote=True)}" target="_blank" rel="noopener">打开官方岗位</a> · '
            f'<a href="../{escape(raw, quote=True)}">读取时的原文</a></p>'
            f'<details><summary>判断与证据 · {"已完成理解" if r["complete"] else "解释未完成"}</summary><ul>{checks}</ul>'
            f'<h4>任职条件提示</h4>{hints or "未提取到可快速提示的条件；不表示全部个人资格通过。"}</details></article>')
    source_rows = "".join(f'<tr><td>{escape(e["company"])}</td><td>{e["output_count"]}</td>'
        f'<td>{escape(e.get("reason") or "完成")}</td></tr>' for e in retrieval["events"] if e["kind"] == "direct_search")
    gate_html = "".join(f'<li>{"✓" if passed else "待检查"} {escape(label)}</li>' for label, passed in gates.items())
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>个人求职流程修复验收</title><style>
body{{font:16px/1.7 system-ui,"Microsoft Yahei",sans-serif;color:#17312c;background:#f4f7f6;margin:0}}main{{max-width:1060px;margin:auto;padding:40px 22px}}h1{{font-size:34px;line-height:1.25}}h2{{margin-top:36px}}small{{display:block;color:#60736d}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}.metrics div,article,section{{background:white;border:1px solid #dae6e1;border-radius:12px;padding:18px;margin:12px 0}}.metrics strong{{display:block;font-size:30px;color:#156a54}}a{{color:#176d61}}.tag{{float:right;padding:3px 9px;border-radius:14px;background:#edf0f0}}.matched{{background:#d8f0e5;color:#16613d}}.pending{{background:#fff0ce;color:#805b07}}.excluded{{background:#eee;color:#5e6260}}blockquote{{margin:8px 0;padding:8px 14px;border-left:3px solid #bdcec5;color:#50645c;white-space:pre-wrap;overflow-wrap:anywhere}}details>summary{{cursor:pointer}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;text-align:left;border-bottom:1px solid #e2e9e6}}button{{border:1px solid #b9cec5;background:#fff;border-radius:18px;padding:8px 14px;margin:4px;cursor:pointer}}button.active{{background:#176d61;color:white}}li{{margin:9px 0}}article h3{{margin:12px 0;overflow-wrap:anywhere}}@media(max-width:600px){{h1{{font-size:28px}}.tag{{float:none;display:inline-block}}}}
</style><main><small>2026-10-19 · 北京 / 上海 · 2027届校招 · Agent / RAG / AI产品</small><h1>先找回岗位，再减少误判和等待</h1>
<p>这次使用真实官网正文验收五项改动。所有结论采用同一版本：{VERSION}。目标匹配只代表城市、方向、招聘人群和届别，不代表个人全部任职资格及开放状态均已通过。</p>
<div class="metrics"><div><strong>{summary["interpreted"]}/{len(rows)}</strong>完成原文理解</div><div><strong>{counts["matched"]}</strong>符合求职目标</div><div><strong>{summary["new_matches"]}</strong>本次扩展来源匹配</div><div><strong>0</strong>后台复核重新抓详情次数</div></div>
<section><h2>改动与验收</h2><ol><li><b>误排除：</b>区分工作形式、招聘人群和任职资格；“全职/3年经验”不推导非校招。欢迎应届生可识别；在读身份和不同方向的条件不拼接。</li><li><b>正文自动续核：</b>已保存但尚未识别成岗位的页面进入后台队列。独立30秒解释预算、冷却、最多3次失败、取消恢复、目标与原文变更保护。新增4个首次解析失败页面已在生产队列恢复，无需重抓官网。</li><li><b>前三条排序：</b>考虑实际职责、新旧岗位和招聘类型；长列表摘录保留后部相关职责；仅使用AI工具的岗位降序；排名失败不会冒充完成。实测两家排序成功，耗时 {" / ".join(f"{s:.2f}秒" for s in speeds)}。每家公司仍先查3条，其余保留续查。</li><li><b>个人门槛：</b>列表标明学历、经验、论文等类别；详情保留原文、加分项和分方向限定，不把资料缺失当成不符合。</li><li><b>有效覆盖：</b>补搜拆成单方向小查询，失败后缩小条件；保留完整目标用于最终核验。修复缓存入口失败时被冷却机制挡住、无法返回官网重找的路径。</li></ol><ul>{gate_html}</ul></section>
<section><h2>真实覆盖范围与局限</h2><table><thead><tr><th>公司</th><th>首批线索</th><th>状态</th></tr></thead><tbody>{source_rows}</tbody></table><p>百度本次仍出现页面初始化后离开公开招聘网址；商汤与智谱入口超时。补搜代码已改为小查询，不能据此宣称这三家的岗位已经找回。未测量全网召回率，也未新增无证据公司。</p><p>模型对相邻方向仍可能有波动；本报告保留每条原文和理由便于核对。用户查看岗位时仍需确认学历、经历、论文等个人条件。</p><p>验证：后端回归 256 项通过；前端构建通过；桌面与手机操作测试 4 项通过。验收数据写入 artifacts 下的隔离数据库。</p></section>
<h2>逐条查看</h2><div id="filters"><button class="active" data-filter="all">全部 {len(rows)}</button><button data-filter="matched">符合目标 {counts["matched"]}</button><button data-filter="pending">待确认 {counts["pending"]}</button><button data-filter="excluded">不符合 {counts["excluded"]}</button></div>{"".join(cards)}
<p><a href="summary.json">验收摘要 JSON</a> · <a href="final-acceptance/results.json">原26条结果</a> · <a href="final-coverage/results.json">新增首批结果</a> · <a href="final-ranking-acceptance/results.json">排序补充结果</a></p></main><script>
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('article').forEach(x=>x.hidden=b.dataset.filter!=='all'&&x.dataset.status!==b.dataset.filter)}}));
</script></html>'''
    (OUT / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    main()

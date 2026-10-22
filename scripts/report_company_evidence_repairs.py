"""Build a compact report from saved company and listing acceptance evidence."""
import json
import sys
from collections import defaultdict
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.url_reader import parse_html_document

OUT = ROOT / "artifacts/company-evidence-repairs-20261019"


def read(path):
    return json.loads((OUT / path).read_text(encoding="utf-8"))


def link(url, label=None):
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(label or url)}</a>'


companies = read("final-validation/companies.json")
rounds = [read(f"final-validation/round-{n}.json") for n in (1, 2)]
unique = {c["url"]: c for r in rounds for c in r["candidates"]}
by_company = defaultdict(list)
for candidate in unique.values():
    by_company[candidate["company"]].append(candidate)
source_names = {e["source_id"]: e["company"] for r in rounds for e in r["events"] if e["kind"] == "direct_search"}
counts = [{"company": name, "candidates": len(by_company[name]),
           "state": rounds[-1]["states"][source_id]["reason"]} for source_id, name in source_names.items()]
recovered = {e["company"] for r in rounds for e in r["events"]
             if e["kind"] == "direct_search" and e.get("source_retry") and e.get("source_read_success")}
supplement = []
latest_failures = {}
for folder in ("fragment-recovery", "region-recovery", "region-resume"):
    batch = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((OUT / folder).glob("round-*.json"))]
    supplement.extend(batch)
    names = {e["company"] for r in batch for e in r["events"] if e["kind"] == "direct_search"}
    for name in names:
        latest_failures[name] = [e for r in batch for e in r["events"] if e["kind"] == "listing_entry_failure" and e["company"] == name]
extra = {c["url"]: c for r in supplement for c in r["candidates"] if c["url"] not in unique}
failures = [e for errors in latest_failures.values() for e in errors]
overall = {**unique, **extra}
last_states = dict(rounds[-1]["states"])
for run in supplement:
    last_states.update(run["states"])
unresolved = [{"company": source_names[source_id], "url": state.get("listing_url"),
               "body_excerpt": parse_html_document(state.get("listing_html", "")).text[:180],
               "reason": state.get("ui_navigation", {}).get("reason") or state.get("reason")}
              for source_id, state in last_states.items()
              if not any(c["company"] == source_names[source_id] for c in overall.values())]
summary = {"verified_companies": sum(c["status"] == "verified" for c in companies),
           "pending_companies": sum(c["status"] != "verified" for c in companies),
           "main_acceptance": {"sources": len(source_names), "readable_sources": sum(c["candidates"] > 0 for c in counts),
                               "unique_candidate_links": len(unique), "company_counts": counts,
                               "failure_recovery_companies": sorted(recovered)},
           "supplemental_new_links": len(extra), "supplemental_failures": failures,
           "overall_unique_links": len(overall), "overall_readable_sources": len({c["company"] for c in overall.values()}),
           "unresolved": unresolved}
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
company_rows = []
for company in companies:
    proof = company.get("evidence", {}).get("corroboration", {})
    quote = proof.get("quote") or ""
    evidence = escape(quote) + (" · " + escape(proof.get("observation", "")) if quote else "")
    company_rows.append(f'<tr><td>{escape(company["company"])}</td><td>{"通过" if company["status"] == "verified" else "待核验"}</td>'
                        f'<td>{link(company["homepage_url"], "公司主页")} · {link(company["career_url"], "招聘入口")}</td>'
                        f'<td>{evidence or escape(company["reason"])}</td></tr>')
count_rows = ''.join(f'<tr><td>{escape(c["company"])}</td><td>{c["candidates"]}</td><td>{escape(c["state"])}</td></tr>' for c in counts)
job_rows = ''.join(f'<tr><td>{escape(c["company"])}</td><td>{link(c["url"], c["title"][:140])}</td></tr>' for c in unique.values())
extra_rows = ''.join(f'<li>{escape(c["company"])} · {link(c["url"], c["title"][:120])}</li>' for c in extra.values())
failure_rows = ''.join(f'<li>{escape(e["company"])}：{escape(e.get("error_detail", e["error_code"]))}</li>' for e in failures)
unresolved_rows = ''.join(f'<li>{escape(e["company"])}：最后列表 {link(e["url"])}，读取正文为「{escape(e["body_excerpt"])}」，状态 {escape(e["reason"])}。</li>' for e in unresolved)
html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>官网核验与动态列表修复验收 · 2026-10-19</title>
<style>body{{font:16px/1.75 system-ui,sans-serif;color:#182c3a;background:#f3f6f8;margin:0}}main{{max-width:1100px;margin:40px auto;padding:0 22px 50px}}h1{{font-size:30px;line-height:1.4}}h2{{margin-top:32px;font-size:23px}}p{{max-width:950px}}.metrics{{display:flex;flex-wrap:wrap;gap:16px}}.metric{{background:white;padding:18px 25px;border:1px solid #d6e0e5;border-radius:10px;min-width:180px}}strong.num{{display:block;font-size:32px;color:#116a60}}table{{width:100%;border-collapse:collapse;background:white;font-size:14px}}td,th{{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #dde5ea;overflow-wrap:anywhere}}th{{background:#e6eef2}}a{{color:#116a9b}}.scroll{{overflow-x:auto}}.note{{padding:16px;background:#fff6dc;border-left:4px solid #b78320}}code{{font-size:13px}}footer{{margin-top:30px;color:#52616d}}</style>
<main><p>JobFlow Agent · 2026-10-19 · 真实保存证据 + 有界官网实读</p><h1>先消除误挡，再恢复列表读取</h1>
<div class="metrics"><div class="metric">既有公司记录<strong class="num">0 → {summary['verified_companies']} / 6</strong>核验通过，保留原句与路径</div><div class="metric">主验收官网<strong class="num">{summary['main_acceptance']['readable_sources']} / 7</strong>两轮内读出候选链接</div><div class="metric">主验收候选<strong class="num">{len(unique)}</strong>按真实网址去重</div></div>
<p class="note">这里统计的是读到的岗位候选链接，尚未逐条完成北京/上海、2027 校招、Agent/RAG/AI 产品及个人硬门槛核验。包含社招和其他方向，不能把 {len(unique)} 条都算作适合投递的岗位。</p>
<h2>公司规则核对</h2><p>使用原有 6 条待核验记录及缓存原文；关闭新公司联网发现，不依靠新搜索补出证据。缺失的官网页面允许重新读取。所有验证在隔离数据库中完成，个人数据库未导入这些试验结果。</p>
<div class="scroll"><table><thead><tr><th>公司</th><th>核验</th><th>观察到的地址</th><th>证据或保留原因</th></tr></thead><tbody>{''.join(company_rows)}</tbody></table></div>
<p>DeepSeek：政府原文明确声明官网域名；阶跃：高校正文标注官网网址，但超链接格式异常；千寻：组合品牌名及正文标注网址；Kimi：主站已有独立证据，同域招聘页有品牌和实际回链。Moonshot AI 与 Kimi 有品牌重叠，不重复计为新增有效公司；Sunrise 仍缺可读独立归属证据。</p>
<h2>动态读取修复与两轮结果</h2><p>每个官网每轮最多 30 秒实际读取、最多交接 3 条候选；并发 2，保留续查状态。等待名额的时间独立计量。京东恢复了通用卡片和空搜索结果识别；小鹏保留真实列表路径；DeepSeek 支持官网直接出链到具体 ATS 岗位；千寻不再因校招路径与“社招职位”导航文字冲突而整页跳过。</p>
<div class="scroll"><table><thead><tr><th>公司</th><th>两轮去重候选</th><th>最后状态</th></tr></thead><tbody>{count_rows}</tbody></table></div>
<p>明确记录的失败续查恢复公司：{escape('、'.join(sorted(recovered)) or '无')}。阶跃本次读到的是已验证社招入口，不能因公司通过核验就宣称校招检索成功。每公司三条上限及后续分页仍保留。</p>
<h2>后续入口复测</h2><p>另修复图片式 ATS 链接、公开 <code>/apply/…#/jobs</code> 路由与 HTTP 请求不携带片段地址的问题。已验证身份的招聘站内允许通用页面标题，后发现的校招入口优先续查。Kimi 两轮、字节三轮加一次保存进度续查，补测新增 {len(extra)} 条主验收中未出现的链接。主验收加补测合计 {len(overall)} 条去重候选，来自 {summary['overall_readable_sources']} / 7 个官网。</p><ul>{extra_rows or '<li>补测未增加候选链接。</li>'}</ul><ul>{failure_rows or '<li>最新补测没有记录入口失败；达到预算的页面仍需继续读取。</li>'}</ul>
<h2>主验收岗位链接</h2><div class="scroll"><table><thead><tr><th>公司</th><th>观察到的岗位标题 / 卡片摘要</th></tr></thead><tbody>{job_rows}</tbody></table></div>
<h2>仍未解决的来源</h2><ul>{unresolved_rows or '<li>本批来源均有候选产出，仍不代表已查全。</li>'}</ul>
<h2>验证边界</h2><p>公司独立归属、动态读取、搜索续查、跨租户边界等核心回归通过；前端生产构建通过，桌面/手机界面 12 项检查通过。新增浏览器路由修复另跑针对性回归。未生成或提交任何求职申请。</p>
<p>可复核数据：<a href="companies.json">初次公司复核</a> · <a href="final-validation/companies.json">最终公司状态</a> · <a href="final-validation/round-1.json">主验收第 1 轮</a> · <a href="final-validation/round-2.json">主验收第 2 轮</a> · <a href="summary.json">精简统计</a></p>
<footer>本报告只描述此批来源、此时点与此预算内的实际结果，不代表全网岗位覆盖率。</footer></main></html>'''
(OUT / "report.html").write_text(html, encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))

"""Build the evidence report for the two real daily-use scenarios."""

import argparse
import html
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value):
    return html.escape(str(value), quote=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder.resolve()
    primary, alternate = (read(folder / name / "daily-summary.json") for name in ("primary", "alternate"))
    ptime, atime = (read(folder / name / "complete.json") for name in ("primary", "alternate"))
    cross = read(folder / "alternate/multi-goal-audit.json")
    primary_cases = read(folder / "primary/audit.json")
    alternate_cases = read(folder / "alternate/audit.json")
    primary_jobs = {j["id"]: j for j in primary["jobs"]}
    screenshots = [folder / "alternate" / f"switch-{name}.json" for name in ("desktop", "mobile")]
    ui = [read(p) for p in screenshots]
    assert all(x["passed"] and x["saved_job_retained"] and x["inspected"] for x in ui)
    total_minutes = (ptime["elapsed_seconds"] + atime["elapsed_seconds"]) / 60
    labels = {"recommended": "推荐", "pending": "待核实 / 值得看看", "excluded": "明确不符", "invalid_detail": "正文读取未完成"}

    def queue(summary, lane, phase):
        return summary[f"queue_{phase}"]["lanes"][lane]["remaining"]

    def ratio(summary, prefix):
        m = summary["metrics"]
        return f'{m[prefix + "successes"]}/{m[prefix + "attempts"]}'

    rows = [
        ("真实运行 / 搜索轮数", f'{ptime["elapsed_seconds"] / 60:.1f} 分钟 / {len(primary["rounds"])} 轮', f'{atime["elapsed_seconds"] / 60:.1f} 分钟 / {len(alternate["rounds"])} 轮'),
        ("结束时推荐记录", f'{primary["before_counts"]["recommended"]} → {primary["after_counts"]["recommended"]}', f'0 → {alternate["after_counts"]["recommended"]}（搜索期间曾找到 3 条）'),
        ("期间新增岗位记录", "8 条，扣除已确认的同岗重复后为 7 条", f'{alternate["new_unique_jobs"]} 条；含旧目标后台续核产出'),
        ("新增且结束时推荐", "4 条，扣除已确认重复后为 3 条", "2 条；另 1 条曾推荐后退回待核实"),
        ("已有岗位转为推荐", str(primary["existing_promoted"]), str(alternate["existing_promoted"])),
        ("首次本轮结果", "9.6 秒（复用历史缓存）", "48.6 秒"),
        ("首条新推荐", "前台指标未记录；后台有产出，无法准确计时", "165.5 秒（约 2 分 46 秒）"),
        ("官网列表读取成功 / 尝试", ratio(primary, "source_read_"), ratio(alternate, "source_read_")),
        ("岗位详情读取成功 / 尝试", ratio(primary, "read_"), ratio(alternate, "read_")),
        ("失败详情续查恢复 / 尝试", f'{primary["metrics"]["retry_recovered"]}/{primary["metrics"]["retry_attempts"]}', f'{alternate["metrics"]["retry_recovered"]}/{alternate["metrics"]["retry_attempts"]}'),
        ("正文判断待处理", f'{queue(primary, "source", "before")} → {queue(primary, "source", "after")}', f'{queue(alternate, "source", "before")} → {queue(alternate, "source", "after")}'),
        ("个人任职资格待处理", f'{queue(primary, "qualifications", "before")} → {queue(primary, "qualifications", "after")}', f'{queue(alternate, "qualifications", "before")} → {queue(alternate, "qualifications", "after")}'),
    ]
    table = "".join(f"<tr><th scope='row'>{esc(a)}</th><td>{esc(b)}</td><td>{esc(c)}</td></tr>" for a, b, c in rows)
    audits = []
    for case in alternate_cases:
        observed = (case.get("observed") or {}).get("review_status", "unknown")
        audits.append(f"""<article class="case"><p class="eyebrow">人工核对 · {esc(labels[case['expected']])} / 系统结束状态 · {esc(labels.get(observed, observed))}</p>
<h3>{esc(case['title'])}</h3><p>{esc(case['finding'])}</p><a href="{esc(case['url'])}" target="_blank" rel="noreferrer">打开招聘原文 ↗</a>
<details><summary>查看本次保存的正文</summary><pre>{esc(case['raw_content'])}</pre></details></article>""")
    original_audit = "".join(f"<li><strong>{esc(primary_jobs[c['id']]['company'])} · {esc(primary_jobs[c['id']]['title'][:110])}</strong><p>{esc(c['finding'])}</p></li>" for c in primary_cases)
    trace_rows = []
    example = "job_9837cf26e16343f2bd79"
    for event in cross["histories"].get(example, []):
        from_goal = "AI 目标" if event["previous_goal"] == "goal_510142e137774f3ea1f7" else "Java 目标"
        to_goal = "AI 目标" if event["current_goal"] == "goal_510142e137774f3ea1f7" else "Java 目标"
        trace_rows.append(f"<tr><td>{esc(event['at'][11:19])} UTC</td><td>{from_goal} → {to_goal}</td><td>{esc(event['body_hash'][:12])}</td></tr>")
    lost = cross["primary_previously_recommended_now_changed"]
    evidence = [
        ("原条件统计", "primary/daily-summary.json"), ("Java 条件统计", "alternate/daily-summary.json"),
        ("两目标覆盖证据", "alternate/multi-goal-audit.json"), ("15 秒观察日志", "alternate/decision-history.jsonl"),
        ("阿里重复记录", "primary/duplicate-audit.json"), ("未读岗位列表线索", "primary/unread-relevant-listings.json"),
        ("自然语言解析问题", "primary/alternate-goal-with-development.json"), ("最终保存条件", "alternate/alternate-goal.json"),
        ("桌面目标切换验收", "alternate/switch-desktop.json"), ("手机目标切换验收", "alternate/switch-mobile.json"),
        ("原条件人工审计", "primary/audit.json"), ("Java 条件人工审计", "alternate/audit.json"),
        ("第一组重启记录", "primary/complete.json"), ("第二组重启记录", "alternate/complete.json"),
    ]
    evidence_links = "".join(f'<li><a href="{url}">{esc(name)}</a></li>' for name, url in evidence)
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobFlow · 日常使用与跨目标试用报告</title><style>
:root{{--ink:#172a32;--muted:#50646e;--line:#dbe3e4;--green:#126454;--amber:#98601d}}*{{box-sizing:border-box}}body{{margin:0;background:#f1f5f3;color:var(--ink);font:16px/1.75 "Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1120px;margin:auto;padding:48px 28px 72px}}h1{{font-size:clamp(27px,4vw,42px);line-height:1.3;letter-spacing:-.03em;margin:10px 0 18px}}h2{{font-size:24px;line-height:1.4;margin:0 0 16px}}h3{{font-size:18px;margin:8px 0}}p{{margin:10px 0}}a{{color:#196451;text-underline-offset:3px;overflow-wrap:anywhere}}section{{background:white;border:1px solid var(--line);border-radius:18px;padding:28px;margin:24px 0}}.eyebrow{{font-size:12px;letter-spacing:.07em;color:var(--green);font-weight:700}}.lede{{font-size:19px;max-width:960px}}.muted,small{{color:var(--muted)}}.chips{{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}}.chip{{padding:7px 13px;background:#fff;border:1px solid var(--line);border-radius:30px;font-size:13px}}.warning{{border-left:5px solid #c78932;background:#fff8ec;padding:18px 20px;border-radius:10px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.card{{background:#f5f8f7;padding:20px;border-radius:12px}}.metric{{font-size:36px;color:var(--green);font-weight:700;line-height:1.3}}.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}thead{{background:#edf4f1}}th{{font-weight:600}}td{{min-width:190px}}.case{{border-top:1px solid var(--line);padding:20px 0}}.case:first-child{{border:0}}details{{margin-top:14px}}summary{{cursor:pointer;color:var(--green);font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;max-height:430px;overflow:auto;font:14px/1.8 inherit;background:#f5f7f7;padding:16px;border-radius:10px}}li{{margin:12px 0}}.evidence{{columns:2;padding-left:20px}}img{{width:100%;border:1px solid var(--line);border-radius:10px}}code{{overflow-wrap:anywhere;background:#edf1f2;padding:2px 5px;border-radius:4px;font-size:13px}}.priority{{color:var(--amber);font-weight:700}}footer{{font-size:13px;color:var(--muted)}}@media(max-width:680px){{main{{padding:24px 14px 40px}}section{{padding:20px 16px;margin:18px 0}}.grid{{grid-template-columns:1fr}}.evidence{{columns:1}}.lede{{font-size:17px}}td{{min-width:180px}}}}
</style></head><body><main>
<header><div class="eyebrow">JOBFLOW / REAL USE AUDIT / 2026-10-19</div><h1>日常流程能跑通，<br>换求职方向仍不够稳定。</h1><p class="lede">真实试用两组条件、模拟四次进入，共运行 <strong>{total_minutes:.1f} 分钟</strong>。收藏、刷新与重启恢复通过；新方向确实找到了合适岗位，但判断保存方式让部分推荐再次退回待核实。</p>
<div class="chips"><span class="chip">真实联网 + AI 判断</span><span class="chip">北京 / 上海 · Agent / RAG / AI 产品</span><span class="chip">杭州 / 深圳 · Java 后端</span><span class="chip">均为 2027 届校招</span></div></header>
<div class="warning"><strong>这次是测试和定位，未修改产品逻辑。</strong>单一目标可以辅助自用；多目标判断隔离尚未通过验收。推荐代表主要搜索条件吻合，个人资格及实际开放状态仍需核对。</div>
<section><h2>结果一眼看懂</h2><div class="grid"><div class="card"><p class="eyebrow">原条件 · 13.4 分钟</p><div class="metric">84 → 98</div><p>系统推荐记录增加 14 条。新增入库 8 条中有 1 条已确认重复；扣除后新增 7 条，其中 3 条推荐，另有 10 条已有岗位完成复核转为推荐。</p></div><div class="card"><p class="eyebrow">新条件 · 9.7 分钟</p><div class="metric">找到过 3 条 / 留住 2 条</div><p>小红书 Java 平台开发、Agentic ops 后端仍显示推荐；商汤深圳后端岗原本已推荐，却被旧目标后台判断覆盖后退回待核实。</p></div></div>
<p class="muted">98 是含历史岗位的推荐记录总数，包含已知重复，不能理解成这次新找到 98 个岗位。两组新增数均来自试用前后快照，不把重复读取次数当新岗位。</p></section>
<section><h2>两组实测对比</h2><div class="scroll"><table><thead><tr><th>指标</th><th>北京 / 上海 · AI 方向</th><th>杭州 / 深圳 · Java 后端</th></tr></thead><tbody>{table}</tbody></table></div><p class="muted">读取比例只针对本次尝试；缓存命中分别为 {primary['metrics']['cache_hits']} / {alternate['metrics']['cache_hits']} 次，不混入联网读取成功率。新目标期间入库的 13 条包括原目标后台续核产生的岗位，不等于 13 条 Java 岗位。</p></section>
<section><h2>最先需要修：按目标保存判断</h2><p>本次观察到 <strong>{cross['jobs_overwritten']} 个岗位发生 {cross['cross_goal_overwrites']} 次跨目标覆盖</strong>，其中 {len(cross['same_body_round_trip_jobs'])} 个岗位在正文相同的情况下发生往返覆盖。一个目标刚判断完，另一个目标又替换这份结论，前一个目标因此重新进入队列。</p>
<p>现在只有一个 <code>source_understanding</code> 保存位置，判断指纹却包含求职条件。指纹校验会拒用别的目标结论，这避免了直接串用推荐，但原目标的分析成果也随之失效。</p>
<p>切回原目标时总数仍为 98，但其中 <strong>{len(lost)} 条原推荐已退回待核实</strong>，被其他新增推荐抵消；只看总数会漏掉这个问题。</p>
<details><summary>查看同一岗位反复覆盖的时间证据</summary><p>样例：Agent System Backend Engineer Graduate (AML Ark) - 2027 Start。相同正文哈希下发生以下变化：</p><div class="scroll"><table><thead><tr><th>时间</th><th>判断归属变化</th><th>正文哈希前缀</th></tr></thead><tbody>{''.join(trace_rows)}</tbody></table></div></details>
<p class="priority">建议：按“岗位正文版本 × 求职条件版本 × 判断版本”分别保存结果和重试状态，页面优先读取当前目标的已完成结果；后台重复任务合并，并给当前目标优先级。</p></section>
<section><h2>真实岗位核对：新条件</h2><p>这组人工核对基于本次保存的官方正文，检查城市、届别、招聘类型与 Java/后端证据。不能据此估算全网召回率。</p>{''.join(audits)}</section>
<section><h2>另外四处影响日常体验</h2><ol>
<li><strong>“Java 后端开发”被额外加了一道待核实条件。</strong><p>输入完整表达时，系统将“开发”留下并生成 <code>意图待核实：开发</code>，导致推荐被堵住。保留这次失败回执后，改用用户选择的“Java 后端”才继续试用。需要把通用职业用语与真正附加要求分开；无法解析的词应提示用户确认，不能默默增加硬门槛。</p></li>
<li><strong>同一官方职位的链接参数变化仍会重复入库。</strong><p>阿里职位 <code>199907720043</code> 的两个链接，仅 <code>deptCodes</code> 不同，却存成两个岗位。应使用可信官网职位 ID 归并，并维护链接别名；不能一律删除查询参数，因为部分网站把职位 ID 放在参数里。</p></li>
<li><strong>官网读取及前三条排序仍会延迟好岗位。</strong><p>原条件的列表缓冲中有 39 条标题相关、尚未保存详情的线索，其中商汤“27届大模型Agentic算法工程师”列出北京/上海和直接职责。它们是待确认线索，不是 39 条已证实遗漏。应该优先处理城市、届别和职责更明确的新岗位，并允许用户按公司续查。</p><p>华为页面的模板占位符被存成“What We Offer”岗位，则说明还需要通用的正文质量检查：未渲染内容返回页面读取队列，保留具体失败原因。</p></li>
<li><strong>已有库加载和资格处理仍有等待。</strong><p>原条件页面的岗位库请求中位耗时 {primary['library_latency_ms']['median'] / 1000:.2f} 秒，最慢 {primary['library_latency_ms']['max'] / 1000:.2f} 秒。正文队列 93→59，但资格队列 142→161。建议读取已保存判断、分页返回列表，并按用户收藏和当前目标相关性安排资格分析。</p></li>
</ol></section>
<section><h2>已经通过的日常操作</h2><div class="grid"><div><ul><li>桌面与手机：打开正文、看到来源链接并收藏。</li><li>刷新及后续访问：收藏、筛选状态和正文仍可读取。</li><li>忽略后重新收藏：状态显示正确。</li><li>两目标往返切换，刷新后保留最后目标。</li><li>换目标后仍能在收藏夹找到原目标收藏。</li><li>新目标推荐详情能打开，显示筛选证据。</li></ul></div><div><ul><li>四次实际进入、两次独立进程重启均正常完成。</li><li>重启保留岗位、收藏和公司查询进度。</li><li>运行中没有捕获到后台 worker 异常退出。</li><li>普通搜索和公司续查均走真实服务入口。</li><li>桌面和手机无页面脚本错误、无横向溢出。</li></ul></div></div><p class="muted">精确轮数：第一组 2 次普通搜索 + 1 次公司续查；第二组 2 次普通搜索 + 2 次公司续查。搜索从正式服务入口启动，浏览器覆盖浏览/收藏/条件编辑/切换；公司续查按钮的浏览器点击案例本轮未执行。独立通过的 UI 场景为 8 项：原条件桌面/手机各两次、新建条件、修改条件、桌面/手机目标切换。最后两项增加了等待推荐实际可见的断言后重新通过；重复运行不额外计数。</p>
<details><summary>查看桌面和手机截图</summary><div class="grid"><figure><img loading="lazy" src="alternate/switch-desktop.png" alt="桌面切换至Java目标后的岗位列表"><figcaption>桌面 · 新目标</figcaption></figure><figure><img loading="lazy" src="alternate/alternate-detail-mobile.png" alt="手机上的新目标岗位详情及筛选依据"><figcaption>手机 · 推荐详情</figcaption></figure></div></details></section>
<section><h2>原条件人工核对摘要</h2><p>审计 {len(primary_cases)} 个实际岗位：确认城市不符等明确排除、保留 AI 产品和相邻研发方向，并指出 FDE 客户交付岗位的排序需要更细区分。未据此宣称全部 98 条推荐都适合本人。</p><details><summary>展开逐项判断</summary><ul>{original_audit}</ul></details></section>
<section><h2>下一轮验收标准</h2><ol><li><strong>先修多目标结果隔离。</strong>原目标和 Java 目标各自完成判断后，后台运行和切换都不能让已完成结果因另一个目标而丢失。</li><li><strong>修条件解析和岗位身份。</strong>“Java后端”与“Java后端开发”得到等价意图；同一官方职位换筛选参数，数量和收藏保持一致。</li><li><strong>再提升有效产出。</strong>未渲染模板不进岗位正文库；选择明确匹配的新线索优先读取；以“新增可见推荐 / 时间”衡量，而非只看调用量和入库量。</li></ol></section>
<section><h2>证据与测试边界</h2><ul class="evidence">{evidence_links}</ul><p class="muted">使用 artifacts 下独立数据库，正式个人数据库和服务未修改。真实网络与模型只发送已确认条件和公开招聘资料。两组测试在同一天压缩访问间隔，没有快进系统时钟，不能替代连续几天稳定性测试；也没有完整岗位真值集，因此无法给出全网漏检率或总体推荐准确率。人工核对依赖本次抓取保存的正文，未逐个再次独立抓取全部官网。</p><p class="muted">本轮只新增验收脚本和报告；产品缺陷保留。新增 Python 审计脚本 Ruff 检查通过，前端 TypeScript 检查通过。未重新宣称此前的全部后端测试在本轮运行。</p></section>
<footer>报告生成自两组真实快照、官方正文与浏览器验收回执。源代码与原始证据一并保留，可复查具体岗位。</footer>
</main></body></html>"""
    (folder / "report.html").write_text(document, encoding="utf-8")
    print(json.dumps({"report": str(folder / "report.html"), "real_minutes": round(total_minutes, 2), "manual_cases": len(primary_cases) + len(alternate_cases)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

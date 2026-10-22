"""Publish evidence from the fixed cohort audit, separately from ByteDance recovery."""
import html
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/job-acceptance-20261019"

# Independent assistant review of the captured bodies, not user-approved labels.
# Each quote is checked against that candidate's saved visible text below.
REVIEWS = [
    (1, "pending", "北京/杭州；方向相关；实习和全职均可，但未说明2027届校招。", "【岗位类别】：实习/全职", "本科及以上；平台或系统方向经历"),
    (2, "pending", "同一个申请入口包含研发、研究、产品等多个方向；须选具体方向，且未写2027届。", "各个招聘方向均可实习或全职。", "各方向学历、年限不同，不能互相套用"),
    (3, "pending", "北京Agent数据岗位，缺少2027届证据；不能把某一细分方向的3年要求套给全部方向。", "招聘方向【实习/全职】：", "前端、移动端、后端等要求3年以上；安全方向另列要求"),
    (4, "pending", "北京/上海Agent基建研发，未写校招或毕业届别。", "Agent 训推框架维护：负责 Agent 训练与推理全链路框架的开发、优化与稳定性保障", "需要相关基建能力"),
    (5, "pending", "北京/上海AI产品方向保留；产品规划与落地职责明确，缺少校招和2027届证据。", "负责企业级通用 Agent 解决方案的产品规划与落地", "本科及以上"),
    (6, "pending", "北京/上海Code Agent研究职责明确，未写校招和2027届。", "构建code agent的基础能力，包括planning能力、测例、代码生成能力。", "机器学习及研究经历；硕博只是加分项"),
    (7, "fit", "北京；标题明确27届校招；本人开发端侧Agent核心模块。", "【27届校招】智能座舱端侧Agent研发工程师（北京）", "C++/Java、Agent技术基础"),
    (8, "pending", "北京可选；AI产品方向保留，未说明校招及2027届。", "定义并推进大模型在真实任务场景中的 Agent 能力", "Agent产品、评测及数据构造能力"),
    (9, "experience", "北京/上海且方向相关，但有明确5年资历要求，应先提示门槛；不能据此把招聘类型判为社招。", "5 年及以上后端或基础架构研发经验", "5年以上研发经验，本科及以上"),
    (10, "fit", "北京可选；2027届校招；机器人Agent架构、RAG检索、部署职责明确。", "设计并实现高并发、可扩展的机器人Agent框架，集成长短期记忆模块与 RAG 检索系统", "硕士及以上；Agent、VLM实战"),
    (11, "fit", "北京/上海可选；2027届校招；AI产品规划、设计、评测和交付职责明确。", "2027届硕士及以上学历", "硕士及以上；产品能力"),
    (12, "off_target", "城市和毕业时间范围符合，但主业是机械设计；用AI工具辅助机械工作不等于Agent/RAG/AI产品岗位。", "负责产品结构设计、外购件选型、出图、装配、调试等工作", "机械相关专业"),
    (13, "experience", "北京/上海Agent评测系统研发，但要求3年以上开发经验；资历门槛与招聘类型应分开显示。", "有3年及以上前后端开发经验", "3年以上开发经验，本科以上"),
    (14, "fit", "北京可选；2027届校招；Physical Agent产品定义、需求落地与验收职责明确。", "参与Physical Agent的产品架构和功能定义", "本科及以上；机器人与Agent产品知识"),
    (15, "fit", "北京/上海可选；2027届本科以上；仿真平台Agent应用开发职责明确。", "2027 届本科及以上毕业生", "本科及以上；C++/Python及相关项目实践"),
    (16, "off_target", "北京、2027毕业时间范围符合；工作是数据挖掘和普通业务建模，AI用于辅助开发。", "挖掘数据建模应用于公司业务相关场景：推荐、风险控制、用户挖掘等", "本科及以上；数据挖掘方向"),
    (17, "pending", "北京Coding Agent设计与全栈开发，未写校招和2027届。", "负责 AI Coding / Coding Agent 产品方向设计与全栈开发", "独立工程与产品落地能力"),
    (18, "off_target", "北京2027届校招，但职责是嵌入式底层及外设驱动；Agent仅出现在辅助编码加分项。", "参与机器人/数采设备嵌入式底层软件开发、系统配置、功能集成", "嵌入式与底层驱动能力"),
    (19, "pending", "北京可选，明确欢迎应届生且含Agent框架组件方向；仍缺2027届范围，不能把资深优先当作应届生禁止。", "我们欢迎应届毕业生及两年以内经验的新鲜力量加入", "多方向、多资历入口；需要选择具体方向"),
    (20, "pending", "北京；本人做Agent训练与评测工程，缺校招和2027届证据。", "建设和完善数据产出和管理、 Agent 训练与评测流程", "大模型训练与系统开发实际经验"),
    (21, "experience", "QA测试岗要求3年以上经验，地点也未写；不应作为已确认校招推荐。", "3年以上QA测试经验", "3年以上QA；岗位侧重测试"),
    (22, "pending", "北京Agentic工具链相关，未确认2027校招。门户标注社会招聘值得提示，但AI仅引用全职作排除证据不成立。", "Agentic 工具链 - 将 Agent 用于开发、测试、排障与运营", "要求线上系统实践；需确认招聘人群"),
    (23, "pending", "Coding/SWE Agent训练职责明确；工作地点为“-”，校招/届别未确认。不能以全职直接排除校招。", "Actively engage in improving Coding/SWE Agent capabilities through SFT", "本科及以上；地点及招聘人群待确认"),
    (24, "pending", "北京；标题有Agent，但正文交付是内容平台后端，具体Agent职责仍不清楚，校招和届别也未确认。", "你将负责内容平台方向的后端主线研发", "资深后端、Go及内容平台经历"),
    (25, "pending", "正文明确北京/上海等地点及Agentic RL研发；地点不能只取元数据“-”。缺校招/2027届证据。", "工作地点：北京 · 上海 · 深圳 · 新加坡 · 硅谷", "千卡训练、Agentic RL发表或上线经历；系统AI切分仍未完成"),
    (26, "pending", "Agent/MCP融入产品功能的研发职责明确；地点及2027校招未确认，不能以全职直接排除。", "将 Function Call、MCP、Agent 等能力融入产品功能", "生产系统、分布式/API/部署等能力"),
]
LABELS = {"fit": "目标条件匹配", "off_target": "方向不符", "experience": "明确资历门槛", "pending": "需要确认"}


def compact(value):
    return re.sub(r"\s+", "", value)


def esc(value):
    return html.escape(str(value), quote=True)


def main():
    original = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    recovery = json.loads((OUT / "recovery.json").read_text(encoding="utf-8"))
    initial = {r["index"]: r for r in original["results"]}
    updates = {r["index"]: r for r in recovery["results"]}
    reviewed = []
    for index, status, note, quote, requirement in REVIEWS:
        raw = (OUT / f"{index:02d}/page.txt").read_text(encoding="utf-8")
        assert compact(quote) in compact(raw), (index, "unbound quote")
        source = initial[index]
        latest = updates.get(index, source)
        reviewed.append({"index": index, "company": source["company"], "url": source["url"],
            "title": latest.get("parsed_title", source.get("parsed_title", source["title"].split("发布于")[0])),
            "status": status, "note": note, "quote": quote, "requirement": requirement,
            "initial_system": source.get("match", {}).get("review_status", source.get("error_code")),
            "latest_system": latest.get("match", {}).get("review_status", latest.get("error_code"))})
    supplemental = json.loads((OUT / "bytedance-acceptance/results.json").read_text(encoding="utf-8"))
    extra = []
    degrees = ["本科及以上", "本科及以上", "本科及以上", "硕士及以上", "硕士及以上；有研究与安全实践要求", "本科及以上"]
    cities = ["上海、北京（另有杭州/深圳）", "上海、北京", "北京、上海", "北京、上海（另有深圳）", "上海", "上海"]
    for row, degree, city in zip(supplemental["results"], degrees, cities, strict=True):
        raw = (OUT / f'bytedance-acceptance/{row["index"]:02d}/page.txt').read_text(encoding="utf-8")
        assert "2027届校园招聘" in raw and "2027届获得" in raw
        extra.append({"index": row["index"], "title": row["parsed_title"], "url": row["url"],
            "status": "fit", "city": city, "requirement": degree, "quote": "2027届校园招聘"})
    errors = Counter(e.get("error_code") or "success" for e in original["events"])
    recovery_complete = sum(r.get("verified") and not any(c.get("diagnosis") == "not_extracted"
        for c in r.get("match", {}).get("checks", [])) for r in recovery["results"])
    summary = {"reviewer": "本次助手逐条阅读已抓取原文；非用户人工标注、非独立盲测",
        "query": original["query"], "original_count": 26, "page_reads": 26,
        "review_counts": dict(Counter(r["status"] for r in reviewed)), "original_reviews": reviewed,
        "initial_model_calls": original["model_calls"], "initial_model_events": dict(errors),
        "body_resume_selected": len(recovery["results"]), "body_resume_completed": recovery_complete,
        "body_resume_model_calls": recovery["model_calls"], "body_resume_detail_refetches": 0,
        "supplemental_bytedance_count": 6, "supplemental_reviews": extra,
        "fresh_first_three_seconds": 19.891, "old_state_first_three_seconds": 20.688,
        "regression_tests": 111,
        "remaining_defects": [
            "AI把全职当作非校招，至少4条需确认线索被错误排除（22、23、24、26）；21也有错误类型理由。",
            "同是3/5年经验门槛，13被当成非校招，9仍只是待确认，资历与招聘性质没有一致分开。",
            "19原文明确欢迎应届生，AI招聘类型理由遗漏了这句；仍需核对2027届范围。",
            "10条解释未完成记录用保存正文续核后完成8条；2的模型输出校验、25的正文区间识别仍失败。",
            "列表候选中有机械、普通数据挖掘、嵌入式岗位，占用了详情读取配额；最终推荐已挡住这3条。"],
        "limits": ["只验收固定候选及修复后的字节补充样本，不能估计全网漏岗率。",
            "目标条件匹配不是全部个人资格通过；学历、经历、真实开放状态和投递流程仍应核对。",
            "原26条的5条系统推荐均有原文支持；未发现该组最终推荐的城市/届别/方向误荐。",
            "所有写入发生在隔离数据库，未改个人岗位库或发送投递。"]}
    (OUT / "acceptance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def card(row, supplemental=False):
        prefix = "bytedance-acceptance/" if supplemental else ""
        title = row["title"]
        company = "字节跳动" if supplemental else row["company"]
        note = row["city"] + "；2027届校招；Agent研发职责已核对。" if supplemental else row["note"]
        system = "系统与本次原文复核一致" if supplemental else f'系统首轮：{row["initial_system"]}；续核后：{row["latest_system"]}'
        return f'''<article data-status="{row['status']}" data-extra="{int(supplemental)}"><div class="eyebrow">{'补充' if supplemental else '原样本'} {row['index']:02d} · {esc(company)} <span class="badge {row['status']}">{LABELS[row['status']]}</span></div><h3><a href="{esc(row['url'])}" target="_blank" rel="noreferrer">{esc(title)}</a></h3><p>{esc(note)}</p><blockquote>{esc(row['quote'])}</blockquote><p class="small">条件提醒：{esc(row['requirement'])}</p><footer>{esc(system)} · <a href="{prefix}{row['index']:02d}/page.txt">保存的原文</a> · <a href="{prefix}{row['index']:02d}/result.json">系统核验记录</a></footer></article>'''

    cards = "".join(card(r) for r in reviewed if r["status"] == "fit")
    cards += "".join(card(r, True) for r in extra)
    cards += "".join(card(r) for r in reviewed if r["status"] != "fit")
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>岗位验收与字节入口诊断 · 2026-10-19</title><style>
    :root{color-scheme:light;--ink:#182c3c;--muted:#526674;--line:#dce4e8;--green:#066658}*{box-sizing:border-box}body{margin:0;background:#f4f6f7;color:var(--ink);font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:36px 24px 70px}h1{font-size:32px;line-height:1.3;margin:8px 0 16px}h2{font-size:23px;margin:34px 0 12px}h3{font-size:18px;line-height:1.5;margin:9px 0}p{margin:9px 0}.eyebrow{font-size:13px;color:var(--muted)}.lede{max-width:900px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.metric,article,.panel{background:white;border:1px solid var(--line);border-radius:14px;padding:20px}.metric b{display:block;font-size:32px;line-height:1.3}.metric span,.small{font-size:14px;color:var(--muted)}.panel{margin:16px 0}.success{border-left:5px solid var(--green)}.warning{border-left:5px solid #bc7e21}a{color:#145f8b;text-underline-offset:3px}button{font:inherit;border:1px solid #b8c9d1;background:white;border-radius:24px;padding:7px 15px;cursor:pointer}button.active{background:#163e4e;color:white}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}article[hidden]{display:none}.badge{display:inline-block;font-size:12px;margin-left:5px;border-radius:5px;padding:2px 7px;background:#edf1f3}.fit{background:#e0f3eb;color:#066658}.off_target{background:#fdebec;color:#934c51}.experience{background:#fff2d9;color:#8e6319}blockquote{font-size:14px;margin:12px 0;padding:8px 12px;background:#f5f8fa;border-left:3px solid #c4d7e1}footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px;margin-top:14px}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;border-bottom:1px solid var(--line);padding:10px;vertical-align:top}code{word-break:break-all;font-size:13px}ul{padding-left:23px}.note{color:var(--muted);font-size:14px}@media(max-width:700px){main{padding:24px 16px}.metrics{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}h1{font-size:26px}.table{overflow:auto}}
    </style></head><body><main><div class="eyebrow">JOBFLOW · 实际官网验收 · 2026-10-19</div><h1>原26条中确认5条目标匹配，<br>字节修复后另外确认6条</h1><p class="lede">按北京/上海、2027届校招、Agent / RAG / AI产品核对。原26条与字节补充6条分别计数；这里的“匹配”仅指目标条件，学历和项目经历仍需逐项对照。</p>
    <div class="metrics"><div class="metric"><b>26 / 26</b><span>原候选详情正文读到</span></div><div class="metric"><b>5 + 6</b><span>原样本匹配 + 字节补充匹配</span></div><div class="metric"><b>19.9 秒</b><span>字节首批3条列表结果</span></div><div class="metric"><b>8 / 10</b><span>已有正文续核完成</span></div></div>
    <section class="panel success"><b>本轮入口修复已通过真实流程验收。</b><p>新搜索约19.9秒拿到字节首批3条；第二轮复用列表缓冲再取3条。用上轮卡在404的旧进度继续搜索，也在约20.7秒恢复3条。默认每公司3条与“未查完”状态保留。111项相关回归测试通过。</p></section>
    <h2>先看这11条</h2><p class="note">原样本5条：小鹏3条、千寻2条，其中2条是AI产品岗。字节6条均在当前岗位正文写明2027届校园招聘，地点包含北京或上海；AI for Science及安全研究员要求硕士及以上。</p><div class="controls"><button data-filter="fit" class="active">目标匹配 11</button><button data-filter="original">原26条全部</button><button data-filter="pending">需确认 15</button><button data-filter="experience">资历门槛 3</button><button data-filter="off_target">方向不符 3</button><button data-filter="all">全部32条</button></div><div class="grid">'''
    page += cards + '''</div><h2>字节到底返回了什么</h2><div class="panel table"><table><thead><tr><th>观察地址/环节</th><th>实际证据</th><th>结论</th></tr></thead><tbody><tr><td><code>jobs.bytedance.com/campus/</code></td><td>HTTP 200，无HTTP跳转；浏览器标题“字节跳动校园招聘”。静态HTML主要含社会招聘、全球招聘出链。</td><td>校招首页仍然有效。</td></tr><tr><td>浏览器执行脚本后</td><td>真实导航出现 <code>/campus/position</code>；静态HTML没有该入口。</td><td>需要先加载动态导航。</td></tr><tr><td><code>jobs.bytedance.com/experienced</code></td><td>静态内容确实含 <code>href="/position"</code>；动态导航另有 <code>/experienced/position</code>。</td><td>旧链接来自网站本身，不是程序丢失路径前缀。</td></tr><tr><td><code>jobs.bytedance.com/position</code></td><td>HTTP 404；浏览器正文 Not Found。</td><td>这个地址确实失效；不能靠重复读取恢复。</td></tr><tr><td><code>jobs.bytedance.com/en</code></td><td>HTTP 302 到 <code>joinbytedance.com/</code>。</td><td>这是全球招聘入口，不能替代目标校招列表。</td></tr></tbody></table><p>根因：静态读取发现了全球招聘出链，程序就提前认为入口足够，跳过了校招页的动态加载。之后跟到全球站、国内社招页及其旧链接。</p><p>修复：已在目标校招/实习入口时，通用页脚出链不再阻止浏览器读取本页导航；只跟随实际出现的目标入口。旧失败查询自动重读一次原目标入口，保留已有岗位、去重记录与其他续查入口。</p><p><a href="bytedance/diagnosis.json">HTTP和浏览器对照</a> · <a href="bytedance-recovery/round-1.json">新搜索首轮</a> · <a href="bytedance-old-state-resume/round-1.json">旧失败进度恢复</a></p></div>
    <h2>验收没有通过的部分</h2><section class="panel warning"><ul><li><b>“全职”被误当成“非校招”。</b>续核时22、23、24、26被排除，所引用的证据只有全职。应保留待确认；门户标注社会招聘与单岗招聘人群的关联需另核验，不能拿错误理由代替。</li><li><b>资历门槛与招聘类型混用。</b>9有5年经验要求却仅显示待确认，13有3年要求被判非校招。应该单列经验要求，不用年限推断招聘渠道。</li><li><b>已有正文仍有解释失败。</b>首轮10条解释未完成；保存正文续核完成8条，未重新抓详情。2的模型输出校验、25的正文区间识别仍未完成；本次已另行阅读原文留出人工确认结论。</li><li><b>候选排序仍浪费配额。</b>机械、普通数据挖掘、嵌入式3条进入详情队列，但最终推荐已排除。应在排序阶段利用职责摘要减少这类候选。</li><li><b>应届生明示语义仍有遗漏。</b>19明确“欢迎应届毕业生”，系统招聘类型解释未引用这句。2027届仍须确认，但不能把“未写校园招聘四字”等同于未接受应届生。</li></ul><p>本轮只修复并回归了官网入口与旧进度恢复。上述AI判断问题已留存具体岗位、原文和结果，尚未宣称修复。</p></section>
    <h2>验收口径与限制</h2><p>原26条：5条目标匹配、3条方向不符、3条有明确经验门槛、15条需确认。5条原系统推荐均有原文支持，没有发现这组推荐的城市、届别或方向误荐；这不能证明没有全网漏岗。</p><p>首轮真实模型使用30次调用预算；后段6条触及预算上限，另有超时与输出校验失败。续核使用独立预算及30秒等待，不代表普通搜索的默认等待已调整。字节补充6条另做详情核验，不算入原26条。</p><p class="note">逐条原文复核由本次助手完成，不是用户人工标注或独立盲测。未提交任何申请，未写入个人岗位库。岗位开放状态及投递成功没有在本轮验证。<a href="acceptance-summary.json">完整验收数据</a> · <a href="results.json">首轮系统结果</a> · <a href="recovery.json">正文续核结果</a></p></main><script>
    const buttons=[...document.querySelectorAll('button[data-filter]')];function select(kind){for(const b of buttons)b.classList.toggle('active',b.dataset.filter===kind);for(const a of document.querySelectorAll('article'))a.hidden=!(kind==='all'||kind==='original'&&a.dataset.extra==='0'||kind===a.dataset.status)}buttons.forEach(b=>b.addEventListener('click',()=>select(b.dataset.filter)));select('fit');</script></body></html>'''
    (OUT / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("original_count", "page_reads", "review_counts", "body_resume_completed", "supplemental_bytedance_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Compare frozen, assistant-reviewed official references with recorded searches."""

import argparse
import asyncio
import hashlib
import html
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.company_registry import enabled_company_sources
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.job_url import canonical_job_url


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def identity(url):
    return canonical_job_url(url) if url else ""


def state_urls(state):
    for item in state.get("buffer", []):
        if state.get("reader_kind") == "html":
            yield identity(item["id"])
        elif state.get("base"):
            yield identity(state["base"].rstrip("/") + "/position/" + str(item["id"]) + "/detail")


def compare(rows, run):
    matches = {m["job_posting_id"]: m for m in run["matches"]}
    jobs = {identity(j["source_url"]): j for j in run["jobs"]}
    leads = {identity(lead["url"]): lead for lead in run["leads"]}
    pools, handed = {}, set()
    for event in run["trace"]:
        details = event.get("details", {})
        if event["tool"] == "listing_candidates":
            for candidate in details["candidates"]:
                pools[identity(candidate["url"])] = candidate
        elif event["tool"] == "listing_handoff":
            handed.add(identity(details["url"]))
    retained = {url for state in run["company_search_state"].get("sources", {}).values()
                for url in state_urls(state)}
    result = []
    for row in rows:
        url = identity(row["url"])
        job = jobs.get(url)
        match = matches.get(job["id"], {}) if job else {}
        lead = leads.get(url, {})
        found = url in pools or url in leads or job is not None
        status = match.get("review_status")
        stage = ("已推荐" if status == "recommended" else "已入库待AI理解/条件核实" if status == "pending"
                 else "系统排除" if status == "excluded" else "候选池保留待续查" if url in retained
                 else "线索待核验" if found else "本轮未找回")
        result.append({"id": row["id"], "found": found, "candidate_rank": pools.get(url, {}).get("rank"),
                       "direct_handoff": url in handed, "retained": url in retained,
                       "status": status, "stage": stage, "failure_code": lead.get("failure_code")})
    relevant = {r["id"] for r in rows if r["label"] == "relevant"}
    return {"metrics": run["metrics"], "elapsed_seconds": run["elapsed_seconds"],
            "relevant_total": len(relevant),
            "reference_found": sum(r["found"] for r in result if r["id"] in relevant),
            "reference_recommended": sum(r["status"] == "recommended" for r in result if r["id"] in relevant),
            "rows": result}


async def replay(before):
    """Same captured NIO pool: isolate fallback ordering from network/model noise."""
    state = before["company_search_state"]["sources"]["nio"]
    captured = next(e["details"]["candidates"] for e in before["trace"]
                    if e["tool"] == "listing_candidates" and e["details"].get("source_id") == "nio"
                    and e["details"].get("stage") == "ranking_timeout")
    items = {}
    for item in state["buffer"]:
        for value in item.get("_listing_evidence", {}).get("api_record", {}).get("payload", {}).get("data", {}).get("job_post_list", []):
            items[str(value["id"])] = value
        items[str(item["id"])] = item
    ids = [row["url"].split("/position/")[1].split("/")[0] for row in captured]
    assert all(key in items for key in ids), "Cannot reconstruct the exact recorded pool"
    local = {**state, "buffer": [items[key] for key in ids], "ranking_query": None}

    class UnavailableModel:
        primary = True

        async def rank_listing(self, texts, **kwargs):
            return list(range(len(texts)))  # Same fallback contract as an unavailable model.

    known = {identity(j["url"]) for j in before["baseline_jobs"] if j["url"]}
    source = enabled_company_sources(["nio"])[0]
    direct = DirectRecruitmentSearch(sources=[source], query=before["query"], reader=None, browser=None,
        on_event=lambda *_: None, understanding=UnavailableModel(), known_urls=known)
    await direct._rank_buffer(source, local)
    after = [{"url": direct._item_url(item, local), "title": item["title"],
              "known": direct._item_url(item, local) in known} for item in local["buffer"]]
    assert {row["url"] for row in after} == {row["url"] for row in captured}
    return {"scope": "identical_15_captured_candidates_no_network_no_model",
            "candidate_count": len(after), "before_top3": captured[:3], "after_top3": after[:3],
            "before_new_top3": sum(not r["known"] for r in captured[:3]),
            "after_new_top3": sum(not r["known"] for r in after[:3])}


def main(folder):
    labels = read(folder / "labels.json")
    rows = []
    before = read(folder / "before/report.json")
    known = {identity(j["url"]) for j in before["baseline_jobs"]}
    for entry in read(folder / "manifest.json"):
        raw = (folder / "reference" / (entry["id"] + ".json")).read_bytes()
        rows.append({**entry, **labels["labels"][entry["id"]],
                     "new_to_baseline": identity(entry["url"]) not in known,
                     "source_sha256": hashlib.sha256(raw).hexdigest()})
    runs = {name: read(folder / name / "report.json") for name in
            ("before", "after", "continue-nio", "continue-sensetime") if (folder / name / "report.json").exists()}
    comparisons = {name: compare(rows, run) for name, run in runs.items()}
    report = {"scope": labels["scope"], "limitations": labels["notes"],
              "label_counts": dict(Counter(r["label"] for r in rows)), "references": rows,
              "runs": comparisons, "controlled_replay": asyncio.run(replay(before))}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = html.escape
    metric_rows = ""
    for name, result in comparisons.items():
        m = result["metrics"]
        first = m.get("first_new_recommended_ms")
        metric_rows += f'<tr><th>{esc(name)}</th><td>{result["elapsed_seconds"]} 秒</td><td>{m["new_recommended_jobs"]}</td><td>{str(round(first / 1000, 1)) + " 秒" if first is not None else "尚无"}</td><td>{result["reference_found"]}/7</td><td>{result["reference_recommended"]}/7</td><td>{m["source_read_successes"]}/{m["source_read_attempts"]}</td></tr>'
    reference_rows = ""
    for row in rows:
        stages = "".join(f'<td>{esc(next(x for x in result["rows"] if x["id"] == row["id"])["stage"])}</td>' for result in comparisons.values())
        reference_rows += f'<tr><td><a href="{esc(row["url"])}">{esc(row["id"])}</a><small>{"新链接" if row["new_to_baseline"] else "原库已有"}</small></td><td>{esc(row["label"])}<small>{esc(row["reason"])}</small></td>{stages}<td><a href="reference/{esc(row["id"])}.json">正文证据</a></td></tr>'
    new_jobs = []
    run = runs["after"]
    old_ids = {j["id"] for j in run["baseline_jobs"]}
    recommendations = {m["job_posting_id"] for m in run["matches"] if m["review_status"] == "recommended"}
    for job in run["jobs"]:
        if job["id"] not in old_ids and job["id"] in recommendations:
            new_jobs.append(f'<li><a href="{esc(job["source_url"])}">{esc(job["title"])}</a><details><summary>查看本轮原文</summary><pre>{esc(job["raw_content"])}</pre></details></li>')
    replayed = report["controlled_replay"]
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>岗位找回率验收 · 2026-10-19</title>
<style>body{{font:15px/1.7 system-ui,sans-serif;background:#f6f8fc;color:#18304c;margin:0;padding:40px}}main{{max-width:1450px;margin:auto}}h1{{font-size:30px}}section{{background:white;border:1px solid #d8e0ed;border-radius:14px;padding:24px;margin:22px 0}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:11px;border-bottom:1px solid #e2e8f0;vertical-align:top}}small{{display:block;color:#52667d}}a{{color:#245cc4}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}.warn{{background:#fff5df}}strong{{color:#174c93}}</style>
<main><h1>岗位找回率验收</h1><p>2026-10-19 · 六家公司 · 21 条固定对照 · 每家公司首轮最多核验三条详情</p>
<section><h2>结论</h2><p>相同原始数据库、相同目标和公司集合，新增推荐岗位由 <strong>0 → 3</strong>，首个新推荐岗位 <strong>43.6 秒</strong>出现。改动在检索与候选选择阶段，未修改最终 AI 判断标准。</p><p>原先补搜被旧官网域名限制；排序超时时，标题写法和旧岗位占位又让新岗位难以进入前三条。已支持按已观察招聘入口补搜、无有效列表时按公司探索官方职位，以及正文/卡片信息与新旧状态共同参与兜底排序。</p></section>
<section><h2>实测与限制</h2><p>{esc(labels["scope"])}</p><p>{esc(labels["notes"])}</p><div class="scroll"><table><thead><tr><th>运行</th><th>总耗时</th><th>新增推荐</th><th>首个新推荐</th><th>对照找回（含待续查）</th><th>对照已推荐</th><th>官网列表读取</th></tr></thead><tbody>{metric_rows}</tbody></table></div><p>对照分母仅 7 条已确认相关岗位，不代表全网或六家公司所有岗位。续查各自从 after 的副本开始，新增数量不能直接相加；续查只查选定公司，表中 7 条固定分母用于查看各岗位去向。新推荐包括不在固定对照中的岗位，未把它们事后加入分母。</p><p>实时网页、搜索引擎和模型存在波动；本次总耗时没有下降，列表读取成功率也未改善，不能据此宣称整体提速或全量覆盖。</p></section>
<section><h2>相同候选池回放</h2><p>对修改前保存的 {replayed["candidate_count"]} 条蔚来候选，关闭网络和模型，用同一正文验证兜底排序：前三条中的新岗位由 {replayed["before_new_top3"]} → {replayed["after_new_top3"]}。候选集合完全相同，没有删除未选项。这仅验证新岗位优先机制，不证明候选已经符合全部条件。</p></section>
<section><h2>前三条的质量与续查</h2><p>逐条复核蔚来实际送去核验的前三条：修改前后都为 3/3 方向、城市及校招届别符合，但修改前全是旧岗位，修改后全是新岗位。MiniMax 的前三条仍混有产品市场营销、可观测平台和预训练等边界岗位；不能宣称整体前三条质量已解决。</p><p>蔚来续查又产出 3 条新推荐，并完成 3 条旧岗位复核；两条使用已保存的列表正文，一条重新读取。商汤续查利用保存正文完成 3 条旧岗位复核，官网列表本身仍未恢复成功。续查新增三条为信息娱乐 Agent 开发、Agent 安全防护开发、AI 智能平台研发，已按原文复核，未加入冻结对照集。</p></section>
<section><h2>本轮新推荐</h2><ul>{"".join(new_jobs)}</ul><p>三条已逐条核对本轮原文：包含北京或上海、2027届正式校招、本人承担 Agent/RAG 系统开发。学历及全部任职条件仍需投递前核对。</p></section>
<section class="warn"><h2>仍然存在的问题</h2><p>商汤入口加载不稳定，补搜虽可找回实际岗位，部分新域名链接仍缺少官方归属确认；旧岗位的 AI 复核预算可能先被无关历史岗位消耗；没有进入当前关键词第一页的岗位仍需续查。下一步应优先改善历史复核排序、复用有证据的招聘入口，再验收分页覆盖。</p></section>
<section><h2>逐条去向</h2><p>下表为各次运行自身的输出；“本轮未找回”不表示上轮已经入库或推荐的岗位被删除。</p><div class="scroll"><table><thead><tr><th>对照岗位</th><th>原文审计</th>{"".join(f"<th>{esc(name)}</th>" for name in comparisons)}<th>证据</th></tr></thead><tbody>{reference_rows}</tbody></table></div></section>
<p>可复核文件：<a href="report.json">汇总 JSON</a> · <a href="before/report.json">修改前运行</a> · <a href="after/report.json">修改后运行</a> · <a href="labels.json">运行前冻结判断</a>。个人数据库未修改。</p></main></html>'''
    (folder / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({"report": str(folder / "report.html"), "labels": report["label_counts"],
                      "runs": {k: {x: v[x] for x in ("reference_found", "reference_recommended")} for k, v in comparisons.items()},
                      "replay": replayed}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    main(parser.parse_args().folder)

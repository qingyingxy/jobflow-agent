"""Summarize immutable live matching-chain trials without dropping failures."""
from __future__ import annotations

import html
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/matching-chain-live-20261020"
LABELS = ["recommended_application", "consider", "not_recommended", "insufficient_information"]
NAMES = dict(zip(LABELS, ["推荐投递", "值得考虑", "不推荐", "信息不足"]))
NAMES["execution_error"] = "执行失败"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summary_times(values):
    values = sorted(values)
    return {"n": len(values), "p50_seconds": round(median(values), 3),
            "p95_seconds": values[math.ceil(len(values) * .95) - 1], "max_seconds": values[-1]} if values else {"n": 0}


def metrics(pairs, *, require_completed=False):
    matrix = {gold: {pred: 0 for pred in LABELS + ["execution_error"]} for gold in LABELS}
    qualified, completed = 0, 0
    for case, row in pairs:
        pred = row.get("decision", {}).get("recommendation", "execution_error")
        if require_completed and row.get("status") != "completed":
            pred = "execution_error"
        matrix[case["expected_decision"]][pred] += 1
        qualified += row.get("eligibility", {}).get("eligible") == case["expected_eligibility"]
        completed += row.get("status") == "completed"
    classes = {}
    for label in LABELS:
        tp = matrix[label][label]
        fp = sum(matrix[g][label] for g in LABELS if g != label)
        fn = sum(matrix[label].values()) - tp
        classes[label] = {"tp": tp, "fp": fp, "fn": fn,
                          "precision": tp / (tp + fp) if tp + fp else 0,
                          "recall": tp / (tp + fn) if tp + fn else 0,
                          "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0}
    rec = "recommended_application"
    excluded = "not_recommended"
    return {"pairs": len(pairs), "completed": completed,
            "agreement": sum(matrix[x][x] for x in LABELS),
            "agreement_rate": sum(matrix[x][x] for x in LABELS) / len(pairs),
            "macro_f1": sum(c["f1"] for c in classes.values()) / 4,
            "qualification_agreement": qualified,
            "matrix": matrix, "classes": classes,
            "over_recommendation": {"numerator": classes[rec]["fp"], "denominator": classes[rec]["tp"] + classes[rec]["fp"]},
            "false_exclusion": {"numerator": classes[excluded]["fp"], "denominator": sum(sum(matrix[x].values()) for x in LABELS if x != excluded)}}


def main():
    manifest = read(OUT / "manifest.json")
    jobs = {j["id"]: j for j in manifest["jobs"]}
    pairs, first, retries, details = [], [], [], []
    for case in manifest["cases"]:
        prefix = OUT / case["job_id"]
        p1 = prefix / f"{case['profile_key']}-attempt1.json"
        p2 = prefix / f"{case['profile_key']}-attempt2.json"
        r1 = read(p1) if p1.exists() else {"status": "not_finished"}
        final = read(p2) if p2.exists() else r1
        first.append((case, r1))
        pairs.append((case, final))
        if p2.exists():
            retries.append({"case_id": case["id"], "before": r1["status"], "after": final["status"]})
        details.append({"case_id": case["id"], "expected": case["expected_decision"],
                        "initial": r1.get("decision", {}).get("recommendation", "execution_error"),
                        "final": final.get("decision", {}).get("recommendation", "execution_error"),
                        "initial_status": r1["status"], "final_status": final["status"]})
    grounding = {"ordinary_quotes": 0, "grounded_quotes": 0, "invalid": [], "supported_ordinary_rows": 0, "supported_with_quotes": 0}
    for case, row in pairs:
        owned = {r["id"]: r for r in manifest["profiles"][case["profile_key"]]["evidence"]}
        for index, match in enumerate(row.get("matches", [])):
            req = match["requirement"]
            if req.get("education") or req["category"] in {"education", "major"}:
                continue
            quotes = []
            for item in match.get("item_checks", []):
                for q in item.get("evidence_quotes", []):
                    quotes.append(q)
                    grounding["ordinary_quotes"] += 1
                    cited = [owned[rid]["claim"] for rid in item["evidence_ids"] if rid in owned]
                    valid = any(" ".join(q.split()) in " ".join(claim.split()) for claim in cited)
                    grounding["grounded_quotes"] += valid
                    if not valid:
                        grounding["invalid"].append({"case_id": case["id"], "index": index, "quote": q})
            if match["support_level"] == "supported":
                grounding["supported_ordinary_rows"] += 1
                grounding["supported_with_quotes"] += bool(quotes)
    cache = [r["cache_check"] for _, r in first if r.get("cache_check")]
    # Exploratory diagnostic, separate from the predeclared reference metric.
    # A/B/C send the same requirement and experience text to the matcher;
    # opaque user/evidence IDs differ, and education is evaluated locally.
    consistency = {"status": "exploratory_post_run_diagnostic", "units": 0,
                   "same_level": 0, "cross_supported_boundary": 0, "differences": []}
    by_job = {}
    for case, row in pairs:
        by_job.setdefault(case["job_id"], {})[case["profile_key"]] = row
    for job_id, rows in by_job.items():
        if any(rows.get(key, {}).get("status") != "completed" for key in "ABC"):
            continue
        mapped = {key: {m["requirement"]["description"]: m for m in rows[key]["matches"]
                        if not m["requirement"].get("education") and m["requirement"]["category"] not in {"education", "major"}}
                  for key in "ABC"}
        for description in mapped["A"]:
            if not all(description in mapped[key] for key in "ABC"):
                continue
            levels = [mapped[key][description]["support_level"] for key in "ABC"]
            consistency["units"] += 1
            consistency["same_level"] += len(set(levels)) == 1
            consistency["cross_supported_boundary"] += "supported" in levels and len(set(levels)) > 1
            if len(set(levels)) > 1:
                consistency["differences"].append({"job_id": job_id, "description": description, "levels_ABC": levels})
    calls = []
    for p in OUT.glob("campus-ai-*/calls.jsonl"):
        calls.extend(json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    end = read(OUT / "run-end.json") if (OUT / "run-end.json").exists() else {"in_progress": True}
    audit = read(OUT / "semantic-audit.json") if (OUT / "semantic-audit.json").exists() else {"status": "pending"}
    result = {
        "label_status": manifest["label_status"], "initial": metrics(first), "after_recovery": metrics(pairs),
        "strict_initial": metrics(first, require_completed=True),
        "strict_after_recovery": metrics(pairs, require_completed=True),
        "metric_definitions": {
            "initial_and_after_recovery": "Agreement of visible decisions; an incomplete capability analysis may still have the correct qualification-driven visible decision. Completion is reported separately.",
            "strict_initial_and_strict_after_recovery": "Incomplete or failed execution counts as execution_error, even if visible decision agrees. Same frozen labels; conservative full-chain score.",
            "calls_total": "Structured client generate() invocations; not an independently observed count of underlying HTTP attempts.",
        },
        "by_profile": {key: metrics([(c, r) for c, r in pairs if c["profile_key"] == key]) for key in manifest["profiles"]},
        "recovery": retries, "recovered": sum(r["after"] == "completed" for r in retries),
        "latency": {
            "cold_initial_including_incomplete": summary_times([r["elapsed_seconds"] for _, r in first if r.get("cold_parse")]),
            "warm_initial_including_incomplete": summary_times([r["elapsed_seconds"] for _, r in first if r.get("cold_parse") is False]),
            "cache": summary_times([r["elapsed_seconds"] for r in cache]),
        },
        "cache": {"tested": len(cache), "passed": sum(r["same_analysis"] and r["same_decision"] and r["extra_calls"] == 0 for r in cache)},
        "citation_grounding": grounding,
        "semantic_consistency": consistency,
        "calls": {"total": len(calls), "by_schema": dict(Counter(c["schema"] for c in calls)),
                  "errors": dict(Counter(c["error_type"] for c in calls if "error_type" in c)),
                  "usage": {key: sum((c.get("response", {}).get("usage") or {}).get(key, 0) or 0 for c in calls) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}},
        "run": end, "semantic_audit": audit, "cases": details,
    }
    (OUT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    e = lambda x: html.escape(str(x))
    finalm = result["after_recovery"]
    initialm = result["initial"]
    strictm = result["strict_after_recovery"]
    strict_initial = result["strict_initial"]
    intro = f"""<h1>完整匹配链路 · 真实模型验收</h1><p class="sub">2026-10-20 · gpt-5.6-terra · 当前生产解析与匹配入口</p>
    <p>保存的官网 JD 原文 → 两阶段 JD 解析 → 本地资格核对 → AI 经历匹配 → 最终建议。<strong>12 条岗位快照 × 4 类虚构候选人，48 组。</strong></p>
    <p class="notice">参考结论由本助手在调用前预先声明，不是独立人工金标。样本来自已使用的开发集，候选人全部虚构；本次不测联网搜索、网页读取、简历导入或实际录用概率。</p>
    <div class="cards"><div><b>{finalm['completed']}/48</b><span>重试后完整完成</span></div><div><b>{strictm['agreement']}/48</b><span>完整完成且符合参考</span></div><div><b>{strictm['macro_f1']:.3f}</b><span>严格全链路 Macro-F1</span></div><div><b>{finalm['qualification_agreement']}/48</b><span>资格结论一致</span></div></div>
    <h2>首次与恢复分开看</h2><table><tr><th>阶段</th><th>完整完成</th><th>显示的建议一致</th><th>完整且一致</th><th>严格 Macro-F1</th></tr>
    <tr><td>首次运行（含产品内部重试）</td><td>{initialm['completed']}/48</td><td>{initialm['agreement']}/48</td><td>{strict_initial['agreement']}/48</td><td>{strict_initial['macro_f1']:.3f}</td></tr>
    <tr><td>对未完成项额外续跑一次</td><td>{finalm['completed']}/48</td><td>{finalm['agreement']}/48</td><td>{strictm['agreement']}/48</td><td>{strictm['macro_f1']:.3f}</td></tr></table>
    <p>显示的最终建议一致 {finalm['agreement']}/48，但其中 {finalm['agreement']-strictm['agreement']} 组仍有能力分析未完成。严格口径把未完成项算作执行失败；只按显示建议计算的四分类 Macro-F1 为 {finalm['macro_f1']:.3f}。两种口径使用同一份冻结标签，均不是独立人工准确率。</p>
    <p>额外续跑 {len(retries)} 组，恢复 {result['recovered']} 组。过度推荐 {finalm['over_recommendation']['numerator']}/{finalm['over_recommendation']['denominator']}（分母为系统推荐数）；误排除 {finalm['false_exclusion']['numerator']}/{finalm['false_exclusion']['denominator']}（分母为参考未排除数）。</p>"""
    profiles = "<h2>四类资料</h2><table><tr><th>资料</th><th>固定输入</th><th>建议一致</th><th>资格一致</th></tr>" + "".join(
        f"<tr><td>{key}</td><td>{e(p['name'])}</td><td>{result['by_profile'][key]['agreement']}/12</td><td>{result['by_profile'][key]['qualification_agreement']}/12</td></tr>"
        for key, p in manifest["profiles"].items()) + "</table>"
    confusion = "<h2>最终建议对照</h2><p>行是预声明参考，列是系统输出。执行失败保留在分母。</p><table><tr><th>参考 ↓ / 输出 →</th>" + "".join(f"<th>{NAMES[l]}</th>" for l in LABELS + ["execution_error"]) + "</tr>"
    confusion += "".join("<tr><th>" + NAMES[g] + "</th>" + "".join(f"<td>{finalm['matrix'][g][p]}</td>" for p in LABELS + ["execution_error"]) + "</tr>" for g in LABELS) + "</table>"
    audit_html = "<h2>证据与语义复核</h2>" + f"<p>已发布普通能力引用 {grounding['grounded_quotes']}/{grounding['ordinary_quotes']} 能在对应候选人引用的经历中找到；这只证明引用来源，不证明推理正确。</p>"
    audit_html += f"<p>补充稳定性检查：A/B/C 使用相同 JD 和经历文本（候选人及引用 ID 不同；学历不发送到经历匹配模型），{consistency['same_level']}/{consistency['units']} 个普通条件三次支持等级一致；{consistency['cross_supported_boundary']} 个条件跨越了“完全支持 / 未完全支持”的边界。这是探索性诊断，不是独立重复采样准确率。</p>"
    for finding in audit.get("findings", []):
        audit_html += f"<article><h3>{e(finding['title'])}</h3><p>{e(finding['detail'])}</p><p class='sub'>{e(', '.join(finding.get('case_ids', [])))}</p></article>"
    rows = "<h2>逐组结果与原始证据</h2><p>展开查看资格检查、匹配解释和引用；所有首次失败均保留。</p>"
    for case, row in pairs:
        job = jobs[case["job_id"]]
        pred = row.get("decision", {}).get("recommendation", "execution_error")
        css = "good" if pred == case["expected_decision"] else "bad"
        rows += f"<details><summary><span class='{css}'>{'一致' if css == 'good' else '分歧'}</span> {e(case['id'])} · {e(job['source']['company'])} · {e(job['source']['title'])} — {NAMES[pred]}</summary>"
        rows += f"<p>参考：{NAMES[case['expected_decision']]}。{e(case['reason'])}</p><p>状态：{e(row['status'])}；本次用时 {e(row.get('elapsed_seconds', '—'))} 秒。</p>"
        rows += "<ul>" + "".join(f"<li>{e(c['result'])}：{e(c['reason'])}</li>" for c in row.get("eligibility", {}).get("checks", [])) + "</ul>"
        for match in row.get("matches", []):
            r = match["requirement"]
            rows += f"<div class='match'><b>{'必须' if r['mandatory'] else '优先'} · {e(match['support_level'])}</b><p>{e(r['description'])}</p><p>{e(match['explanation'])}</p>"
            for item in match.get("item_checks", []):
                rows += "".join(f"<blockquote>{e(q)}</blockquote>" for q in item.get("evidence_quotes", []))
            rows += "</div>"
        rows += f"<details><summary>岗位原文（存档，未确认当前在招）</summary><p><a href='{e(job['source']['source_url'])}'>官方来源</a></p><pre>{e(job['raw_content'])}</pre></details></details>"
    timing = "<h2>耗时、缓存与调用记录</h2><pre>" + e(json.dumps({k: result[k] for k in ("latency", "cache", "calls", "run")}, ensure_ascii=False, indent=2)) + "</pre><p>冷解析耗时包含首次 JD 解析与匹配；暖解析复用同一岗位解析，只重新做候选人匹配。缓存复查不计为新的质量样本。</p>"
    footer = "<h2>可复核材料</h2><p><a href='manifest.json'>冻结的输入与参考结论</a> · <a href='metrics.json'>完整指标</a> · <a href='semantic-audit.json'>语义审计记录</a></p><p>此结果支持描述已搭建并测试完整分析链路；不能称为独立人工验证的投递准确率，也不能替代线上岗位召回率或求职成功率。</p>"
    css = "body{font:16px/1.7 system-ui,'Microsoft YaHei',sans-serif;color:#162335;background:#f3f6fa;margin:0}main{max-width:1120px;margin:40px auto;padding:36px;background:white;border-radius:18px}h1{font-size:30px}h2{margin-top:36px;font-size:23px}.sub{color:#63758a;font-size:14px}.notice{padding:18px;background:#fff5dc;border-radius:10px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}.cards div{padding:20px;background:#eef5ff;border-radius:12px}.cards b{display:block;font-size:29px}.cards span{color:#425c78;font-size:14px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #dce4ed;padding:12px;text-align:left}th{background:#f2f6fb}details,article{border:1px solid #dee6ee;border-radius:10px;padding:14px;margin:12px 0}summary{cursor:pointer;font-weight:600}.good{color:#087b58}.bad{color:#b34c20}.match{border-left:3px solid #b7cce6;padding:6px 16px;margin:12px 0}.match p{margin:6px 0}blockquote{color:#4b6079;font-size:14px;margin:8px;padding:8px;background:#f3f6fa}pre{white-space:pre-wrap;word-break:break-word;font-size:13px;padding:16px;background:#f5f7fa}a{color:#175da2}@media(max-width:700px){main{margin:0;padding:18px}.cards{grid-template-columns:repeat(2,1fr)}}"
    (OUT / "report.html").write_text(f"<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>JobFlow 完整匹配链路验收</title><style>{css}</style><main>{intro}{profiles}{confusion}{audit_html}{timing}{rows}{footer}</main></html>", encoding="utf-8")
    print(json.dumps({"initial": {k: initialm[k] for k in ('completed', 'agreement', 'macro_f1', 'qualification_agreement')},
                      "final": {k: finalm[k] for k in ('completed', 'agreement', 'macro_f1', 'qualification_agreement')},
                      "retries": len(retries), "recovered": result['recovered'], "calls": result['calls'], "run": end}, ensure_ascii=False))


if __name__ == "__main__":
    main()

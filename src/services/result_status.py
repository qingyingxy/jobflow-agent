"""Keep reading, search fit and personal eligibility as independent claims."""

from src.services.body_quality import assess_body
from src.services.personal_requirements import personal_requirement_hints
from src.services.source_understanding import review_attempt

FIELD_LABELS = {"location": "地点", "role": "职责方向", "job_type": "招聘类型",
                "graduation_year": "届别", "keyword": "关键词", "additional": "附加条件"}


def enrich_result(match, job, profile, *, conditions):
    from src.services.search_goal_service import posting_stub

    match = dict(match)
    quality = assess_body(job.raw_content, title=job.title)
    readable = quality["status"] == "readable"
    checks = match.get("checks", [])
    unresolved = [c for c in checks if c.get("diagnosis") == "not_extracted" or c.get("review_required")]
    attempt = review_attempt(posting_stub(job), conditions)
    if not readable:
        analysis = {"state": "reading_required", "label": "读取未完成", "reason": quality["reason"]}
        # Old conclusions based on a page shell cannot remain recommendations
        # or exclusions. A separately observed closure is still valid.
        if job.availability_status != "CLOSED":
            match.update(filter_status="pending", review_status="pending", match_tier="expanded",
                         mismatch_labels=[quality["reason"]], mismatch_reasons=["body_incomplete"], checks=[])
            checks = []
    elif unresolved:
        failures = attempt.get("failures", 0)
        state, label, reason = (
            ("blocked", "分析多次失败", "已保留正文，可通过继续处理重试") if failures >= 3 else
            ("retrying", "分析待重试", "已保留正文，后台将继续分析") if failures else
            ("waiting", "等待分析", "正文已保存，尚未完成当前目标的判断"))
        analysis = {"state": state, "label": label, "reason": reason}
    else:
        analysis = {"state": "completed", "label": "搜索条件已分析", "reason": "搜索判断与个人资格分别核对"}

    required = [c for c in checks if c.get("required", True) and c["field"] != "availability"]
    missing = [FIELD_LABELS.get(c["field"], c["field"]) for c in required if c.get("diagnosis") == "source_missing"]
    if not readable or unresolved:
        search = {"state": "pending", "label": "搜索条件待判断"}
    elif any(c["status"] == "excluded" for c in required):
        search = {"state": "conflict", "label": "搜索条件有明确冲突"}
    elif required and all(c["status"] == "matched" for c in required):
        search = {"state": "matched", "label": "搜索条件符合"}
    elif missing:
        search = {"state": "source_missing", "label": "原文未说明：" + "、".join(missing)}
    else:
        search = {"state": "uncertain", "label": "搜索条件仍需核对"}
    search["missing_fields"] = missing if readable else []
    hints = personal_requirement_hints(job, profile) if readable else []
    conflict = any(h["status"] == "attention" for h in hints)
    satisfied = [h for h in hints if h["status"] == "satisfied"]
    if conflict:
        personal = {"state": "conflict", "label": "个人门槛存在冲突"}
    elif not readable:
        personal = {"state": "unreviewed", "label": "个人门槛待核对"}
    elif profile is None:
        personal = {"state": "profile_missing", "label": "个人资料待补充"}
    elif satisfied:
        personal = {"state": "partially_checked", "label": "已核对部分门槛，其余待核对"}
    else:
        personal = {"state": "unreviewed", "label": "个人门槛待核对"}
    personal["reason"] = "搜索条件符合不代表全部任职资格符合；未提取到门槛也不代表已通过"
    match.update(personal_requirements=hints, personal_gate_conflict=conflict,
                 result_status={"reading": quality, "analysis": analysis, "search": search, "personal": personal})
    if conflict and match.get("review_status") == "recommended":
        match["review_status"] = "pending"
        match["review_caveats"] = [*match.get("review_caveats", []), "个人门槛存在冲突"]
    return match

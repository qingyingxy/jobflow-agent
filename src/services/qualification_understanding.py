"""Source-bound qualification clauses; profile comparison stays local."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.services.job_fact_understanding import WorkLocation, attach_locations

VERSION = "qualification-clauses-v2-conflicts"
INSTRUCTION = (
    "同时抽取当前岗位对申请人的任职条件qualifications，不能判断具体候选人是否合格。"
    "逐条区分required必备、preferred优先、conditional有替代或分支、uncertain范围不清。"
    "evidence必须逐字引用原文完整条件，包括否定、可选、放宽与限定；不引用团队介绍。"
    "每项只表达一个要求，段落后面的优先条件不能改变前面的必备学历。"
    "学历与专业分别理解：计算机、数学或相关专业的博士学位，学历仍为博士；"
    "硕士或博士学历则accepted_degrees列出两者，本科及以上列出bachelor/master/doctor。"
    "不要求博士、优秀硕士可放宽、多方向任选等必须保留条件，不能标成无条件博士必备。"
    "scope写适用的方向或例外条件；全岗位通用填null。非学历项accepted_degrees为空。"
    "只抽取原文写明的学历、专业、经验、院校、论文等资格；没有就返回空数组。"
    "必须同时检查岗位标题、招聘项目和正文要求，不能只抽取任职要求小节。"
    "若同一资格有互相矛盾的表述，在该条conflicting_evidence中逐字引用其他冲突原文，"
    "strength填uncertain，scope说明冲突，不能只选择更宽松的一段。"
    "例如项目写2027届博士生招聘，正文写硕士或博士学位，且没有明确放宽说明，"
    "应保留这两处证据并标为待核对；不能把项目学历限制只当作毕业年份。"
    "明确的多方向条件或放宽例外不等于矛盾，使用conditional和scope保留适用范围。"
    "没有冲突时conflicting_evidence为空数组。"
)


class QualificationClause(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: Literal["degree", "major", "experience", "institution", "publication", "other"]
    strength: Literal["required", "preferred", "conditional", "uncertain"]
    evidence: str = Field(min_length=2, max_length=3000)
    accepted_degrees: list[Literal["associate", "bachelor", "master", "doctor"]] = Field(max_length=4)
    scope: str | None = Field(max_length=500)
    conflicting_evidence: list[str] = Field(default_factory=list, max_length=5)


class QualificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    qualifications: list[QualificationClause] = Field(max_length=20)
    work_locations: list[WorkLocation] | None = Field(default=None, max_length=20)


def body_key(job):
    return hashlib.sha256((VERSION + "\n" + (job.raw_content or "")).encode()).hexdigest()


def validated_clauses(job, values):
    if values is None:
        return None
    try:
        clauses = QualificationOutput.model_validate({"qualifications": values}).model_dump()["qualifications"]
    except ValidationError:
        return None
    if any(c["evidence"] not in (job.raw_content or "") for c in clauses):
        return None
    return clauses


def cached_qualifications(job):
    record = (job.recruitment_context or {}).get("qualification_understanding", {})
    if record.get("fingerprint") != body_key(job) or record.get("version") != VERSION:
        return None
    return validated_clauses(job, record.get("clauses"))


def attach_qualifications(job, values):
    clauses = validated_clauses(job, values)
    if clauses is None:
        return job
    return replace(job, recruitment_context={**(job.recruitment_context or {}),
        "qualification_understanding": {"version": VERSION, "fingerprint": body_key(job), "clauses": clauses},
        "qualification_review_attempt": {"fingerprint": body_key(job), "failures": 0, "error_code": None}})


def qualification_attempt(job):
    attempt = (job.recruitment_context or {}).get("qualification_review_attempt", {})
    return attempt if attempt.get("fingerprint") == body_key(job) else {"fingerprint": body_key(job), "failures": 0}


async def review_qualifications(runtime, job, *, on_checkpoint=None):
    from src.services.semantic_retry import failed_attempt, retry_at

    if cached_qualifications(job) is not None:
        return job
    previous = qualification_attempt(job)
    now = datetime.now(UTC)
    attempt = {**previous, "queued_at": previous.get("queued_at") or now.isoformat(),
        "attempted_at": now.isoformat(), "error_code": "semantic_pending", "next_retry_at": None}
    pending = replace(job, recruitment_context={**(job.recruitment_context or {}), "qualification_review_attempt": attempt})
    if on_checkpoint:
        on_checkpoint(pending)
    payload = {"url": job.detail_url, "qualification_version": VERSION, "body": job.raw_content}
    import asyncio
    import json

    from src.services.source_understanding import VERSION as source_version
    try:
        result = await runtime.generate(QualificationOutput, payload, INSTRUCTION,
            kind="job_qualifications", timeout=runtime.settings.web_search_semantic_retry_timeout_seconds)
    except asyncio.CancelledError:
        attempt["error_code"] = "semantic_cancelled"
        if on_checkpoint:
            on_checkpoint(pending)
        raise
    updated = attach_qualifications(pending, result["qualifications"] if result else None)
    if result:
        updated = attach_locations(updated, result.get("work_locations"))
    if cached_qualifications(updated) is None:
        cache_key = json.dumps([source_version, "job_qualifications", payload], ensure_ascii=False, sort_keys=True)
        error = runtime._errors.get(cache_key, "semantic_invalid")
        failures = previous.get("failures", 0) + int(failed_attempt(error))
        updated = replace(pending, recruitment_context={**pending.recruitment_context,
            "qualification_review_attempt": {**attempt, "error_code": error, "failures": failures,
                                             "next_retry_at": retry_at(error, failures, now)}})
    if on_checkpoint:
        on_checkpoint(updated)
    return updated

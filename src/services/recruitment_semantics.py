"""Portable recruitment evidence from semantic fields and Schema.org JobPosting."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from itertools import pairwise
from urllib.parse import urljoin

from src.services.job_url import canonical_job_url

_LABELS = {
    "岗位状态": "岗位状态",
    "职位状态": "岗位状态",
    "招聘状态": "招聘状态",
    "网申状态": "网申状态",
    "批次状态": "批次状态",
    "job status": "岗位状态",
    "position status": "岗位状态",
    "application status": "网申状态",
    "网申时间": "网申时间",
    "投递时间": "投递时间",
    "报名时间": "报名时间",
    "招聘批次": "招聘批次",
    "招聘项目": "招聘项目",
    "招聘公告": "招聘公告",
    "批次公告": "批次公告",
    "recruitment program": "招聘项目",
    "招聘对象": "招聘对象",
    "毕业时间要求": "毕业时间要求",
    "毕业时间": "毕业时间要求",
    "届别要求": "届别要求",
    "适用届别": "届别要求",
}
BATCH_FIELDS = frozenset({"招聘批次", "招聘项目", "招聘公告", "批次公告"})


@dataclass(frozen=True)
class RecruitmentField:
    label: str
    value: str
    value_node: object

    @property
    def source_text(self):
        return f"{self.label}：{self.value}"


def labelled_fields(scope):
    """Associate adjacent cells/terms and two-child fields, never page keywords."""
    fields = []
    for parent in scope.walk():
        children = [n for n in parent.children if hasattr(n, "tag") and not n.excluded]
        pairs = []
        if parent.tag == "dl":
            pairs = [
                (a, b) for a, b in pairwise(children) if a.tag == "dt" and b.tag == "dd"
            ]
        elif len(children) == 2 and (
            parent.tag == "tr"
            or not any(
                isinstance(child, str) and child.strip() for child in parent.children
            )
        ):
            pairs = [children]
        for label_node, value_node in pairs:
            label = _LABELS.get(label_node.text().strip().rstrip(":：").casefold())
            value = value_node.text().strip()
            if label and value and len(value) <= 1500:
                fields.append(RecruitmentField(label, value, value_node))
    return fields


def deadline_availability(value, *, now=None):
    """A past explicit deadline closes a job; a future date does not prove open."""
    base = {
        "value": "UNKNOWN",
        "valid_through": value,
        "reason": "截止日期尚未到达，但仍缺少明确在招证据",
    }
    if not isinstance(value, str):
        return {**base, "reason": "岗位截止日期格式无法确认"}
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            deadline = datetime.combine(
                datetime.fromisoformat(value).date(),
                time.max,
                timezone(timedelta(hours=8)),
            )
        else:
            deadline = datetime.fromisoformat(value)
            if deadline.tzinfo is None:
                raise ValueError("deadline_timezone_unknown")
        if (now or datetime.now(UTC)) > deadline:
            return {
                **base,
                "value": "CLOSED",
                "source_text": f"validThrough={value}",
                "reason": None,
            }
    except ValueError:
        return {**base, "reason": "岗位截止日期格式或时区无法确认"}
    return base


def structured_context(*, raw_html, document, url, base, save_snapshot, now=None):
    from src.services.url_reader import parse_html_document

    jobs = []
    for item in parse_html_document(raw_html).json_ld:
        kinds = item.get("@type", [])
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if "JobPosting" not in kinds or not isinstance(item.get("url"), str):
            continue
        if canonical_job_url(urljoin(url, item["url"])).rstrip(
            "/"
        ) == canonical_job_url(url).rstrip("/"):
            jobs.append(item)
    if not jobs:
        return None
    if (
        len(jobs) != 1
        or not isinstance(jobs[0].get("title"), str)
        or re.sub(r"\s+", "", jobs[0]["title"]).casefold()
        != re.sub(r"\s+", "", document.title or "").casefold()
    ):
        raise ValueError("structured_job_identity_conflict")
    job = jobs[0]
    eligibility = []
    incomplete_eligibility = False
    for field in (
        "educationRequirements",
        "experienceRequirements",
        "qualifications",
        "eligibilityToWorkRequirement",
    ):
        values = job.get(field, [])
        values = values if isinstance(values, list) else [values]
        # Preserve the whole field or none; don't cherry-pick one branch from
        # an unsupported schema object or a mixed structured/text list.
        if all(isinstance(value, str) for value in values):
            eligibility.extend(values)
        elif values and values != [None]:
            incomplete_eligibility = True
    if incomplete_eligibility:
        eligibility = []
    if not eligibility and "validThrough" not in job:
        return None
    availability = (
        deadline_availability(job["validThrough"], now=now)
        if "validThrough" in job
        else {"value": "UNKNOWN", "reason": "结构化岗位信息没有明确在招证据"}
    )
    snapshot_id = save_snapshot(url, json.dumps(job, ensure_ascii=False))
    return {
        **base,
        "version": 2,
        "status": "verified",
        "association": "job_structured_data",
        "template": "schema_job_posting",
        "source_url": url,
        "snapshot_id": snapshot_id,
        "eligibility_text": "\n".join(eligibility),
        "availability": {**availability, "source_url": url},
    }

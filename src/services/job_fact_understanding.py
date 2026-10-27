"""Keep the agent's work-location facts with the exact body they describe."""
import hashlib
from dataclasses import replace

from pydantic import BaseModel, ConfigDict, Field

VERSION = "work-location-facts-v1"
INSTRUCTION = (
    "同时返回work_locations，即当前岗位实际工作城市及原文evidence，即使用户地点不限也要提取。"
    "检查完整岗位正文，包括职责和要求之后的工作城市、办公地点等字段。"
    "排除面试城市、公司地址、业务覆盖地、出差目的地和推荐岗位的地点。"
    "value保留原文地点名称，每个地点一项；evidence引用支持该地点的完整字段。"
    "由你核对字段归属及引用是否确实存在；未明确实际工作地点时返回空数组，不猜测。"
)


class WorkLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=1200)


def body_key(job):
    return hashlib.sha256((VERSION + "\n" + (job.raw_content or "")).encode()).hexdigest()


def cached_locations(job):
    record = (getattr(job, "recruitment_context", None) or {}).get("work_location_understanding", {})
    if record.get("version") != VERSION or record.get("fingerprint") != body_key(job):
        return None
    return [item["value"] for item in record["locations"]]


def attach_locations(job, values):
    if values is None:
        return job
    return replace(job, recruitment_context={**(job.recruitment_context or {}),
        "work_location_understanding": {"version": VERSION, "fingerprint": body_key(job),
                                        "locations": values}})

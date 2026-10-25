"""Serialize the campus agent's final judgment without reinterpreting its evidence."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CampusCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=2500, pattern=r"^https?://")
    quote: str = Field(max_length=1200)


class CampusReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["found", "empty", "unknown"]
    title: str = Field(max_length=300)
    kind: Literal["job", "listing", "project", "other"]
    recruitment_url: str = Field(max_length=2500, pattern=r"^(https?://|$)")
    job_titles: list[str] = Field(max_length=5)
    cohort_status: Literal["confirmed", "unspecified"]
    campus_quote: str = Field(max_length=500)
    year_quote: str = Field(max_length=500)
    reasoning: str = Field(max_length=1200)
    citations: list[CampusCitation] = Field(max_length=8)


def report_result(report, url, year, checked_at):
    """Map the model's judgment to the existing card and persistence contracts."""
    citations = [citation.model_dump() for citation in report.citations]
    check = {"status": report.status, "checked_at": checked_at, "url": url,
        "kind": report.kind, "recruitment_url": report.recruitment_url,
        "job_titles": report.job_titles, "cohort_status": report.cohort_status,
        "reasoning": report.reasoning, "citations": citations}
    # Keep company job presence separate from application availability. This
    # report does not claim that a particular application can be submitted.
    scope = "\n\n".join(citation.quote for citation in report.citations)
    facts = {"title": report.title, "year": year, "batch": "campus",
        "scope_quote": scope, "year_quote": report.year_quote,
        "batch_quote": report.campus_quote, "status": "unknown", "status_quote": "",
        "published": None, "starts": None, "deadline": None, "directions": [],
        "cohort_status": report.cohort_status, "agent_report": report.model_dump(),
        "entry": {"url": url, "title": report.title, "kind": report.kind,
            "status": "unknown", "checked_at": checked_at, "quote": "",
            "scope_quote": scope, "campus_quote": report.campus_quote,
            "year_quote": report.year_quote, "origin_url": report.recruitment_url or url,
            "link_text": "", "apply_label": "", "job_titles": report.job_titles,
            "job_presence": report.status}}
    return check, facts

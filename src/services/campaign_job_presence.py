"""Company-level campus job observations, independent of application readiness."""
from datetime import UTC, datetime

from src.services.campaign_navigation import job_filter_url


def job_observation(facts):
    entry = facts.get("entry") or {}
    if entry.get("job_presence") not in {"found", "empty", "internship_only"}:
        return None
    report = facts.get("agent_report") or {}
    return {"status": entry["job_presence"], "checked_at": entry.get("checked_at"),
            "url": entry["url"], "kind": entry["kind"], "job_titles": entry.get("job_titles", []),
            "cohort_status": facts.get("cohort_status", "unspecified"),
            **({"recruitment_url": report.get("recruitment_url"), "reasoning": report.get("reasoning"),
                "citations": report.get("citations", [])} if report else {})}


def check_result(found, *, complete):
    observations = [value for facts, _ in found if (value := job_observation(facts))]
    positive = next((item for item in observations if item["status"] == "found"), None)
    if positive:
        return positive
    internship = next((item for item in observations if item["status"] == "internship_only"), None)
    if internship and complete:
        return internship
    empty = next((item for item in observations if item["status"] == "empty"
                  and not job_filter_url(item["url"])), None)
    if empty and complete:
        return empty
    return {"status": "unknown", "checked_at": datetime.now(UTC).isoformat(),
            "job_titles": [], "cohort_status": "unspecified"}

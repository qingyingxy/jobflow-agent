import hashlib
import json
import sqlite3

import pytest

from scripts.saved_body_integrity import verify_saved_body_changes
from src.services.job_detail_scope import readable_page_text
from src.services.source_understanding import paragraphs


@pytest.mark.parametrize("change,expected", [
    ("newer_saved_source", True), ("altered_body", False), ("invented_read_time", False),
    ("older_saved_source", False), ("missing_snapshot", False), ("deleted_job", False),
])
def test_changes_require_exact_preexisting_body_and_original_read_time(tmp_path, change, expected):
    source, trial = tmp_path / "before.db", tmp_path / "after.db"
    raw = "<main><h1>研发工程师</h1><p>负责开发Agent系统，设计工具调用与运行时能力。</p></main>"
    parts = paragraphs(readable_page_text(raw))
    body = "\n".join(parts)
    captured = "2026-10-19 07:00:00" if change != "older_saved_source" else "2026-10-15 07:00:00"
    url = "https://example.com/jobs/1"
    for path in (source, trial):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE lead_verifications(id TEXT,lead_id TEXT,result TEXT,field_evidence TEXT,checked_at TEXT)")
            conn.execute("CREATE TABLE job_leads(id TEXT,job_posting_id TEXT)")
            if path == trial or change != "missing_snapshot":
                evidence = {"raw_html": raw}
                if path == trial:
                    evidence["page_understanding"] = {"first_paragraph": 0, "last_paragraph": len(parts) - 1}
                conn.execute("INSERT INTO lead_verifications VALUES (?,?,?,?,?)",
                             ("snapshot", "lead", "SNAPSHOT", json.dumps(evidence), captured))
            if path == trial:
                conn.execute("INSERT INTO job_leads VALUES ('lead','job')")
                conn.execute("INSERT INTO lead_verifications VALUES (?,?,?,?,?)", ("verified", "lead", "VERIFIED",
                    json.dumps({"page_scope": {"snapshot_id": "snapshot", "source_url": url}}), "2026-10-19 08:00:00"))
    before = {"job": ["old-hash", url, "更早的原文", "2026-10-17 07:00:00"]}
    if change == "altered_body":
        body += "模型自行添加的职责"
    after = {"job": [hashlib.sha256(body.encode()).hexdigest(), url, body,
        "2026-10-19 08:00:00" if change == "invented_read_time" else captured]}
    if change == "deleted_job":
        after = {}
    result = verify_saved_body_changes(source, trial, before, after)
    assert result["passed"] is expected and result["changed_existing_jobs"] == 1

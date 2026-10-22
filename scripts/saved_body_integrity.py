"""Audit source changes against page snapshots that existed before a trial."""

import hashlib
import json
import sqlite3

from src.services.job_detail_scope import readable_page_text
from src.services.source_understanding import paragraphs


def verify_saved_body_changes(source_path, trial_path, before, after):
    proof = []
    with sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True) as source, \
            sqlite3.connect(trial_path.resolve().as_uri() + "?mode=ro", uri=True) as trial:
        for identifier, old in before.items():
            current = after.get(identifier)
            if current == old:
                continue
            receipt = {"job_id": identifier, "valid": False}
            if current is not None:
                rows = trial.execute("SELECT v.field_evidence FROM lead_verifications v "
                    "JOIN job_leads l ON l.id=v.lead_id WHERE l.job_posting_id=? AND v.result='VERIFIED' "
                    "ORDER BY v.checked_at DESC", (identifier,))
                for (value,) in rows:
                    scope = json.loads(value).get("page_scope", {})
                    snapshot_id = scope.get("snapshot_id")
                    saved = source.execute("SELECT field_evidence,checked_at FROM lead_verifications WHERE id=?",
                                           (snapshot_id,)).fetchone()
                    interpreted = trial.execute("SELECT field_evidence FROM lead_verifications WHERE id=?",
                                                (snapshot_id,)).fetchone()
                    if not saved or not interpreted:
                        continue
                    raw = json.loads(saved[0]).get("raw_html", "")
                    output = json.loads(interpreted[0]).get("page_understanding", {})
                    first, last = output.get("first_paragraph"), output.get("last_paragraph")
                    parts = paragraphs(readable_page_text(raw))
                    if not isinstance(first, int) or not isinstance(last, int) or not 0 <= first <= last < len(parts):
                        continue
                    body = "\n".join(parts[first:last + 1])
                    valid = (body == current[2] and hashlib.sha256(body.encode()).hexdigest() == current[0]
                             and current[3] == saved[1] and current[3] >= old[3]
                             and current[1] == scope.get("source_url"))
                    if valid:
                        receipt = {"job_id": identifier, "valid": True, "snapshot_id": snapshot_id,
                            "snapshot_read_at": saved[1], "old_read_at": old[3], "body_exactly_reconstructed": True}
                        break
            proof.append(receipt)
    return {"passed": all(row["valid"] for row in proof), "changed_existing_jobs": len(proof), "proof": proof}

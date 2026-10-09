"""Re-extract the latest run's saved snapshots without network or JD promotion."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from src.config import get_settings
from src.domain.discovery import DiscoveryRun, JobLead, LeadVerification
from src.infrastructure.database import SessionLocal
from src.services.job_lead_service import normalize_lead_url
from src.services.lead_extraction import extract_lead_preview
from src.services.lead_presentation import discovery_kind


def main():
    with SessionLocal() as session:
        user_id = get_settings().default_user_id
        run = session.scalar(select(DiscoveryRun).where(DiscoveryRun.user_id == user_id).order_by(DiscoveryRun.started_at.desc()).limit(1))
        if not run:
            print("No discovery run")
            return
        leads = list(session.scalars(select(JobLead).where(JobLead.user_id == user_id, JobLead.discovery_run_id == run.id)))
        counts = {"leads": len(leads), "page_previews": 0, "titled_previews": 0, "entries": 0}
        for lead in leads:
            preview = extract_lead_preview(lead.source_url, title=lead.title_hint, snippet=lead.search_snippet)
            snapshots = session.scalars(select(LeadVerification).where(LeadVerification.user_id == user_id,
                LeadVerification.lead_id == lead.id, LeadVerification.result == "SNAPSHOT").order_by(LeadVerification.checked_at.desc()))
            for snapshot in snapshots:
                if normalize_lead_url(snapshot.source_url) != lead.normalized_url:
                    continue
                candidate = extract_lead_preview(snapshot.source_url, raw_html=snapshot.field_evidence.get("raw_html"), snapshot_id=snapshot.id)
                if candidate.get("basis") == "page_snapshot":
                    preview = candidate
                    break
            lead.extracted_fields = preview
            counts["page_previews"] += preview.get("basis") == "page_snapshot"
            counts["titled_previews"] += bool(preview.get("title"))
            counts["entries"] += discovery_kind(lead.source_url, preview.get("title") or lead.title_hint) == "entry"
        session.commit()
        print(json.dumps({"run_id": run.id, **counts}))


if __name__ == "__main__":
    main()

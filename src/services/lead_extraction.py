"""Preview extraction does not assert official ownership or job eligibility."""
import re
from urllib.parse import urlsplit

from src.services.company_registry import enabled_company_sources
from src.services.discovery_matching import _LOCATION_GROUPS
from src.services.job_detail_scope import DetailScopeError, scope_job_document
from src.services.job_fact_verifier import _body_job_type
from src.services.lead_presentation import discovery_kind
from src.services.url_reader import parse_html_document


def extract_lead_preview(url, *, title=None, snippet=None, raw_html=None, snapshot_id=None):
    fields = {}
    raw_hint = title
    document = None
    if raw_html:
        try:
            document, _ = scope_job_document(raw_html, parse_html_document(raw_html), url=url)
        except DetailScopeError:
            pass
    if document:
        title = document.title
        fields.update(title=title, company=document.company, locations=document.locations, raw_content=document.text,
                      job_type=document.job_type, basis="page_snapshot", snapshot_id=snapshot_id)
    elif title and not re.fullmatch(r"(?:https?://)?[\w.-]+\.[a-z]{2,}/?", title, re.IGNORECASE):
        # A list-card label is a preview, never the entire card as the title.
        title = re.split(r"发布于|发布时间|工作地点[:：]|职位类别[:：]", title, maxsplit=1)[0]
        title = re.sub(r"^急\s+", "", title).strip()
        if len(title) <= 160:
            fields.update(title=title, basis="search_hint")
    # Metadata may come from the untrimmed hint. Only infer locations from
    # title/card metadata, not arbitrary mention of cities in job requirements.
    text = " ".join(filter(None, [title if document else raw_hint, snippet if not document else None]))
    if not fields.get("locations"):
        fields["locations"] = [a[0] for a in _LOCATION_GROUPS if a[0] in text]
    if not fields.get("job_type"):
        fields["job_type"] = _body_job_type(title or "")
    if not fields.get("company"):
        companies = {s.company for s in enabled_company_sources() if urlsplit(s.career_url).hostname == urlsplit(url).hostname}
        if len(companies) == 1:
            fields["company"] = companies.pop()
    fields["discovery_kind"] = discovery_kind(url, fields.get("title"))
    fields["verified"] = False
    return fields

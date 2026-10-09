"""Local, conservative upgrade of education evidence written before typed records."""

import hashlib
import re

from sqlalchemy import select

from src.domain.education import (
    EducationRecord,
    degree_levels,
    education_summary,
    validate_education_grounding,
)
from src.domain.education_dates import education_date_support
from src.domain.fact_provenance import record_correction
from src.domain.models import EvidenceItem, UserProfile
from src.services.resume_fact_merge import EDUCATION_FIELDS, _same_education

# Recover only explicitly labelled fields or the common school / major · degree
# table layout. Unrecognised layouts retain the quote with unknown fields.
_TABLE = re.compile(
    r"(?P<school>[\w·]+(?:大学|学院)(?:[（(][^）)\n]*[）)])*)\s+"
    r"(?P<major>[\w与及、 /-]+?)\s*[·|｜]\s*(?:本科|学士|硕士|博士)"
)


def _label(text, label):
    match = re.search(rf"(?:{label})\s*[:：]\s*([^\n，,；;|｜·]+)", text)
    if not match:
        return None
    value = re.split(
        r"\s+(?=(?:学校|专业|学历|学位|入学|毕业|时间)\s*[:：])", match[1]
    )[0].strip()
    return value or None


def education_from_legacy(item: EvidenceItem) -> EducationRecord:
    quote = item.claim.strip()[:2000]
    levels = degree_levels(quote)
    fields = {}
    if len(levels) == 1:
        fields["level"] = next(iter(levels))
        fields["major_raw"] = _label(quote, "专业")
        fields["school"] = _label(quote, "学校|院校")
        table = _TABLE.search(quote)
        if table:
            fields["major_raw"] = fields["major_raw"] or table["major"].strip()
            fields["school"] = fields["school"] or table["school"].strip()
        if len(quote) <= 500:
            try:
                dates = education_date_support(quote)
                for role in ("enrollment", "graduation"):
                    years = getattr(dates, role)
                    if len(years) == 1:
                        fields[f"{role}_year"] = next(iter(years))
                        fields[f"{role}_source_text"] = quote
            except ValueError:
                pass
    record = EducationRecord(
        **fields,
        source_text=quote,
        source=f"resume_asset:legacy:{item.id}",
        id="edu_" + hashlib.sha256(item.id.encode()).hexdigest()[:20],
    )
    validate_education_grounding(record, quote)
    return record


def restore_legacy_education(session, user_id):
    profile = session.get(UserProfile, user_id)
    if profile is None or profile.educations or profile.education_history_complete:
        return profile
    state = dict(profile.resume_import_state or {})
    if state.get("legacy_education_restored"):
        return profile
    items = list(
        session.scalars(
            select(EvidenceItem)
            .where(
                EvidenceItem.user_id == user_id,
                EvidenceItem.type == "education",
            )
            .order_by(EvidenceItem.id)
        )
    )
    if not items or len(items) > 20:
        return profile
    records = []
    for item in items:
        try:
            record = education_from_legacy(item).model_dump(mode="json")
        except ValueError:
            # An invalid/ambiguous record is still visible for correction, and
            # cannot accidentally qualify via the old highest-degree summary.
            record = EducationRecord(
                source_text=item.claim.strip()[:2000],
                source=f"resume_asset:legacy:{item.id}",
                id="edu_" + hashlib.sha256(item.id.encode()).hexdigest()[:20],
            ).model_dump(mode="json")
        if any(
            _same_education(deleted, record)
            for deleted in state.get("deleted_educations", [])
        ):
            continue
        record["provenance"] = record_correction(record, record, EDUCATION_FIELDS)
        records.append(record)
    profile.resume_import_state = {
        **state,
        "legacy_education_restored": [item.id for item in items],
        "legacy_education_summary": {
            "degree": profile.degree,
            "major": profile.major,
            "graduation_year": profile.graduation_year,
        },
    }
    profile.educations = records
    profile.degree, profile.major, profile.graduation_year = education_summary(
        [EducationRecord.model_validate(record) for record in records]
    )
    from src.services.jd_analysis_service import invalidate_analyses_for_user

    invalidate_analyses_for_user(session, user_id)
    session.commit()
    session.refresh(profile)
    return profile

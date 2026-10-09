from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.domain.education import EducationRecord, education_summary
from src.domain.fact_provenance import record_correction
from src.domain.models import UserProfile
from src.services.jd_analysis_service import invalidate_analyses_for_user
from src.services.resume_fact_merge import EDUCATION_FIELDS


def project_education_summary(profile: UserProfile) -> None:
    """Legacy display fields all come from one unambiguous highest record."""
    records = [
        EducationRecord.model_validate(item) for item in profile.educations or []
    ]
    profile.degree, profile.major, profile.graduation_year = education_summary(records)


class ProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: str) -> UserProfile | None:
        from src.services.legacy_education import restore_legacy_education

        return restore_legacy_education(self.session, user_id)

    def upsert(self, user_id: str, changes: dict[str, Any]) -> UserProfile:
        profile = self.session.get(UserProfile, user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self.session.add(profile)

        if (
            profile.educations
            and "educations" not in changes
            and any(
                field in changes and changes[field] != getattr(profile, field)
                for field in ("degree", "major", "graduation_year")
            )
        ):
            raise ValueError(
                "已有分段教育经历，请编辑 educations；旧学历字段仅供兼容展示"
            )

        changes = dict(changes)
        if "educations" in changes:
            previous = {r["id"]: r for r in profile.educations or []}
            updated = []
            for raw in changes["educations"]:
                record = EducationRecord.model_validate(raw).model_dump(mode="json")
                old = previous.get(record["id"])
                if old:
                    old = EducationRecord.model_validate(old).model_dump(mode="json")
                    record["provenance"] = record_correction(
                        old, record, EDUCATION_FIELDS,
                        legacy_reviewed=old["reviewed"] or old["graduation_year_confirmed"],
                    )
                    if old["source"].startswith("resume_asset:"):
                        record["source"], record["source_text"] = old["source"], old["source_text"]
                    if record["graduation_year_confirmed"]:
                        overrides = record["provenance"]["overrides"]
                        record["provenance"]["overrides"] = sorted(set(overrides) | {
                            "graduation_year", "graduation_year_kind", "graduation_source_text",
                        })
                    record["reviewed"] = old["reviewed"] or bool(record["provenance"]["overrides"])
                else:
                    # New manual facts are owned by the user, never the model.
                    record["provenance"] = {}
                    record["provenance"] = record_correction(
                        record, record, EDUCATION_FIELDS,
                        legacy_reviewed=not record["source"].startswith("resume_asset:")
                        or record["reviewed"] or record["graduation_year_confirmed"],
                    )
                updated.append(record)
            deleted = [r for rid, r in previous.items() if rid not in {r["id"] for r in updated}]
            if deleted:
                state = dict(profile.resume_import_state or {})
                state["deleted_educations"] = state.get("deleted_educations", []) + deleted
                profile.resume_import_state = state
            changes["educations"] = updated
        for field, value in changes.items():
            setattr(profile, field, value)
        if "educations" in changes:
            project_education_summary(profile)
        profile.updated_at = datetime.now(UTC)
        invalidate_analyses_for_user(self.session, user_id)

        self.session.commit()
        self.session.refresh(profile)
        return profile

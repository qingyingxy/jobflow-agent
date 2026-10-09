from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.domain.fact_provenance import record_correction
from src.domain.models import EvidenceItem, UserProfile, generate_evidence_id
from src.services.jd_analysis_service import (
    delete_analyses_referencing_evidence,
    invalidate_analyses_for_user,
)
from src.services.resume_fact_merge import EVIDENCE_FIELDS
from src.services.suggestion_service import delete_suggestions_referencing_evidence


class EvidenceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, user_id: str, values: dict[str, object]) -> EvidenceItem:
        item = EvidenceItem(id=generate_evidence_id(), user_id=user_id, **values)
        self.session.add(item)
        invalidate_analyses_for_user(self.session, user_id)
        self.session.commit()
        self.session.refresh(item)
        return item

    def list(
        self,
        user_id: str,
        evidence_type: str | None = None,
        search: str | None = None,
    ) -> list[EvidenceItem]:
        statement = select(EvidenceItem).where(EvidenceItem.user_id == user_id)
        if evidence_type:
            statement = statement.where(EvidenceItem.type == evidence_type)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(EvidenceItem.title.ilike(pattern), EvidenceItem.claim.ilike(pattern))
            )
        statement = statement.order_by(EvidenceItem.created_at.desc(), EvidenceItem.id.desc())
        return list(self.session.scalars(statement).all())

    def get(self, user_id: str, evidence_id: str) -> EvidenceItem | None:
        statement = select(EvidenceItem).where(
            EvidenceItem.id == evidence_id,
            EvidenceItem.user_id == user_id,
        )
        return self.session.scalar(statement)

    def update(
        self,
        user_id: str,
        evidence_id: str,
        changes: dict[str, object],
    ) -> EvidenceItem | None:
        item = self.get(user_id, evidence_id)
        if item is None:
            return None

        changes = {key: value for key, value in changes.items() if value is not None}
        old = {field: getattr(item, field) for field in EVIDENCE_FIELDS}
        old.update(source=item.source, provenance=item.provenance)
        updated = {**old, **changes}
        if changes.pop("keep_current", False):
            updated["provenance"] = {**(item.provenance or {}), "keep_current": True}
        item.provenance = record_correction(old, updated, EVIDENCE_FIELDS)
        for field, value in changes.items():
            if field == "type" and value is None:
                continue
            setattr(item, field, value)
        item.updated_at = datetime.now(UTC)
        invalidate_analyses_for_user(self.session, user_id)

        self.session.commit()
        self.session.refresh(item)
        return item

    def delete(self, user_id: str, evidence_id: str) -> bool:
        item = self.get(user_id, evidence_id)
        if item is None:
            return False
        if item.source.startswith("resume_asset:"):
            profile = self.session.get(UserProfile, user_id)
            if profile is not None:
                state = dict(profile.resume_import_state or {})
                baseline = (item.provenance or {}).get("extracted") or {"claim": item.claim}
                state["deleted_claims"] = list(dict.fromkeys(
                    state.get("deleted_claims", []) + [baseline["claim"]]
                ))
                profile.resume_import_state = state
        delete_analyses_referencing_evidence(
            self.session,
            user_id=user_id,
            evidence_id=evidence_id,
        )
        delete_suggestions_referencing_evidence(
            self.session,
            user_id=user_id,
            evidence_id=evidence_id,
        )
        self.session.delete(item)
        self.session.commit()
        return True

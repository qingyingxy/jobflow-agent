from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.domain.models import EvidenceItem, generate_evidence_id


class EvidenceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, user_id: str, values: dict[str, object]) -> EvidenceItem:
        item = EvidenceItem(id=generate_evidence_id(), user_id=user_id, **values)
        self.session.add(item)
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

        for field, value in changes.items():
            if field == "type" and value is None:
                continue
            setattr(item, field, value)
        item.updated_at = datetime.now(UTC)

        self.session.commit()
        self.session.refresh(item)
        return item

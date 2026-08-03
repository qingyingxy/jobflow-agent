from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.domain.models import UserProfile


class ProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: str) -> UserProfile | None:
        return self.session.get(UserProfile, user_id)

    def upsert(self, user_id: str, changes: dict[str, Any]) -> UserProfile:
        profile = self.get(user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self.session.add(profile)

        for field, value in changes.items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(UTC)

        self.session.commit()
        self.session.refresh(profile)
        return profile

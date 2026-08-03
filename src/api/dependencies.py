from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from src.config import get_settings
from src.infrastructure.database import get_session


def get_current_user_id(
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve the local user identity until a real auth provider is added."""

    candidate = (x_user_id or "").strip()
    return candidate or get_settings().default_user_id


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
DatabaseSession = Annotated[Session, Depends(get_session)]

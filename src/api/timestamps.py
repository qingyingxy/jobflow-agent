"""API instants are UTC; SQLite's legacy naive values already represent UTC.

Normalize response values without changing persisted timestamps or date-only
fields. Local scheduling inputs retain their explicit timezone handling.
"""
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcTimestamp = Annotated[datetime, AfterValidator(as_utc)]

"""Server-maintained extraction baseline and explicit human overrides."""

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FactProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extracted: dict[str, Any] = Field(default_factory=dict)
    overrides: list[str] = Field(default_factory=list)
    conflicts: dict[str, Any] = Field(default_factory=dict)
    acknowledged: dict[str, str] = Field(default_factory=dict)
    # An explicit UI action; ordinary profile saves never acknowledge conflicts.
    keep_current: bool = False


def _difference_key(conflict: dict) -> str:
    value = conflict.get("incoming")
    if isinstance(value, dict):
        value = {
            k: v for k, v in value.items() if k not in {"id", "source", "provenance"}
        }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def note_conflict(metadata: dict, field: str, conflict: dict) -> None:
    if metadata.get("acknowledged", {}).get(field) != _difference_key(conflict):
        metadata.setdefault("conflicts", {})[field] = conflict


def record_correction(
    old: dict,
    updated: dict,
    fields: tuple[str, ...],
    *,
    legacy_reviewed: bool = False,
) -> dict:
    provenance = FactProvenance.model_validate(old.get("provenance") or {})
    submitted = FactProvenance.model_validate(updated.get("provenance") or {})
    if not provenance.extracted:
        provenance.extracted = {field: old.get(field) for field in fields}
        for field in ("source", "source_text"):
            if field in old:
                provenance.extracted[field] = old[field]
        if legacy_reviewed:
            provenance.overrides = list(fields)
    acknowledge = (
        submitted.keep_current
        and submitted.extracted == provenance.extracted
        and submitted.conflicts == provenance.conflicts
    )
    changed = [field for field in fields if updated.get(field) != old.get(field)]
    provenance.overrides = sorted(set(provenance.overrides) | set(changed))
    for field in changed:
        provenance.conflicts.pop(field, None)
    if acknowledge:
        provenance.acknowledged.update(
            {k: _difference_key(v) for k, v in provenance.conflicts.items()}
        )
        provenance.conflicts = {}
    return provenance.model_dump(mode="json")


def merge_extraction(old: dict, incoming: dict, fields: tuple[str, ...]) -> dict:
    provenance = FactProvenance.model_validate(old.get("provenance") or {})
    baseline = provenance.extracted or old
    result = dict(incoming)
    result["id"] = old["id"]
    for field in provenance.overrides:
        if field not in fields:
            continue
        result[field] = old.get(field)
        new_value = incoming.get(field)
        if new_value == old.get(field):
            provenance.conflicts.pop(field, None)
        elif new_value != baseline.get(field) and new_value not in (None, "unknown"):
            provenance.conflicts[field] = {
                "previous_extracted": baseline.get(field),
                "incoming": new_value,
                "source": incoming.get("source"),
                "source_text": incoming.get("source_text", incoming.get("claim")),
            }
    provenance.extracted = {field: incoming.get(field) for field in fields}
    for field in ("source", "source_text"):
        if field in incoming:
            provenance.extracted[field] = incoming[field]
    result["provenance"] = provenance.model_dump(mode="json")
    return result

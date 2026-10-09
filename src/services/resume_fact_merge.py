"""Conservative identity reconciliation, independent of model extraction."""

import hashlib
import json

from src.domain.education import EducationFacts, EducationRecord, comparable
from src.domain.fact_provenance import (
    merge_extraction,
    note_conflict,
    record_correction,
)

EDUCATION_FIELDS = tuple(EducationFacts.model_fields)
EVIDENCE_FIELDS = ("type", "title", "claim", "skills")


def _same_education(old: dict, new: dict) -> bool:
    baseline = (old.get("provenance") or {}).get("extracted") or old
    if comparable(baseline.get("source_text", "")) == comparable(new["source_text"]):
        return True
    # A degree alone (or degree + major alone) is not a record identity.
    return bool(
        baseline.get("school")
        and baseline.get("enrollment_year")
        and baseline.get("level") != "unknown"
        and all(
            baseline.get(key) == new.get(key)
            for key in ("school", "enrollment_year", "level")
        )
    )


def _protected(record: dict) -> bool:
    return bool(
        record.get("reviewed")
        or record.get("graduation_year_confirmed")
        or (record.get("provenance") or {}).get("overrides")
        or not record.get("source", "manual").startswith("resume_asset:")
    )


def merge_educations(
    existing: list[dict], incoming: list[dict]
) -> tuple[list[dict], bool]:
    old_records = [
        EducationRecord.model_validate(r).model_dump(mode="json") for r in existing
    ]
    for old in old_records:
        if _protected(old) and not old["provenance"]["extracted"]:
            old["provenance"] = record_correction(
                old,
                old,
                EDUCATION_FIELDS,
                legacy_reviewed=True,
            )
    pairs = {
        i: [j for j, old in enumerate(old_records) if _same_education(old, new)]
        for i, new in enumerate(incoming)
    }
    used: set[int] = set()
    result: list[dict] = []
    ambiguous = False
    for i, new in enumerate(incoming):
        candidates = pairs[i]
        if (
            len(candidates) == 1
            and sum(candidates[0] in other for other in pairs.values()) == 1
        ):
            j = candidates[0]
            old = old_records[j]
            merged = merge_extraction(old, new, EDUCATION_FIELDS)
            merged["reviewed"] = old["reviewed"]
            merged["graduation_year_confirmed"] = (
                old["graduation_year_confirmed"]
                and merged["graduation_year"] == old["graduation_year"]
            )
            if "graduation_year" in merged["provenance"]["overrides"]:
                merged["graduation_source_text"] = old["graduation_source_text"]
            if "enrollment_year" in merged["provenance"]["overrides"]:
                merged["enrollment_source_text"] = old["enrollment_source_text"]
            try:
                EducationRecord.model_validate(merged)
            except ValueError:
                # A new date must not make a preserved human correction invalid.
                merged = dict(old)
                merged["provenance"] = dict(old["provenance"])
                merged["provenance"]["conflicts"] = {
                    **old["provenance"]["conflicts"],
                    "record": {"incoming": new},
                }
                ambiguous = True
            result.append(merged)
            used.add(j)
            continue
        possible = [
            j
            for j, old in enumerate(old_records)
            if _protected(old)
            and old["level"] == new["level"]
            and (
                not old["school"] or not new["school"] or old["school"] == new["school"]
            )
        ]
        if candidates or possible:
            # Do not expose a possible duplicate as another qualifying degree.
            ambiguous = True
            for j in set(candidates + possible):
                key = hashlib.sha256(
                    json.dumps(
                        {k: new.get(k) for k in (*EDUCATION_FIELDS, "source_text")},
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()[:16]
                note_conflict(
                    old_records[j]["provenance"],
                    f"identity:{key}",
                    {
                        "incoming": new,
                        "reason": "新旧教育经历无法唯一对应，当前值已保留",
                    },
                )
                used.add(j)
                if not any(r["id"] == old_records[j]["id"] for r in result):
                    result.append(old_records[j])
            continue
        new = dict(new)
        new["provenance"] = record_correction(new, new, EDUCATION_FIELDS)
        result.append(new)
    retained = [
        old for j, old in enumerate(old_records) if j not in used and _protected(old)
    ]
    result = retained + result
    # Completeness survives only an unchanged history, including stable IDs.
    unchanged = not ambiguous and {r["id"] for r in result} == {
        r["id"] for r in existing
    }
    return result, unchanged

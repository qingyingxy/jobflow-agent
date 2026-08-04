from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from src.config import get_settings
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.job import RawJobDocument, StructuredJobDescription
from src.domain.matching import EvidenceRecord, requirement_key
from src.evaluation.models import (
    EvaluationManifest,
    PredictionFile,
    PredictionMatch,
    PredictionRecord,
)
from src.infrastructure.llm_client import (
    ModelClientError,
    create_structured_model_client,
)
from src.services.eligibility_checker import check_eligibility
from src.services.evidence_matcher import EvidenceMatcher, EvidenceMatchError
from src.services.jd_parser import JDParser, JDParserError


async def generate_predictions(
    manifest: EvaluationManifest,
    *,
    parser: JDParser,
    matcher: EvidenceMatcher,
    evidence: list[EvidenceRecord],
    profile: CandidateProfileInput | None = None,
    preferences: SearchPreferences | None = None,
    user_id: str = "evaluation-user",
) -> PredictionFile:
    """Generate model predictions without writing jobs or user data to the DB."""

    profile = profile or CandidateProfileInput()
    preferences = preferences or SearchPreferences()
    predictions: list[PredictionRecord] = []

    for case in manifest.cases:
        if case.split != manifest.split:
            continue
        predictions.append(
            await _predict_case(
                case_id=case.id,
                raw_content=case.input.raw_content,
                source_url=case.input.source_url,
                parser=parser,
                matcher=matcher,
                evidence=evidence,
                profile=profile,
                preferences=preferences,
                user_id=user_id,
            )
        )

    return PredictionFile(
        prediction_version=f"generated-{manifest.dataset_version}",
        predictions=predictions,
    )


async def _predict_case(
    *,
    case_id: str,
    raw_content: str | None,
    source_url: str | None,
    parser: JDParser,
    matcher: EvidenceMatcher,
    evidence: list[EvidenceRecord],
    profile: CandidateProfileInput,
    preferences: SearchPreferences,
    user_id: str,
) -> PredictionRecord:
    if raw_content is None:
        return PredictionRecord(case_id=case_id, failure_code="input_not_available")

    document = RawJobDocument(
        source_url=source_url,
        source_type="evaluation",
        raw_content=raw_content,
    )
    try:
        parsed = await parser.parse(document)
    except JDParserError as error:
        return PredictionRecord(case_id=case_id, failure_code=error.code)

    structured = parsed.structured_jd
    fields = _prediction_fields(structured)
    eligibility = check_eligibility(
        EligibilityInput(
            profile=profile,
            preferences=preferences,
            job=structured,
        )
    )
    matches: list[PredictionMatch] = []
    for requirement in structured.requirements or []:
        try:
            match = await matcher.match(
                user_id=user_id,
                requirement=requirement,
                evidence=evidence,
            )
        except EvidenceMatchError as error:
            return PredictionRecord(
                case_id=case_id,
                fields=fields,
                eligibility=eligibility.eligible,
                matches=matches,
                failure_code=error.code,
            )
        matches.append(
            PredictionMatch(
                requirement_key=requirement_key(requirement),
                support_level=match.support_level,
                evidence_ids=match.evidence_ids,
                validation_issues=match.validation_issues,
            )
        )

    return PredictionRecord(
        case_id=case_id,
        fields=fields,
        eligibility=eligibility.eligible,
        matches=matches,
    )


def _prediction_fields(structured: StructuredJobDescription) -> dict[str, Any]:
    payload = structured.model_dump(mode="json")
    return {
        field_name: payload.get(field_name)
        for field_name in ("job_type", "locations", "required_skills")
    }


def main() -> int:
    arguments = _parse_args()
    manifest = EvaluationManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    evidence = _load_evidence(Path(arguments.evidence))
    profile, preferences = _load_profile(Path(arguments.profile))
    settings = get_settings()
    try:
        client = create_structured_model_client(settings)
    except ModelClientError as error:
        raise SystemExit(f"无法创建结构化模型客户端: {error}") from error

    parser = JDParser(
        client,
        prompt_version=settings.prompt_version,
        parser_version=settings.parser_version,
    )
    matcher = EvidenceMatcher(client)
    generation_started_at = datetime.now(UTC)
    generation_started_clock = perf_counter()
    prediction_file = asyncio.run(
        generate_predictions(
            manifest,
            parser=parser,
            matcher=matcher,
            evidence=evidence,
            profile=profile,
            preferences=preferences,
            user_id=arguments.user_id,
        )
    )
    prediction_file = prediction_file.model_copy(
        update={
            "model": client.model_name,
            "prompt_version": settings.prompt_version,
            "generator_version": "evaluation-predict-v1",
            "generated_at": generation_started_at.isoformat(),
            "generation_duration_ms": round(
                (perf_counter() - generation_started_clock) * 1000,
                2,
            ),
            "prediction_failure_count": sum(
                prediction.failure_code is not None
                for prediction in prediction_file.predictions
            ),
        }
    )
    rendered = prediction_file.model_dump_json(indent=2) + "\n"
    output_path = Path(arguments.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(
        f"predictions dataset={manifest.dataset_version} "
        f"split={manifest.split} cases={len(prediction_file.predictions)} "
        f"model={client.model_name} output={arguments.output}"
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate JobFlow predictions from a versioned manifest"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--evidence",
        default="datasets/m11_evaluation_evidence.json",
        help="JSON list of EvidenceRecord objects; defaults to the user-provided review file",
    )
    parser.add_argument(
        "--profile",
        default="datasets/m11_evaluation_profile.json",
        help="JSON profile and search preference context",
    )
    parser.add_argument("--user-id", default="evaluation-user")
    return parser.parse_args()


def _load_evidence(path: Path) -> list[EvidenceRecord]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("evidence", [])
    if not isinstance(payload, list):
        raise TypeError("evidence 文件必须是数组或包含 evidence 数组的对象")
    return [EvidenceRecord.model_validate(item) for item in payload]


def _load_profile(
    path: Path,
) -> tuple[CandidateProfileInput, SearchPreferences]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("profile 文件必须是 JSON 对象")
    profile_payload = payload.get("profile", payload)
    preferences_payload = payload.get("search_preferences", {})
    if isinstance(profile_payload, dict):
        preferences_payload = profile_payload.get(
            "search_preferences",
            preferences_payload,
        )
        profile_payload = {
            key: profile_payload.get(key)
            for key in ("graduation_year", "degree", "major")
        }
    else:
        profile_payload = {}
    if not isinstance(preferences_payload, dict):
        preferences_payload = {}
    return (
        CandidateProfileInput.model_validate(profile_payload),
        SearchPreferences.model_validate(preferences_payload),
    )


if __name__ == "__main__":
    raise SystemExit(main())

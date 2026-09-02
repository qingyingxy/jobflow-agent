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
from src.services.core_jd_parser import CoreJDParser
from src.services.eligibility_checker import check_eligibility
from src.services.evidence_matcher import EvidenceMatcher, EvidenceMatchError
from src.services.jd_parser import JDParser, JDParserError
from src.services.staged_jd_parser import StagedJDParser


async def generate_predictions(
    manifest: EvaluationManifest,
    *,
    parser: JDParser | CoreJDParser | StagedJDParser,
    matcher: EvidenceMatcher,
    evidence: list[EvidenceRecord],
    profile: CandidateProfileInput | None = None,
    preferences: SearchPreferences | None = None,
    user_id: str = "evaluation-user",
    parser_only: bool = False,
    parser_mode: str = "full",
    concurrency: int = 1,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    case_timeout_seconds: float | None = None,
    retry_failures: bool = False,
) -> PredictionFile:
    """Generate model predictions without writing jobs or user data to the DB."""

    profile = profile or CandidateProfileInput()
    preferences = preferences or SearchPreferences()
    cases = [case for case in manifest.cases if case.split == manifest.split]
    predictions_by_id: dict[str, PredictionRecord] = {}
    if resume and checkpoint_path and checkpoint_path.exists():
        checkpoint = PredictionFile.model_validate_json(
            checkpoint_path.read_text(encoding="utf-8")
        )
        predictions_by_id = {
            prediction.case_id: prediction for prediction in checkpoint.predictions
        }
        if retry_failures:
            predictions_by_id = {
                case_id: prediction
                for case_id, prediction in predictions_by_id.items()
                if prediction.failure_code is None
            }

    pending_cases = [case for case in cases if case.id not in predictions_by_id]
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_case(case: Any) -> PredictionRecord:
        async with semaphore:
            operation = _predict_case(
                case_id=case.id,
                raw_content=case.input.raw_content,
                source_url=case.input.source_url,
                parser=parser,
                matcher=matcher,
                evidence=evidence,
                profile=profile,
                preferences=preferences,
                user_id=user_id,
                parser_only=parser_only,
                parser_mode=parser_mode,
            )
            try:
                if case_timeout_seconds is None:
                    return await operation
                return await asyncio.wait_for(operation, timeout=case_timeout_seconds)
            except TimeoutError:
                return PredictionRecord(
                    case_id=case.id,
                    failure_code="model_timeout",
                    failure_details={
                        "timeout_seconds": case_timeout_seconds,
                    },
                )

    tasks = [asyncio.create_task(run_case(case)) for case in pending_cases]
    for task in asyncio.as_completed(tasks):
        prediction = await task
        predictions_by_id[prediction.case_id] = prediction
        if checkpoint_path:
            _write_checkpoint(
                checkpoint_path,
                manifest=manifest,
                predictions=predictions_by_id,
            )

    predictions = [predictions_by_id[case.id] for case in cases]

    return PredictionFile(
        prediction_version=f"generated-{manifest.dataset_version}",
        predictions=predictions,
    )


def _write_checkpoint(
    path: Path,
    *,
    manifest: EvaluationManifest,
    predictions: dict[str, PredictionRecord],
) -> None:
    ordered = [
        predictions[case.id]
        for case in manifest.cases
        if case.split == manifest.split and case.id in predictions
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        PredictionFile(
            prediction_version=f"checkpoint-{manifest.dataset_version}",
            predictions=ordered,
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )


async def _predict_case(
    *,
    case_id: str,
    raw_content: str | None,
    source_url: str | None,
    parser: JDParser | CoreJDParser | StagedJDParser,
    matcher: EvidenceMatcher,
    evidence: list[EvidenceRecord],
    profile: CandidateProfileInput,
    preferences: SearchPreferences,
    user_id: str,
    parser_only: bool,
    parser_mode: str,
) -> PredictionRecord:
    if raw_content is None:
        return PredictionRecord(case_id=case_id, failure_code="input_not_available")

    document = RawJobDocument(
        source_url=source_url,
        source_type="evaluation",
        raw_content=raw_content,
    )
    if parser_mode == "core":
        if not parser_only:
            return PredictionRecord(
                case_id=case_id,
                failure_code="core_parser_requires_parser_only",
            )
        if not isinstance(parser, CoreJDParser):
            return PredictionRecord(
                case_id=case_id,
                failure_code="parser_mode_mismatch",
            )
        try:
            parsed_core = await parser.parse(document)
        except JDParserError as error:
            return PredictionRecord(
                case_id=case_id,
                failure_code=error.code,
                failure_details=error.details,
            )
        return PredictionRecord(
            case_id=case_id,
            fields=_prediction_core_fields(parsed_core.fields),
            warnings=list(parsed_core.warnings),
        )

    if parser_mode == "staged":
        if not isinstance(parser, StagedJDParser):
            return PredictionRecord(
                case_id=case_id,
                failure_code="parser_mode_mismatch",
            )
        try:
            parsed_staged = await parser.parse(document)
        except JDParserError as error:
            return PredictionRecord(
                case_id=case_id,
                failure_code=error.code,
                failure_details=error.details,
            )
        structured = parsed_staged.structured_jd
        parsing_warnings = list(parsed_staged.warnings)
    else:
        if not isinstance(parser, JDParser):
            return PredictionRecord(
                case_id=case_id,
                failure_code="parser_mode_mismatch",
            )
        try:
            parsed = await parser.parse(document)
        except JDParserError as error:
            return PredictionRecord(
                case_id=case_id,
                failure_code=error.code,
                failure_details=error.details,
            )
        structured = parsed.structured_jd
        parsing_warnings = list(parsed.warnings)
    fields = _prediction_fields(structured)
    if parser_only:
        return PredictionRecord(
            case_id=case_id,
            fields=fields,
            warnings=parsing_warnings,
        )

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
                warnings=parsing_warnings,
                failure_code=error.code,
                failure_details=error.details,
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
        warnings=parsing_warnings,
    )


def _prediction_fields(structured: StructuredJobDescription) -> dict[str, Any]:
    return _evaluation_fields(structured.model_dump(mode="json"))


def _prediction_core_fields(fields: Any) -> dict[str, Any]:
    return _evaluation_fields(fields.model_dump(mode="json"))


def _evaluation_fields(payload: dict[str, Any]) -> dict[str, Any]:
    fields = {
        field_name: payload.get(field_name)
        for field_name in ("job_type", "locations", "required_skills")
    }
    for field_name in (
        "required_skill_groups",
        "preferred_skills",
        "skill_mentions",
        "skill_concepts",
    ):
        if payload.get(field_name) is not None:
            fields[field_name] = payload[field_name]
    return fields


def main() -> int:
    arguments = _parse_args()
    manifest = EvaluationManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    if arguments.parser_only:
        evidence = []
        profile = CandidateProfileInput()
        preferences = SearchPreferences()
    else:
        evidence = _load_evidence(Path(arguments.evidence))
        profile, preferences = _load_profile(Path(arguments.profile))
    settings = get_settings()
    if arguments.parser_mode == "core" and not arguments.parser_only:
        raise SystemExit("--parser-mode core 必须与 --parser-only 一起使用")
    try:
        client = create_structured_model_client(settings)
    except ModelClientError as error:
        raise SystemExit(f"无法创建结构化模型客户端: {error}") from error

    if arguments.parser_mode == "core":
        parser = CoreJDParser(
            client,
            prompt_version=settings.core_prompt_version,
            parser_version=settings.core_parser_version,
            validation_retries=settings.parser_validation_retries,
        )
    elif arguments.parser_mode == "staged":
        parser = StagedJDParser(
            client,
            prompt_version=settings.staged_prompt_version,
            parser_version=settings.staged_parser_version,
            core_prompt_version=settings.core_prompt_version,
            detail_prompt_version=settings.detail_prompt_version,
            validation_retries=settings.parser_validation_retries,
        )
    else:
        parser = JDParser(
            client,
            prompt_version=settings.prompt_version,
            parser_version=settings.parser_version,
            validation_retries=settings.parser_validation_retries,
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
            parser_only=arguments.parser_only,
            parser_mode=arguments.parser_mode,
            concurrency=arguments.concurrency,
            checkpoint_path=Path(arguments.checkpoint)
            if arguments.checkpoint
            else None,
            resume=arguments.resume,
            case_timeout_seconds=arguments.case_timeout,
            retry_failures=arguments.retry_failures,
        )
    )
    prediction_file = prediction_file.model_copy(
        update={
            "model": client.model_name,
            "prompt_version": parser.prompt_version,
            "generator_version": (
                f"evaluation-predict-{arguments.parser_mode}"
                f"{'-only' if arguments.parser_only else ''}-v1"
            ),
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
    parser.add_argument(
        "--parser-only",
        action="store_true",
        help="只运行 JD Parser，不读取用户证据，也不运行资格和证据匹配",
    )
    parser.add_argument(
        "--parser-mode",
        choices=("staged", "full", "core"),
        default="staged",
        help="岗位解析模式；staged 为真实产品默认的两阶段模式",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="并发模型请求数；默认 1，真实批量评测建议使用小于等于 4",
    )
    parser.add_argument(
        "--checkpoint",
        help="按 case 保存的中间 prediction 文件",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从 checkpoint 跳过已完成的 case",
    )
    parser.add_argument(
        "--case-timeout",
        type=float,
        default=None,
        help="单个 case 的额外等待上限（秒）；超时记为 model_timeout",
    )
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="配合 --resume 使用，只重试 checkpoint 中已有 failure_code 的 case",
    )
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

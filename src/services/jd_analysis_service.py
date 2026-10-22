from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.domain.analysis import (
    ANALYSIS_VERSION,
    AnalysisRisk,
    JobAnalysis,
    generate_job_analysis_id,
)
from src.domain.education import EducationRecord, education_summary
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    EligibilityResult,
    SearchPreferences,
)
from src.domain.job import JobPosting, StructuredJobDescription
from src.domain.matching import EvidenceRecord, RequirementMatch
from src.domain.models import EvidenceItem
from src.domain.runs import JobParseResult
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParser
from src.services.job_correction_service import effective_structure
from src.services.job_fact_grounding import ground_runtime_facts
from src.services.job_parse_service import (
    JDParseFailure,
    JobNotFoundError,
    JobParseService,
)
from src.services.local_evidence_matcher import match_requirements_locally
from src.services.match_score import calculate_match_score
from src.services.product_jd_parser import ProductJDParser
from src.services.semantic_evidence_matcher import SemanticEvidenceMatcher
from src.services.semantic_matching_service import match_with_cache
from src.services.staged_jd_parser import StagedJDParser


class JDAnalysisFailure(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        agent_run_id: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.agent_run_id = agent_run_id
        self.code = code
        self.details = details or {}


class AnalysisContentChangedError(LookupError):
    pass


@dataclass(frozen=True)
class JobAnalysisExecution:
    analysis: JobAnalysis
    posting: JobPosting
    parse_result: JobParseResult
    agent_run_ids: list[str]


@dataclass(frozen=True)
class JobAnalysisView:
    analysis: JobAnalysis
    posting: JobPosting
    parse_result: JobParseResult


def invalidate_analyses_for_user(session: Session, user_id: str) -> int:
    """Invalidate active analyses before a profile or evidence change commits."""

    result = session.execute(
        update(JobAnalysis)
        .where(
            JobAnalysis.user_id == user_id,
            JobAnalysis.invalidated_at.is_(None),
        )
        .values(invalidated_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)


def invalidate_analyses_for_job(
    session: Session,
    *,
    user_id: str | None = None,
    job_id: str,
) -> int:
    statement = update(JobAnalysis).where(
        JobAnalysis.job_posting_id == job_id,
        JobAnalysis.invalidated_at.is_(None),
    )
    if user_id is not None:
        statement = statement.where(JobAnalysis.user_id == user_id)
    result = session.execute(statement.values(invalidated_at=datetime.now(UTC)))
    return int(result.rowcount or 0)


def delete_analyses_referencing_evidence(
    session: Session,
    *,
    user_id: str,
    evidence_id: str,
) -> int:
    """Hard-delete user analyses whose stored matches cite one evidence item."""

    analyses = list(
        session.scalars(select(JobAnalysis).where(JobAnalysis.user_id == user_id)).all()
    )
    deleted = 0
    for analysis in analyses:
        if any(
            evidence_id in (match.get("evidence_ids") or [])
            for match in (analysis.matches or [])
        ):
            session.delete(analysis)
            deleted += 1
    return deleted


class JDAnalysisService:
    """Combine local qualifications with optional batch semantic matching."""

    def __init__(
        self,
        session: Session,
        *,
        parser: JDParser | StagedJDParser | ProductJDParser | None = None,
        matcher: object | None = None,
        semantic_matcher: SemanticEvidenceMatcher | None = None,
    ) -> None:
        self.session = session
        self.parser = parser
        # Kept as a no-op keyword during the product-v1 migration so callers that
        # construct the old service do not break. Runtime analysis never uses it.
        self.legacy_matcher = matcher
        self.semantic_matcher = semantic_matcher

    async def analyze(self, *, user_id: str, job_id: str, saved_parse=None) -> JobAnalysisExecution:
        if self.parser is None and saved_parse is None:
            raise ValueError("分析服务需要配置 parser")

        try:
            if saved_parse is not None:
                parse_execution = SimpleNamespace(parse_result=saved_parse, agent_run=SimpleNamespace(id=""))
            else:
                parse_execution = await JobParseService(self.session, self.parser).parse(
                    user_id=user_id, job_id=job_id,
                )
        except JobNotFoundError:
            raise
        except JDParseFailure as error:
            raise JDAnalysisFailure(
                stage="jd_parse",
                agent_run_id=error.agent_run_id,
                code=error.code,
                message=str(error),
                details=error.details,
            ) from error

        posting = self.session.get(JobPosting, job_id)
        if posting is None:
            raise JobNotFoundError(job_id)

        try:
            structured = effective_structure(self.session, user_id, parse_execution.parse_result)
        except Exception as error:
            raise JDAnalysisFailure(
                stage="stored_parse_result",
                agent_run_id=parse_execution.agent_run.id,
                code="stored_parse_result_invalid",
                message="已保存的岗位解析结果无法再次校验",
            ) from error

        profile_input, preferences = self._profile_inputs(user_id)
        structured = ground_runtime_facts(structured, posting.raw_content)
        evidence = self._evidence_records(user_id)
        matching_identity = (
            self.semantic_matcher.identity() if self.semantic_matcher else None
        )
        input_hash = _analysis_input_hash(
            structured=structured,
            profile=profile_input,
            preferences=preferences,
            evidence=evidence,
            matching_identity=matching_identity,
        )
        cached = self.session.scalar(
            select(JobAnalysis)
            .where(
                JobAnalysis.user_id == user_id,
                JobAnalysis.job_posting_id == job_id,
                JobAnalysis.parse_result_id == parse_execution.parse_result.id,
                JobAnalysis.input_hash == input_hash,
                JobAnalysis.analysis_version == ANALYSIS_VERSION,
                JobAnalysis.invalidated_at.is_(None),
            )
            .order_by(JobAnalysis.created_at.desc())
        )
        if cached and all(
            m.get("validation_status") == "passed" for m in cached.matches
        ):
            return JobAnalysisExecution(
                cached,
                posting,
                parse_execution.parse_result,
                [parse_execution.agent_run.id] if parse_execution.agent_run.id else [],
            )
        eligibility = check_eligibility(
            EligibilityInput(
                profile=profile_input,
                preferences=preferences,
                job=structured,
            ),
            include_search_preferences=False,
        )
        requirements = structured.requirements or []
        ordinary = [
            r
            for r in requirements
            if r.education is None and r.category not in {"education", "major"}
        ]
        local_requirements = (
            [r for r in requirements if r not in ordinary]
            if self.semantic_matcher
            else requirements
        )
        matches = match_requirements_locally(
            user_id=user_id,
            requirements=local_requirements,
            evidence=evidence,
            profile=profile_input,
            education_checks=[
                check for check in eligibility.checks if check.field == "educations"
            ],
        )
        agent_run_ids = [parse_execution.agent_run.id] if parse_execution.agent_run.id else []
        if self.semantic_matcher and ordinary:
            semantic_matches, matching_run_id = await match_with_cache(
                self.session,
                matcher=self.semantic_matcher,
                user_id=user_id,
                job_id=job_id,
                requirements=ordinary,
                evidence=evidence,
            )
            agent_run_ids.append(matching_run_id)
            local_iter, semantic_iter = iter(matches), iter(semantic_matches)
            matches = [
                next(semantic_iter) if r in ordinary else next(local_iter)
                for r in requirements
            ]
            # Do not publish conclusions about old facts after a concurrent edit.
            self.session.expire_all()
            current_profile, current_preferences = self._profile_inputs(user_id)
            current_hash = _analysis_input_hash(
                structured=ground_runtime_facts(effective_structure(self.session, user_id, parse_execution.parse_result), posting.raw_content),
                profile=current_profile,
                preferences=current_preferences,
                evidence=self._evidence_records(user_id),
                matching_identity=matching_identity,
            )
            if (
                current_hash != input_hash
                or posting.content_hash != parse_execution.parse_result.content_hash
            ):
                raise JDAnalysisFailure(
                    stage="matching",
                    agent_run_id=matching_run_id,
                    code="analysis_inputs_changed",
                    message="分析期间资料或岗位已更新，请使用最新内容重新分析。",
                )

        score = calculate_match_score(
            requirements=structured.requirements,
            matches=matches,
            eligibility=eligibility,
        )
        risks = _build_risks(eligibility, matches, score)

        invalidate_analyses_for_job(
            self.session,
            user_id=user_id,
            job_id=job_id,
        )
        analysis = JobAnalysis(
            id=generate_job_analysis_id(),
            user_id=user_id,
            job_posting_id=job_id,
            parse_result_id=parse_execution.parse_result.id,
            analysis_version=ANALYSIS_VERSION,
            input_hash=input_hash,
            structured_jd=structured.model_dump(mode="json"),
            eligibility=eligibility.model_dump(mode="json"),
            matches=[item.model_dump(mode="json") for item in matches],
            score=score.model_dump(mode="json"),
            risks=[item.model_dump(mode="json") for item in risks],
            missing_information=score.missing_information,
        )
        self.session.add(analysis)
        self.session.commit()
        self.session.refresh(analysis)
        return JobAnalysisExecution(
            analysis=analysis,
            posting=posting,
            parse_result=parse_execution.parse_result,
            agent_run_ids=agent_run_ids,
        )

    def latest(self, *, user_id: str, job_id: str) -> JobAnalysisView | None:
        posting = self.session.get(JobPosting, job_id)
        if posting is None:
            raise JobNotFoundError(job_id)

        from src.services.legacy_education import restore_legacy_education

        restore_legacy_education(self.session, user_id)

        rows = self.session.execute(
            select(JobAnalysis, JobParseResult)
            .join(JobParseResult, JobParseResult.id == JobAnalysis.parse_result_id)
            .where(
                JobAnalysis.user_id == user_id,
                JobAnalysis.job_posting_id == job_id,
                JobAnalysis.invalidated_at.is_(None),
                JobAnalysis.analysis_version == ANALYSIS_VERSION,
            )
            .order_by(JobAnalysis.created_at.desc(), JobAnalysis.id.desc())
        ).all()
        stale_found = False
        for analysis, parse_result in rows:
            if parse_result.content_hash != posting.content_hash:
                analysis.invalidated_at = datetime.now(UTC)
                stale_found = True
                continue
            if stale_found:
                self.session.commit()
            return JobAnalysisView(
                analysis=analysis,
                posting=posting,
                parse_result=parse_result,
            )
        if stale_found:
            self.session.commit()
            raise AnalysisContentChangedError(job_id)
        return None

    def _profile_inputs(
        self,
        user_id: str,
    ) -> tuple[CandidateProfileInput, SearchPreferences]:
        from src.services.legacy_education import restore_legacy_education

        profile = restore_legacy_education(self.session, user_id)
        if profile is None:
            return CandidateProfileInput(), SearchPreferences()
        records = [
            EducationRecord.model_validate(item) for item in profile.educations or []
        ]
        degree, major, year = profile.degree, profile.major, profile.graduation_year
        if records or profile.education_history_complete:
            degree, major, year = education_summary(records)
        elif self.session.scalar(select(EvidenceItem.id).where(
            EvidenceItem.user_id == user_id, EvidenceItem.type == "education",
        ).limit(1)):
            # Unconverted legacy records must not fall back to a possibly mixed
            # highest-degree/major summary (for example when over capacity).
            degree, major, year = None, None, None
        return (
            CandidateProfileInput(
                graduation_year=year,
                degree=degree,
                major=major,
                educations=records,
                education_history_complete=profile.education_history_complete,
            ),
            # Discovery owns search conditions; saved preferences are not qualifications.
            SearchPreferences(),
        )

    def _evidence_records(self, user_id: str) -> list[EvidenceRecord]:
        items = self.session.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.user_id == user_id, EvidenceItem.type != "education")
            .order_by(EvidenceItem.id)
        ).all()
        return [
            EvidenceRecord(
                id=item.id,
                user_id=item.user_id,
                title=item.title,
                claim=item.claim,
                skills=item.skills,
                source=item.source,
            )
            for item in items
        ]


def _analysis_input_hash(
    *,
    structured: StructuredJobDescription,
    profile: CandidateProfileInput,
    preferences: SearchPreferences,
    evidence: list[EvidenceRecord],
    matching_identity: dict | None = None,
) -> str:
    payload = {
        "analysis_version": ANALYSIS_VERSION,
        "structured_jd": structured.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "preferences": preferences.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "matching": matching_identity or {"strategy": "local"},
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _build_risks(
    eligibility: EligibilityResult,
    matches: list[RequirementMatch],
    score: Any,
) -> list[AnalysisRisk]:
    risks: list[AnalysisRisk] = []
    seen: set[str] = set()

    def add(risk: AnalysisRisk) -> None:
        if risk.code not in seen:
            risks.append(risk)
            seen.add(risk.code)

    for check in eligibility.checks:
        if check.result == "fail":
            add(
                AnalysisRisk(
                    code=f"eligibility_fail:{check.rule_name}",
                    severity="high",
                    title="硬性资格未满足",
                    detail=check.reason,
                )
            )
        elif check.result == "unknown":
            add(
                AnalysisRisk(
                    code=f"eligibility_unknown:{check.rule_name}",
                    severity="medium",
                    title="资格信息待确认",
                    detail=check.reason,
                )
            )

    for match in matches:
        requirement_name = match.requirement.name
        requirement_id = hashlib.sha256(
            json.dumps(
                match.requirement.model_dump(mode="json"),
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()[:24]
        if match.validation_status == "failed":
            add(
                AnalysisRisk(
                    code=f"evidence_validation:{requirement_id}",
                    severity="medium",
                    title="部分能力暂未完成判断",
                    detail="分析超时或输出未通过校验，已保留为信息不足；岗位与资格结果仍可查看，可稍后重试。",
                    requirement_name=requirement_name,
                )
            )
        elif match.support_level == "unsupported":
            add(
                AnalysisRisk(
                    code=f"evidence_missing:{requirement_id}",
                    severity="high" if match.requirement.mandatory else "low",
                    title=(
                        "缺少必备要求的经历证据"
                        if match.requirement.mandatory
                        else "缺少加分要求的经历证据"
                    ),
                    detail=match.explanation,
                    requirement_name=requirement_name,
                )
            )
        elif match.support_level in {"partial", "needs_confirmation"}:
            add(
                AnalysisRisk(
                    code=f"evidence_confirmation:{requirement_id}",
                    severity="medium" if match.requirement.mandatory else "low",
                    title="经历证据待确认",
                    detail=match.explanation,
                    requirement_name=requirement_name,
                )
            )

    if score.score is None:
        add(
            AnalysisRisk(
                code="score_insufficient_data",
                severity="medium",
                title="申请建议暂不可判断",
                detail="岗位要求或用户资料不足，请补充后重新分析。",
            )
        )
    return risks

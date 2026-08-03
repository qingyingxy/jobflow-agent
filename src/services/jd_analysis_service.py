from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.domain.analysis import (
    ANALYSIS_VERSION,
    AnalysisRisk,
    JobAnalysis,
    generate_job_analysis_id,
)
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    EligibilityResult,
    SearchPreferences,
)
from src.domain.job import JobPosting, StructuredJobDescription
from src.domain.matching import EvidenceRecord, RequirementMatch
from src.domain.models import EvidenceItem, UserProfile
from src.domain.runs import JobParseResult
from src.services.eligibility_checker import check_eligibility
from src.services.evidence_match_service import (
    EvidenceMatchFailure,
    EvidenceMatchService,
)
from src.services.evidence_matcher import EvidenceMatcher
from src.services.jd_parser import JDParser
from src.services.job_parse_service import (
    JDParseFailure,
    JobNotFoundError,
    JobParseService,
)
from src.services.match_score import calculate_match_score


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
        session.scalars(
            select(JobAnalysis).where(JobAnalysis.user_id == user_id)
        ).all()
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
    """Run the complete synchronous M7 analysis pipeline for one user and JD."""

    def __init__(
        self,
        session: Session,
        *,
        parser: JDParser | None = None,
        matcher: EvidenceMatcher | None = None,
    ) -> None:
        self.session = session
        self.parser = parser
        self.matcher = matcher

    async def analyze(self, *, user_id: str, job_id: str) -> JobAnalysisExecution:
        if self.parser is None or self.matcher is None:
            raise ValueError("分析服务需要同时配置 parser 和 matcher")

        try:
            parse_execution = await JobParseService(self.session, self.parser).parse(
                user_id=user_id,
                job_id=job_id,
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
            structured = StructuredJobDescription.model_validate(
                parse_execution.parse_result.structured_jd
            )
        except Exception as error:
            raise JDAnalysisFailure(
                stage="stored_parse_result",
                agent_run_id=parse_execution.agent_run.id,
                code="stored_parse_result_invalid",
                message="已保存的岗位解析结果无法再次校验",
            ) from error

        profile_input, preferences = self._profile_inputs(user_id)
        eligibility = check_eligibility(
            EligibilityInput(
                profile=profile_input,
                preferences=preferences,
                job=structured,
            )
        )
        evidence = self._evidence_records(user_id)
        matches: list[RequirementMatch] = []
        agent_run_ids = [parse_execution.agent_run.id]
        match_service = EvidenceMatchService(self.session, self.matcher)

        for index, requirement in enumerate(structured.requirements or []):
            try:
                execution = await match_service.match(
                    user_id=user_id,
                    requirement=requirement,
                    target_id=f"{job_id}:{index}",
                )
            except EvidenceMatchFailure as error:
                raise JDAnalysisFailure(
                    stage="evidence_match",
                    agent_run_id=error.agent_run_id,
                    code=error.code,
                    message=str(error),
                ) from error
            matches.append(execution.match)
            agent_run_ids.append(execution.agent_run.id)

        score = calculate_match_score(
            requirements=structured.requirements,
            matches=matches,
            eligibility=eligibility,
        )
        risks = _build_risks(eligibility, matches, score)
        input_hash = _analysis_input_hash(
            structured=structured,
            profile=profile_input,
            preferences=preferences,
            evidence=evidence,
        )

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
        profile = self.session.get(UserProfile, user_id)
        if profile is None:
            return CandidateProfileInput(), SearchPreferences()
        return (
            CandidateProfileInput(
                graduation_year=profile.graduation_year,
                degree=profile.degree,
                major=profile.major,
            ),
            SearchPreferences.model_validate(profile.search_preferences or {}),
        )

    def _evidence_records(self, user_id: str) -> list[EvidenceRecord]:
        items = self.session.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.user_id == user_id)
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
) -> str:
    payload = {
        "analysis_version": ANALYSIS_VERSION,
        "structured_jd": structured.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "preferences": preferences.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
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
        if match.validation_status == "failed":
            add(
                AnalysisRisk(
                    code=f"evidence_validation:{requirement_name}",
                    severity="medium",
                    title="证据匹配已安全降级",
                    detail="模型引用未通过事实校验，已清空非法引用并按 unsupported 处理。",
                    requirement_name=requirement_name,
                )
            )
        elif match.support_level == "unsupported":
            add(
                AnalysisRisk(
                    code=f"evidence_missing:{requirement_name}",
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

    if score.score is None:
        add(
            AnalysisRisk(
                code="score_insufficient_data",
                severity="medium",
                title="匹配分数暂不可计算",
                detail="岗位要求或用户偏好信息不足，请补充后重新分析。",
            )
        )
    return risks

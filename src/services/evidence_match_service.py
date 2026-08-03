from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord, RequirementMatch, requirement_key
from src.domain.models import EvidenceItem
from src.domain.runs import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCEEDED,
    RUN_TYPE_EVIDENCE_MATCH,
    VALIDATION_FAILED,
    VALIDATION_PASSED,
    AgentRun,
    generate_agent_run_id,
)
from src.services.evidence_matcher import EvidenceMatcher, EvidenceMatchError


class EvidenceMatchFailure(RuntimeError):
    def __init__(
        self,
        *,
        agent_run_id: str,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.agent_run_id = agent_run_id
        self.code = code


@dataclass(frozen=True)
class EvidenceMatchExecution:
    match: RequirementMatch
    agent_run: AgentRun


class EvidenceMatchService:
    """Persist the shared AgentRun while keeping matching itself replaceable."""

    def __init__(self, session: Session, matcher: EvidenceMatcher) -> None:
        self.session = session
        self.matcher = matcher

    async def match(
        self,
        *,
        user_id: str,
        requirement: JobRequirement,
        target_id: str | None = None,
    ) -> EvidenceMatchExecution:
        items = list(
            self.session.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.user_id == user_id)
                .order_by(EvidenceItem.id)
            ).all()
        )
        records = [
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
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "requirement": requirement.model_dump(mode="json"),
                    "evidence": [item.model_dump(mode="json") for item in records],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        agent_run = AgentRun(
            id=generate_agent_run_id(),
            user_id=user_id,
            run_type=RUN_TYPE_EVIDENCE_MATCH,
            target_type="job_requirement",
            target_id=target_id or requirement_key(requirement),
            status=RUN_STATUS_FAILED,
            model=self.matcher.model_name,
            prompt_version=self.matcher.prompt_version,
            input_hash=input_hash,
            validation_status=VALIDATION_FAILED,
            started_at=started_at,
        )
        self.session.add(agent_run)
        self.session.flush()

        try:
            match = await self.matcher.match(
                user_id=user_id,
                requirement=requirement,
                evidence=records,
            )
        except EvidenceMatchError as error:
            agent_run.status = RUN_STATUS_FAILED
            agent_run.validation_status = VALIDATION_FAILED
            agent_run.validation_result = {"status": VALIDATION_FAILED, "code": error.code}
            agent_run.error = str(error)
            self._finish(agent_run, started_clock)
            self.session.commit()
            raise EvidenceMatchFailure(
                agent_run_id=agent_run.id,
                code=error.code,
                message=str(error),
            ) from error

        output = match.model_dump(mode="json")
        agent_run.status = RUN_STATUS_SUCCEEDED
        agent_run.validation_status = (
            VALIDATION_PASSED
            if match.validation_status == VALIDATION_PASSED
            else VALIDATION_FAILED
        )
        agent_run.output = output
        agent_run.validation_result = {
            "status": agent_run.validation_status,
            "issues": match.validation_issues,
        }
        if match.validation_status == VALIDATION_FAILED:
            agent_run.error = "匹配结果已安全降级为 unsupported"
        self._finish(agent_run, started_clock)
        self.session.commit()
        self.session.refresh(agent_run)
        return EvidenceMatchExecution(match=match, agent_run=agent_run)

    @staticmethod
    def _finish(agent_run: AgentRun, started_clock: float) -> None:
        agent_run.finished_at = datetime.now(UTC)
        agent_run.duration_ms = round((perf_counter() - started_clock) * 1000, 2)

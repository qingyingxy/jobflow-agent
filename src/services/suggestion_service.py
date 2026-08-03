from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.analysis import JobAnalysis
from src.domain.matching import EvidenceRecord
from src.domain.models import EvidenceItem
from src.domain.runs import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCEEDED,
    RUN_TYPE_RESUME_SUGGESTION,
    VALIDATION_FAILED,
    VALIDATION_PASSED,
    AgentRun,
    generate_agent_run_id,
)
from src.domain.suggestion import (
    ResumeSuggestion,
    ResumeSuggestionModelOutput,
    SuggestionDecision,
    SuggestionStatus,
    SuggestionTargetInput,
    generate_suggestion_id,
)
from src.infrastructure.llm_client import ModelClientError, StructuredModelClient
from src.services.application_service import (
    ApplicationService,
)
from src.services.evidence_validator import validate_suggestion_output
from src.services.suggestion_generator import (
    SUGGESTION_PROMPT_VERSION,
    SuggestionGenerator,
)


class JobAnalysisNotFoundError(LookupError):
    pass


class SuggestionNotFoundError(LookupError):
    pass


class InvalidSuggestionDecisionError(RuntimeError):
    def __init__(self, *, status: str, decision: str) -> None:
        self.status = status
        self.decision = decision
        super().__init__(f"建议当前状态为 {status}，不能执行 {decision} 决策")


class SuggestionGenerationFailure(RuntimeError):
    def __init__(
        self,
        *,
        agent_run_id: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.agent_run_id = agent_run_id
        self.code = code
        self.details = details or {}


class SuggestionService:
    """Generate evidence-grounded suggestions and persist human decisions."""

    def __init__(
        self,
        session: Session,
        client: StructuredModelClient | None = None,
        *,
        generator: SuggestionGenerator | None = None,
    ) -> None:
        self.session = session
        self.generator = generator or (
            SuggestionGenerator(client) if client is not None else None
        )

    async def generate(
        self,
        *,
        user_id: str,
        application_id: str,
        job_analysis_id: str | None,
        target: SuggestionTargetInput,
    ) -> ResumeSuggestion:
        if self.generator is None:
            raise ValueError("生成建议需要配置 StructuredModelClient")

        application_view = ApplicationService(self.session).get_application(
            user_id=user_id,
            application_id=application_id,
        )
        analysis_statement = select(JobAnalysis).where(
            JobAnalysis.user_id == user_id,
            JobAnalysis.job_posting_id == application_view.candidate.job_posting_id,
            JobAnalysis.invalidated_at.is_(None),
        )
        if job_analysis_id is not None:
            analysis_statement = analysis_statement.where(JobAnalysis.id == job_analysis_id)
        else:
            analysis_statement = analysis_statement.order_by(
                JobAnalysis.created_at.desc(),
                JobAnalysis.id.desc(),
            )
        analysis = self.session.scalar(analysis_statement)
        if analysis is None:
            raise JobAnalysisNotFoundError(job_analysis_id or "latest")
        job_analysis_id = analysis.id

        posting = application_view.posting
        evidence = self._evidence_records(user_id)
        suggestion_id = generate_suggestion_id()
        input_hash = self._input_hash(
            application_id=application_id,
            job_analysis_id=job_analysis_id,
            target=target,
            evidence=evidence,
        )
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        agent_run = AgentRun(
            id=generate_agent_run_id(),
            user_id=user_id,
            run_type=RUN_TYPE_RESUME_SUGGESTION,
            target_type="resume_suggestion",
            target_id=suggestion_id,
            status=RUN_STATUS_FAILED,
            model=self.generator.client.model_name,
            prompt_version=SUGGESTION_PROMPT_VERSION,
            input_hash=input_hash,
            validation_status=VALIDATION_FAILED,
            started_at=started_at,
        )
        self.session.add(agent_run)
        self.session.flush()

        try:
            response = await self.generator.generate(
                original_text=target.original_text,
                target_type=target.target_type,
                target_label=target.target_label,
                job_title=posting.title,
                company=posting.company,
                evidence=evidence,
            )
        except ModelClientError as error:
            self._finish_failed_run(
                agent_run,
                started_clock=started_clock,
                error=str(error),
                code=error.code,
            )
            self.session.commit()
            raise SuggestionGenerationFailure(
                agent_run_id=agent_run.id,
                code=error.code,
                message=str(error),
            ) from error

        try:
            output = ResumeSuggestionModelOutput.model_validate(response.output)
        except ValidationError as error:
            issues = [item["msg"] for item in error.errors()]
            self._finish_invalid_run(
                agent_run,
                response.output,
                started_clock=started_clock,
                issues=issues,
            )
            self.session.commit()
            raise SuggestionGenerationFailure(
                agent_run_id=agent_run.id,
                code="suggestion_output_invalid",
                message="模型返回的材料建议未通过结构化校验",
                details={"issues": issues},
            ) from error

        issues = validate_suggestion_output(
            user_id=user_id,
            original_text=target.original_text,
            output=output,
            evidence=evidence,
        )
        if issues:
            self._finish_invalid_run(
                agent_run,
                output.model_dump(mode="json"),
                started_clock=started_clock,
                issues=issues,
            )
            self.session.commit()
            raise SuggestionGenerationFailure(
                agent_run_id=agent_run.id,
                code="suggestion_evidence_invalid",
                message="材料建议未通过经历证据校验",
                details={"issues": issues},
            )

        agent_run.status = RUN_STATUS_SUCCEEDED
        agent_run.validation_status = VALIDATION_PASSED
        agent_run.output = output.model_dump(mode="json")
        agent_run.validation_result = {
            "status": VALIDATION_PASSED,
            "issues": [],
        }
        agent_run.model = response.model
        self._finish(agent_run, started_clock)
        suggestion = ResumeSuggestion(
            id=suggestion_id,
            user_id=user_id,
            application_id=application_id,
            job_analysis_id=job_analysis_id,
            target_type=target.target_type,
            target_label=target.target_label,
            original_text=target.original_text,
            suggestion_text=output.suggestion_text,
            evidence_ids=output.evidence_ids,
            status=SuggestionStatus.PENDING.value,
            agent_run_id=agent_run.id,
        )
        self.session.add(suggestion)
        self._add_event(
            user_id=user_id,
            entity_id=application_id,
            event_type="SuggestionCreated",
            payload={
                "suggestion_id": suggestion.id,
                "job_analysis_id": job_analysis_id,
                "target_type": target.target_type,
                "evidence_count": len(output.evidence_ids),
            },
        )
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(suggestion)
        return suggestion

    def list(self, *, user_id: str, application_id: str) -> list[ResumeSuggestion]:
        ApplicationService(self.session).get_application(
            user_id=user_id,
            application_id=application_id,
        )
        return list(
            self.session.scalars(
                select(ResumeSuggestion)
                .where(
                    ResumeSuggestion.user_id == user_id,
                    ResumeSuggestion.application_id == application_id,
                )
                .order_by(
                    ResumeSuggestion.created_at.desc(),
                    ResumeSuggestion.id.desc(),
                )
            ).all()
        )

    def get(self, *, user_id: str, suggestion_id: str) -> ResumeSuggestion:
        suggestion = self.session.scalar(
            select(ResumeSuggestion).where(
                ResumeSuggestion.id == suggestion_id,
                ResumeSuggestion.user_id == user_id,
            )
        )
        if suggestion is None:
            raise SuggestionNotFoundError(suggestion_id)
        return suggestion

    def decide(
        self,
        *,
        user_id: str,
        suggestion_id: str,
        decision: SuggestionDecision,
        final_text: str | None = None,
    ) -> ResumeSuggestion:
        suggestion = self.get(user_id=user_id, suggestion_id=suggestion_id)
        if suggestion.status != SuggestionStatus.PENDING.value:
            raise InvalidSuggestionDecisionError(
                status=suggestion.status,
                decision=decision.value,
            )

        if decision is SuggestionDecision.ACCEPT:
            resolved_text = suggestion.suggestion_text
            status_value = SuggestionStatus.ACCEPTED.value
        elif decision is SuggestionDecision.EDIT:
            resolved_text = (final_text or "").strip()
            if not resolved_text:
                raise ValueError("编辑后接受必须提供 final_text")
            status_value = SuggestionStatus.ACCEPTED.value
        else:
            resolved_text = None
            status_value = SuggestionStatus.REJECTED.value

        suggestion.status = status_value
        suggestion.final_text = resolved_text
        suggestion.updated_at = datetime.now(UTC)
        self._add_event(
            user_id=user_id,
            entity_id=suggestion.application_id,
            event_type="SuggestionDecisionRecorded",
            payload={
                "suggestion_id": suggestion.id,
                "decision": decision.value,
                "status": status_value,
                "final_text_present": resolved_text is not None,
                "final_text_length": len(resolved_text or ""),
                "final_text_sha256": self._text_hash(resolved_text),
            },
        )
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(suggestion)
        return suggestion

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

    @staticmethod
    def _input_hash(
        *,
        application_id: str,
        job_analysis_id: str,
        target: SuggestionTargetInput,
        evidence: list[EvidenceRecord],
    ) -> str:
        payload = {
            "application_id": application_id,
            "job_analysis_id": job_analysis_id,
            "target": target.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _text_hash(value: str | None) -> str | None:
        if value is None:
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _add_event(
        self,
        *,
        user_id: str,
        entity_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        from src.domain.application import DomainEvent, generate_domain_event_id

        self.session.add(
            DomainEvent(
                id=generate_domain_event_id(),
                user_id=user_id,
                entity_type="application",
                entity_id=entity_id,
                event_type=event_type,
                payload=payload,
            )
        )

    @staticmethod
    def _finish(agent_run: AgentRun, started_clock: float) -> None:
        agent_run.finished_at = datetime.now(UTC)
        agent_run.duration_ms = round((perf_counter() - started_clock) * 1000, 2)

    def _finish_failed_run(
        self,
        agent_run: AgentRun,
        *,
        started_clock: float,
        error: str,
        code: str,
    ) -> None:
        agent_run.status = RUN_STATUS_FAILED
        agent_run.validation_status = VALIDATION_FAILED
        agent_run.validation_result = {"status": VALIDATION_FAILED, "code": code}
        agent_run.error = error
        self._finish(agent_run, started_clock)

    def _finish_invalid_run(
        self,
        agent_run: AgentRun,
        output: dict[str, Any],
        *,
        started_clock: float,
        issues: list[str],
    ) -> None:
        agent_run.status = RUN_STATUS_SUCCEEDED
        agent_run.validation_status = VALIDATION_FAILED
        agent_run.output = output
        agent_run.validation_result = {
            "status": VALIDATION_FAILED,
            "issues": issues,
        }
        agent_run.error = "材料建议未通过安全校验"
        self._finish(agent_run, started_clock)


def delete_suggestions_referencing_evidence(
    session: Session,
    *,
    user_id: str,
    evidence_id: str,
) -> int:
    """Delete suggestion rows that cite deleted evidence, retaining audit events."""

    suggestions = list(
        session.scalars(
            select(ResumeSuggestion).where(ResumeSuggestion.user_id == user_id)
        ).all()
    )
    deleted = 0
    for suggestion in suggestions:
        if evidence_id in (suggestion.evidence_ids or []):
            session.delete(suggestion)
            deleted += 1
    return deleted

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.job import JobPosting, RawJobDocument
from src.domain.runs import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCEEDED,
    RUN_TYPE_JD_PARSE,
    VALIDATION_FAILED,
    VALIDATION_PASSED,
    AgentRun,
    JobParseResult,
    generate_agent_run_id,
    generate_parse_result_id,
)
from src.services.jd_parser import JDParser, JDParserError, ParsedJobDescription
from src.services.job_fact_grounding import ground_runtime_facts
from src.services.product_jd_execution import ProductJDExecutionParser
from src.services.product_jd_parser import ProductJDParser
from src.services.staged_jd_parser import StagedJDParser


class JobNotFoundError(LookupError):
    pass


class JDParseFailure(RuntimeError):
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


@dataclass(frozen=True)
class JobParseExecution:
    parse_result: JobParseResult
    agent_run: AgentRun


class JobParseService:
    def __init__(
        self,
        session: Session,
        parser: JDParser | StagedJDParser | ProductJDParser,
    ) -> None:
        self.session = session
        self.parser = parser

    async def parse(self, *, user_id: str, job_id: str) -> JobParseExecution:
        posting = self.session.get(JobPosting, job_id)
        if posting is None:
            raise JobNotFoundError(job_id)

        cached = self.session.scalar(
            select(JobParseResult)
            .where(
                JobParseResult.job_posting_id == posting.id,
                JobParseResult.content_hash == posting.content_hash,
                JobParseResult.schema_version == self.parser.schema_version,
                JobParseResult.parser_version == self.parser.parser_version,
                JobParseResult.prompt_version == self.parser.prompt_version,
                JobParseResult.model == self.parser.model_name,
            )
            .order_by(JobParseResult.created_at.desc())
        )
        if cached is not None:
            return self._cache_hit(cached, user_id=user_id, job_id=job_id)

        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        agent_run = AgentRun(
            id=generate_agent_run_id(),
            user_id=user_id,
            run_type=RUN_TYPE_JD_PARSE,
            target_type="job_posting",
            target_id=job_id,
            status=RUN_STATUS_FAILED,
            model=self.parser.model_name,
            prompt_version=self.parser.prompt_version,
            input_hash=posting.content_hash,
            validation_status=VALIDATION_FAILED,
            started_at=started_at,
        )
        self.session.add(agent_run)
        self.session.flush()

        document = RawJobDocument(
            source_url=posting.source_url,
            source_type=posting.source_type,
            raw_content=posting.raw_content,
            source_metadata={
                "company": posting.company,
                "title": posting.title,
                "job_type": posting.job_type,
                "locations": posting.locations or [],
            },
            retrieved_at=posting.retrieved_at,
            trace_id=posting.trace_id,
        )

        try:
            if isinstance(self.parser, ProductJDExecutionParser):
                checkpoint = self._extraction_checkpoint(user_id, posting, document)

                def save_checkpoint(value):
                    value = {
                        **value,
                        "origin_run_id": value.get("origin_run_id") or agent_run.id,
                    }
                    agent_run.validation_result = {
                        "status": VALIDATION_FAILED,
                        "stage": "extraction_completed",
                        "checkpoint": value,
                    }
                    # Commit before the next network request, including on interruption.
                    # The run remains incomplete and no JobParseResult is published.
                    self.session.commit()

                parsed = await self.parser.parse_with_checkpoint(
                    document,
                    checkpoint=checkpoint,
                    save_checkpoint=save_checkpoint,
                )
            else:
                parsed = await self.parser.parse(document)
        except JDParserError as error:
            self._mark_failed(agent_run, error, started_clock)
            self.session.commit()
            raise JDParseFailure(
                agent_run_id=agent_run.id,
                code=error.code,
                message=str(error),
                details=error.details,
            ) from error

        parse_result = self._save_success(agent_run, posting, parsed, started_clock)
        self.session.commit()
        self.session.refresh(agent_run)
        self.session.refresh(parse_result)
        return JobParseExecution(parse_result=parse_result, agent_run=agent_run)

    def _extraction_checkpoint(self, user_id, posting, document):
        if self.parser.mode != "two_stage":
            return None
        key = self.parser.checkpoint_key(document)
        runs = self.session.scalars(
            select(AgentRun)
            .where(
                AgentRun.user_id == user_id,
                AgentRun.run_type == RUN_TYPE_JD_PARSE,
                AgentRun.target_type == "job_posting",
                AgentRun.target_id == posting.id,
                AgentRun.input_hash == posting.content_hash,
                AgentRun.model == self.parser.model_name,
                AgentRun.prompt_version == self.parser.prompt_version,
            )
            .order_by(AgentRun.started_at.desc())
            .limit(50)
        )
        for run in runs:
            checkpoint = (run.validation_result or {}).get("checkpoint")
            if isinstance(checkpoint, dict) and checkpoint.get("key") == key:
                return checkpoint
        return None

    def _cache_hit(
        self,
        parse_result: JobParseResult,
        *,
        user_id: str,
        job_id: str,
    ) -> JobParseExecution:
        now = datetime.now(UTC)
        agent_run = AgentRun(
            id=generate_agent_run_id(),
            user_id=user_id,
            run_type=RUN_TYPE_JD_PARSE,
            target_type="job_posting",
            target_id=job_id,
            status=RUN_STATUS_SUCCEEDED,
            model=parse_result.model,
            prompt_version=parse_result.prompt_version,
            input_hash=parse_result.content_hash,
            output=parse_result.structured_jd,
            validation_status=VALIDATION_PASSED,
            validation_result={
                "status": VALIDATION_PASSED,
                "cache_hit": True,
                "parse_result_id": parse_result.id,
                "execution": {"model_call_count": 0, "cache_hit": True},
            },
            started_at=now,
            finished_at=now,
            duration_ms=0,
        )
        self.session.add(agent_run)
        self.session.commit()
        self.session.refresh(agent_run)
        self.session.refresh(parse_result)
        return JobParseExecution(parse_result=parse_result, agent_run=agent_run)

    def _save_success(
        self,
        agent_run: AgentRun,
        posting: JobPosting,
        parsed: ParsedJobDescription,
        started_clock: float,
    ) -> JobParseResult:
        structured_output = ground_runtime_facts(parsed.structured_jd, posting.raw_content).model_dump(mode="json")
        parse_result = JobParseResult(
            id=generate_parse_result_id(),
            job_posting_id=posting.id,
            content_hash=parsed.input_hash,
            schema_version=parsed.schema_version,
            parser_version=parsed.parser_version,
            prompt_version=parsed.prompt_version,
            model=parsed.model,
            structured_jd=structured_output,
        )
        self.session.add(parse_result)

        agent_run.status = RUN_STATUS_SUCCEEDED
        agent_run.model = parsed.model
        agent_run.output = structured_output
        agent_run.validation_status = VALIDATION_PASSED
        agent_run.validation_result = {
            **(agent_run.validation_result or {}),
            "status": VALIDATION_PASSED,
            "stage": "completed",
            "schema_version": parsed.schema_version,
            "execution": getattr(parsed, "diagnostics", {}),
        }
        self._finish(agent_run, started_clock)
        return parse_result

    @staticmethod
    def _mark_failed(
        agent_run: AgentRun,
        error: JDParserError,
        started_clock: float,
    ) -> None:
        agent_run.status = RUN_STATUS_FAILED
        agent_run.validation_status = VALIDATION_FAILED
        agent_run.validation_result = {
            **(agent_run.validation_result or {}),
            "status": VALIDATION_FAILED,
            "stage": error.details.get("stage"),
            "code": error.code,
            "details": error.details,
        }
        agent_run.error = str(error)
        JobParseService._finish(agent_run, started_clock)

    @staticmethod
    def _finish(agent_run: AgentRun, started_clock: float) -> None:
        agent_run.finished_at = datetime.now(UTC)
        agent_run.duration_ms = round((perf_counter() - started_clock) * 1000, 2)

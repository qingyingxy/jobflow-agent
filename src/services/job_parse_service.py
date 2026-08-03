from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

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
    def __init__(self, session: Session, parser: JDParser) -> None:
        self.session = session
        self.parser = parser

    async def parse(self, *, user_id: str, job_id: str) -> JobParseExecution:
        posting = self.session.get(JobPosting, job_id)
        if posting is None:
            raise JobNotFoundError(job_id)

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
            retrieved_at=posting.retrieved_at,
            trace_id=posting.trace_id,
        )

        try:
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

    def _save_success(
        self,
        agent_run: AgentRun,
        posting: JobPosting,
        parsed: ParsedJobDescription,
        started_clock: float,
    ) -> JobParseResult:
        structured_output = parsed.structured_jd.model_dump(mode="json")
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
            "status": VALIDATION_PASSED,
            "schema_version": parsed.schema_version,
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
            "status": VALIDATION_FAILED,
            "code": error.code,
            "details": error.details,
        }
        agent_run.error = str(error)
        JobParseService._finish(agent_run, started_clock)

    @staticmethod
    def _finish(agent_run: AgentRun, started_clock: float) -> None:
        agent_run.finished_at = datetime.now(UTC)
        agent_run.duration_ms = round((perf_counter() - started_clock) * 1000, 2)

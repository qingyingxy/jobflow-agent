from fastapi import APIRouter, HTTPException, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import JobParseResponse, JobPostingRead, JobTextImportRequest
from src.config import get_settings
from src.infrastructure.llm_client import (
    ModelClientError,
    create_structured_model_client,
)
from src.services.jd_parser import JDParser
from src.services.job_parse_service import (
    JDParseFailure,
    JobNotFoundError,
    JobParseService,
)
from src.services.job_service import JobImportService

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post(
    "/jobs/import-text",
    response_model=JobPostingRead,
    status_code=status.HTTP_201_CREATED,
)
def import_job_text(
    payload: JobTextImportRequest,
    session: DatabaseSession,
) -> JobPostingRead:
    return JobImportService(session).import_text(
        raw_content=payload.raw_content,
        source_url=payload.source_url,
        source_type=payload.source_type,
        company=payload.company,
        title=payload.title,
    )


@router.get("/jobs/{job_id}", response_model=JobPostingRead)
def read_job(job_id: str, session: DatabaseSession) -> JobPostingRead:
    posting = JobImportService(session).get(job_id)
    if posting is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return posting


@router.post(
    "/jobs/{job_id}/parse",
    response_model=JobParseResponse,
)
async def parse_job(
    job_id: str,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> JobParseResponse:
    try:
        settings = get_settings()
        client = create_structured_model_client(settings)
    except ModelClientError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code, "message": str(error)},
        ) from error

    parser = JDParser(
        client,
        prompt_version=settings.prompt_version,
        parser_version=settings.parser_version,
    )
    try:
        execution = await JobParseService(session, parser).parse(
            user_id=user_id,
            job_id=job_id,
        )
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在") from error
    except JDParseFailure as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": error.code,
                "message": str(error),
                "agent_run_id": error.agent_run_id,
                "details": error.details,
            },
        ) from error

    result = execution.parse_result
    return JobParseResponse(
        job_id=result.job_posting_id,
        parse_result_id=result.id,
        agent_run_id=execution.agent_run.id,
        model=result.model,
        schema_version=result.schema_version,
        parser_version=result.parser_version,
        prompt_version=result.prompt_version,
        structured_jd=result.structured_jd,
    )

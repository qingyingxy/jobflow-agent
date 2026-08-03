from fastapi import APIRouter, HTTPException, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import (
    JobAnalysisResponse,
    JobParseResponse,
    JobPostingRead,
    JobTextImportRequest,
    JobURLImportRequest,
)
from src.config import get_settings
from src.domain.analysis import AnalysisRisk
from src.domain.eligibility import EligibilityResult
from src.domain.job import StructuredJobDescription
from src.domain.matching import MatchScore, RequirementMatch
from src.infrastructure.llm_client import (
    ModelClientError,
    create_structured_model_client,
)
from src.services.evidence_matcher import EvidenceMatcher
from src.services.jd_analysis_service import (
    AnalysisContentChangedError,
    JDAnalysisFailure,
    JDAnalysisService,
)
from src.services.jd_parser import JDParser
from src.services.job_parse_service import (
    JDParseFailure,
    JobNotFoundError,
    JobParseService,
)
from src.services.job_service import JobImportService
from src.services.url_reader import (
    SafeHTTPReader,
    URLFetchTimeout,
    URLReaderError,
    URLSafetyError,
    parse_html_document,
)

router = APIRouter(prefix="/api", tags=["jobs"])


def create_http_reader() -> SafeHTTPReader:
    return SafeHTTPReader()


def _url_reader_error(error: URLReaderError) -> HTTPException:
    if isinstance(error, URLSafetyError):
        response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, URLFetchTimeout):
        response_status = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        response_status = status.HTTP_502_BAD_GATEWAY
    return HTTPException(
        status_code=response_status,
        detail={"code": error.code, "message": str(error)},
    )


def _analysis_response(
    *,
    analysis,
    posting,
    parse_result,
    agent_run_ids: list[str],
) -> JobAnalysisResponse:
    return JobAnalysisResponse(
        analysis_id=analysis.id,
        job=JobPostingRead.model_validate(posting),
        parse_result_id=analysis.parse_result_id,
        analysis_version=analysis.analysis_version,
        agent_run_ids=agent_run_ids,
        structured_jd=StructuredJobDescription.model_validate(
            parse_result.structured_jd
        ),
        eligibility=EligibilityResult.model_validate(analysis.eligibility),
        matches=[RequirementMatch.model_validate(item) for item in analysis.matches],
        score=MatchScore.model_validate(analysis.score),
        risks=[AnalysisRisk.model_validate(item) for item in analysis.risks],
        missing_information=analysis.missing_information,
        created_at=analysis.created_at,
        invalidated_at=analysis.invalidated_at,
    )


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


@router.post(
    "/jobs/import-url",
    response_model=JobPostingRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_job_url(
    payload: JobURLImportRequest,
    session: DatabaseSession,
) -> JobPostingRead:
    try:
        fetched = await create_http_reader().fetch(payload.source_url)
    except URLReaderError as error:
        raise _url_reader_error(error) from error

    document = parse_html_document(fetched.body.decode("utf-8", errors="replace"))
    if len(document.text) < 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "job_content_too_short",
                "message": "页面中没有提取到足够的岗位正文",
            },
        )
    return JobImportService(session).import_text(
        raw_content=document.text,
        source_url=fetched.final_url,
        source_type="generic_html",
        company=payload.company or document.company,
        title=payload.title or document.title,
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


@router.post(
    "/jobs/{job_id}/analyze",
    response_model=JobAnalysisResponse,
)
async def analyze_job(
    job_id: str,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> JobAnalysisResponse:
    settings = get_settings()
    try:
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
    matcher = EvidenceMatcher(client)
    try:
        execution = await JDAnalysisService(
            session,
            parser=parser,
            matcher=matcher,
        ).analyze(user_id=user_id, job_id=job_id)
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "岗位不存在"},
        ) from error
    except JDAnalysisFailure as error:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if error.code in {"model_timeout", "model_unavailable", "model_error"}
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=response_status,
            detail={
                "code": error.code,
                "message": str(error),
                "agent_run_id": error.agent_run_id,
                "stage": error.stage,
                "details": error.details,
            },
        ) from error

    return _analysis_response(
        analysis=execution.analysis,
        posting=execution.posting,
        parse_result=execution.parse_result,
        agent_run_ids=execution.agent_run_ids,
    )


@router.get(
    "/jobs/{job_id}/analysis",
    response_model=JobAnalysisResponse,
)
def read_latest_analysis(
    job_id: str,
    session: DatabaseSession,
    user_id: CurrentUserId,
) -> JobAnalysisResponse:
    try:
        view = JDAnalysisService(session).latest(user_id=user_id, job_id=job_id)
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "岗位不存在"},
        ) from error
    except AnalysisContentChangedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "analysis_content_changed",
                "message": "岗位原文或解析版本已经变化，请重新分析",
            },
        ) from error
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "analysis_not_found",
                "message": "当前用户还没有可用的岗位分析结果",
            },
        )
    return _analysis_response(
        analysis=view.analysis,
        posting=view.posting,
        parse_result=view.parse_result,
        agent_run_ids=[],
    )

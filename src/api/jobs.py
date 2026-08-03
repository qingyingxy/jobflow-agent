from fastapi import APIRouter, HTTPException, status

from src.api.dependencies import DatabaseSession
from src.api.schemas import JobPostingRead, JobTextImportRequest
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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.jobs import _analysis_response
from src.api.timestamps import as_utc
from src.domain.analysis import JobAnalysis
from src.domain.job import JobPosting, JobRequirement, StructuredJobDescription
from src.domain.job_correction import JobCorrection
from src.domain.runs import JobParseResult
from src.services.jd_analysis_service import JDAnalysisService
from src.services.job_correction_service import (
    compile_correction,
    effective_structure,
    latest_correction,
)

router = APIRouter(prefix="/api/jobs", tags=["job-corrections"])


class CorrectionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    parse_result_id: str
    expected_revision: int = Field(ge=0)
    requirements: list[JobRequirement] | None = Field(default=None, max_length=50)
    reason: str = Field(min_length=1, max_length=500)


def owned_parse(session, user_id, job_id, parse_id=None):
    statement = select(JobParseResult).join(JobAnalysis, JobAnalysis.parse_result_id == JobParseResult.id).where(
        JobAnalysis.user_id == user_id, JobAnalysis.job_posting_id == job_id,
    )
    result = session.scalar(statement.order_by(JobAnalysis.created_at.desc()).limit(1))
    posting = session.get(JobPosting, job_id)
    if result is None or posting is None:
        raise HTTPException(status_code=404, detail="请先完成当前用户的岗位分析")
    if parse_id and result.id != parse_id:
        raise HTTPException(status_code=409, detail="岗位解析已变化，请重新打开后纠错")
    if result.content_hash != posting.content_hash:
        raise HTTPException(status_code=409, detail="岗位原文已变化，请重新分析后纠错")
    return result, posting


@router.get("/{job_id}/corrections")
def read_corrections(job_id: str, user_id: CurrentUserId, session: DatabaseSession):
    parsed, posting = owned_parse(session, user_id, job_id)
    current = latest_correction(session, user_id, job_id)
    rows = session.scalars(select(JobCorrection).where(
        JobCorrection.user_id == user_id, JobCorrection.job_posting_id == job_id,
    ).order_by(JobCorrection.revision.desc())).all()
    return {
        "parse_result_id": parsed.id, "revision": current.revision if current else 0,
        "raw_content": posting.raw_content,
        "requirements": effective_structure(session, user_id, parsed).model_dump(mode="json")["requirements"] or [],
        "history": [{"revision": r.revision, "reason": r.reason, "created_at": as_utc(r.created_at),
                     "restored": r.structured_jd is None,
                     "before": (rows[i + 1].requirements if i + 1 < len(rows) and rows[i + 1].parse_result_id == r.parse_result_id else None),
                     "requirements": r.requirements} for i, r in enumerate(rows)],
    }


@router.put("/{job_id}/corrections")
async def save_correction(job_id: str, payload: CorrectionWrite, user_id: CurrentUserId, session: DatabaseSession):
    parsed, posting = owned_parse(session, user_id, job_id, payload.parse_result_id)
    current = latest_correction(session, user_id, job_id)
    revision = current.revision if current else 0
    if revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="纠错记录已变化，请重新打开后修改")
    try:
        structured = None if payload.requirements is None else compile_correction(
            StructuredJobDescription.model_validate(parsed.structured_jd), payload.requirements, posting.raw_content,
        ).model_dump(mode="json")
        session.add(JobCorrection(
            user_id=user_id, job_posting_id=job_id, parse_result_id=parsed.id,
            content_hash=posting.content_hash, revision=revision + 1,
            requirements=[r.model_dump(mode="json") for r in payload.requirements] if payload.requirements is not None else None,
            structured_jd=structured, reason=payload.reason,
        ))
        session.flush()
        execution = await JDAnalysisService(session).analyze(user_id=user_id, job_id=job_id, saved_parse=parsed)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="纠错记录已变化，请刷新后重试") from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _analysis_response(analysis=execution.analysis, posting=posting, parse_result=parsed, agent_run_ids=[])

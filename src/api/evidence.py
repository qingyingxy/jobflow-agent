from fastapi import APIRouter, HTTPException, Query, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import EvidenceCreate, EvidenceRead, EvidenceUpdate
from src.services.evidence_service import EvidenceService

router = APIRouter(prefix="/api", tags=["evidence"])


@router.post("/evidence", response_model=EvidenceRead, status_code=status.HTTP_201_CREATED)
def create_evidence(
    payload: EvidenceCreate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> EvidenceRead:
    return EvidenceService(session).create(user_id, payload.model_dump())


@router.get("/evidence", response_model=list[EvidenceRead])
def list_evidence(
    user_id: CurrentUserId,
    session: DatabaseSession,
    evidence_type: str | None = Query(default=None, alias="type"),
    search: str | None = Query(default=None, min_length=1, max_length=100),
) -> list[EvidenceRead]:
    return EvidenceService(session).list(user_id, evidence_type, search)


@router.get("/evidence/{evidence_id}", response_model=EvidenceRead)
def read_evidence(
    evidence_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> EvidenceRead:
    item = EvidenceService(session).get(user_id, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="经历证据不存在")
    return item


@router.patch("/evidence/{evidence_id}", response_model=EvidenceRead)
def update_evidence(
    evidence_id: str,
    payload: EvidenceUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> EvidenceRead:
    item = EvidenceService(session).update(
        user_id,
        evidence_id,
        payload.model_dump(exclude_unset=True),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="经历证据不存在")
    return item


@router.delete("/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evidence(
    evidence_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> None:
    deleted = EvidenceService(session).delete(user_id, evidence_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="经历证据不存在")

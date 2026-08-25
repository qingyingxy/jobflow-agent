from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.application import (
    APPLICATION_TRANSITIONS,
    CANDIDATE_TRANSITIONS,
    ApplicationStatus,
    CandidateJob,
    CandidateStatus,
    DomainEvent,
    generate_application_id,
    generate_candidate_id,
    generate_domain_event_id,
)
from src.domain.application import (
    Application as ApplicationModel,
)
from src.domain.job import JobPosting


class JobPostingNotFoundError(LookupError):
    pass


class CandidateNotFoundError(LookupError):
    pass


class ApplicationNotFoundError(LookupError):
    pass


class InvalidTransitionError(RuntimeError):
    def __init__(
        self,
        *,
        entity: str,
        current: str,
        target: str,
        allowed: list[str],
    ) -> None:
        self.entity = entity
        self.current = current
        self.target = target
        self.allowed = allowed
        super().__init__(f"{entity} 不允许从 {current} 转换到 {target}")


@dataclass(frozen=True)
class CandidateView:
    candidate: CandidateJob
    posting: JobPosting


@dataclass(frozen=True)
class ApplicationView:
    application: ApplicationModel
    candidate: CandidateJob
    posting: JobPosting
    events: list[DomainEvent]


@dataclass(frozen=True)
class ApplicationPreparation:
    view: ApplicationView
    created: bool


class ApplicationService:
    """Own candidate/application state transitions and their audit events."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_candidate(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        initial_status: CandidateStatus = CandidateStatus.SAVED,
        commit: bool = True,
    ) -> CandidateView:
        posting = self.session.get(JobPosting, job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(job_posting_id)

        existing = self.session.execute(
            select(CandidateJob)
            .where(
                CandidateJob.user_id == user_id,
                CandidateJob.job_posting_id == job_posting_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            return CandidateView(candidate=existing, posting=posting)

        candidate = CandidateJob(
            id=generate_candidate_id(),
            user_id=user_id,
            job_posting_id=job_posting_id,
            status=initial_status.value,
        )
        self.session.add(candidate)
        try:
            self._add_event(
                user_id=user_id,
                entity_type="candidate",
                entity_id=candidate.id,
                event_type=(
                    "CandidateDiscovered"
                    if initial_status is CandidateStatus.DISCOVERED
                    else "CandidateSaved"
                ),
                payload={
                    "job_posting_id": posting.id,
                    "company": posting.company,
                    "title": posting.title,
                    "status": initial_status.value,
                },
            )
            if commit:
                self._commit()
            else:
                self.session.flush()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(candidate)
        return CandidateView(candidate=candidate, posting=posting)

    def list_candidates(
        self,
        *,
        user_id: str,
        status: CandidateStatus | None = None,
    ) -> list[CandidateView]:
        statement = (
            select(CandidateJob, JobPosting)
            .join(JobPosting, JobPosting.id == CandidateJob.job_posting_id)
            .where(CandidateJob.user_id == user_id)
            .order_by(CandidateJob.updated_at.desc(), CandidateJob.id.desc())
        )
        if status is not None:
            statement = statement.where(CandidateJob.status == status.value)
        rows = self.session.execute(statement).all()
        return [
            CandidateView(candidate=candidate, posting=posting)
            for candidate, posting in rows
        ]

    def get_candidate(self, *, user_id: str, candidate_id: str) -> CandidateView:
        row = self.session.execute(
            select(CandidateJob, JobPosting)
            .join(JobPosting, JobPosting.id == CandidateJob.job_posting_id)
            .where(
                CandidateJob.id == candidate_id,
                CandidateJob.user_id == user_id,
            )
        ).one_or_none()
        if row is None:
            raise CandidateNotFoundError(candidate_id)
        candidate, posting = row
        return CandidateView(candidate=candidate, posting=posting)

    def transition_candidate(
        self,
        *,
        user_id: str,
        candidate_id: str,
        target_status: CandidateStatus,
    ) -> CandidateView:
        view = self.get_candidate(user_id=user_id, candidate_id=candidate_id)
        current_status = CandidateStatus(view.candidate.status)
        allowed = CANDIDATE_TRANSITIONS[current_status]
        if target_status not in allowed:
            raise InvalidTransitionError(
                entity="CandidateJob",
                current=current_status.value,
                target=target_status.value,
                allowed=sorted(item.value for item in allowed),
            )

        view.candidate.status = target_status.value
        try:
            self._add_event(
                user_id=user_id,
                entity_type="candidate",
                entity_id=view.candidate.id,
                event_type="CandidateStatusChanged",
                payload={
                    "job_posting_id": view.posting.id,
                    "from_status": current_status.value,
                    "to_status": target_status.value,
                },
            )
            self._commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(view.candidate)
        return view

    def prepare_application(
        self,
        *,
        user_id: str,
        candidate_id: str,
    ) -> ApplicationPreparation:
        candidate_view = self.get_candidate(
            user_id=user_id,
            candidate_id=candidate_id,
        )
        existing = self.session.scalar(
            select(ApplicationModel).where(
                ApplicationModel.candidate_job_id == candidate_id
            )
        )
        if existing is not None:
            return ApplicationPreparation(
                view=self._application_view(existing, candidate_view),
                created=False,
            )

        current_status = CandidateStatus(candidate_view.candidate.status)
        allowed = CANDIDATE_TRANSITIONS[current_status]
        if CandidateStatus.CONVERTED not in allowed:
            raise InvalidTransitionError(
                entity="CandidateJob",
                current=current_status.value,
                target=CandidateStatus.CONVERTED.value,
                allowed=sorted(item.value for item in allowed),
            )

        application = ApplicationModel(
            id=generate_application_id(),
            candidate_job_id=candidate_view.candidate.id,
            status=ApplicationStatus.PREPARING.value,
        )
        candidate_view.candidate.status = CandidateStatus.CONVERTED.value
        self.session.add(application)
        try:
            self._add_event(
                user_id=user_id,
                entity_type="application",
                entity_id=application.id,
                event_type="ApplicationCreated",
                payload={
                    "job_posting_id": candidate_view.posting.id,
                    "candidate_job_id": candidate_view.candidate.id,
                    "candidate_status_from": current_status.value,
                    "candidate_status_to": CandidateStatus.CONVERTED.value,
                    "application_status": ApplicationStatus.PREPARING.value,
                },
            )
            self._commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(application)
        return ApplicationPreparation(
            view=self._application_view(application, candidate_view),
            created=True,
        )

    def list_applications(self, *, user_id: str) -> list[ApplicationView]:
        rows = self.session.execute(
            select(ApplicationModel, CandidateJob, JobPosting)
            .join(
                CandidateJob,
                CandidateJob.id == ApplicationModel.candidate_job_id,
            )
            .join(JobPosting, JobPosting.id == CandidateJob.job_posting_id)
            .where(CandidateJob.user_id == user_id)
            .order_by(ApplicationModel.updated_at.desc(), ApplicationModel.id.desc())
        ).all()
        return [
            ApplicationView(
                application=application,
                candidate=candidate,
                posting=posting,
                events=self._events(user_id=user_id, entity_id=application.id),
            )
            for application, candidate, posting in rows
        ]

    def get_application(
        self,
        *,
        user_id: str,
        application_id: str,
    ) -> ApplicationView:
        row = self.session.execute(
            select(ApplicationModel, CandidateJob, JobPosting)
            .join(
                CandidateJob,
                CandidateJob.id == ApplicationModel.candidate_job_id,
            )
            .join(JobPosting, JobPosting.id == CandidateJob.job_posting_id)
            .where(
                ApplicationModel.id == application_id,
                CandidateJob.user_id == user_id,
            )
        ).one_or_none()
        if row is None:
            raise ApplicationNotFoundError(application_id)
        application, candidate, posting = row
        return ApplicationView(
            application=application,
            candidate=candidate,
            posting=posting,
            events=self._events(user_id=user_id, entity_id=application.id),
        )

    def transition_application(
        self,
        *,
        user_id: str,
        application_id: str,
        target_status: ApplicationStatus,
        next_action: str | None = None,
    ) -> ApplicationView:
        view = self.get_application(
            user_id=user_id,
            application_id=application_id,
        )
        current_status = ApplicationStatus(view.application.status)
        allowed = APPLICATION_TRANSITIONS[current_status]
        if target_status not in allowed:
            raise InvalidTransitionError(
                entity="Application",
                current=current_status.value,
                target=target_status.value,
                allowed=sorted(item.value for item in allowed),
            )

        view.application.status = target_status.value
        if target_status in {
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }:
            view.application.next_action = None
        elif next_action is not None:
            view.application.next_action = next_action
        try:
            self._add_event(
                user_id=user_id,
                entity_type="application",
                entity_id=view.application.id,
                event_type="ApplicationStatusChanged",
                payload={
                    "job_posting_id": view.posting.id,
                    "from_status": current_status.value,
                    "to_status": target_status.value,
                    "next_action": view.application.next_action,
                },
            )
            self._commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(view.application)
        return self.get_application(
            user_id=user_id,
            application_id=view.application.id,
        )

    def list_events(self, *, user_id: str, application_id: str) -> list[DomainEvent]:
        self.get_application(user_id=user_id, application_id=application_id)
        return self._events(user_id=user_id, entity_id=application_id)

    def _application_view(
        self,
        application: ApplicationModel,
        candidate_view: CandidateView,
    ) -> ApplicationView:
        return ApplicationView(
            application=application,
            candidate=candidate_view.candidate,
            posting=candidate_view.posting,
            events=self._events(
                user_id=candidate_view.candidate.user_id,
                entity_id=application.id,
            ),
        )

    def _events(self, *, user_id: str, entity_id: str) -> list[DomainEvent]:
        return list(
            self.session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.user_id == user_id,
                    DomainEvent.entity_type == "application",
                    DomainEvent.entity_id == entity_id,
                )
                .order_by(DomainEvent.created_at.asc(), DomainEvent.id.asc())
            ).all()
        )

    def _add_event(
        self,
        *,
        user_id: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> DomainEvent:
        event = DomainEvent(
            id=generate_domain_event_id(),
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
        )
        self.session.add(event)
        return event

    def _commit(self) -> None:
        self.session.commit()

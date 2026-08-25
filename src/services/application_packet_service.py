from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.domain.analysis import ANALYSIS_VERSION, JobAnalysis
from src.domain.application import DomainEvent, generate_domain_event_id
from src.domain.application_packet import (
    ApplicationPacket,
    PacketDecision,
    PacketDecisionType,
    PacketRevision,
    PacketStatus,
    generate_packet_decision_id,
    generate_packet_id,
    generate_packet_revision_id,
)
from src.domain.materials import (
    AnswerBankEntry,
    AnswerSensitivity,
    CandidatePrivateProfile,
    ResumeAsset,
    ResumeVersion,
)
from src.domain.models import EvidenceItem
from src.domain.runs import JobParseResult
from src.services.application_service import (
    ApplicationNotFoundError,
    ApplicationService,
)
from src.services.candidate_material_service import CandidateMaterialService

ActorType = Literal["user", "agent"]


class ApplicationPacketError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ApplicationPacketNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class PacketRevisionView:
    revision: PacketRevision
    decisions: list[PacketDecision]
    source_changed: bool
    source_change_codes: list[str]


@dataclass(frozen=True)
class ApplicationPacketView:
    packet: ApplicationPacket
    revisions: list[PacketRevisionView]

    @property
    def current_revision(self) -> PacketRevisionView:
        for revision in self.revisions:
            if revision.revision.id == self.packet.current_revision_id:
                return revision
        raise RuntimeError("投递包当前版本不存在")


@dataclass(frozen=True)
class PacketGeneration:
    view: ApplicationPacketView
    created: bool


@dataclass(frozen=True)
class _FrozenSources:
    job_snapshot: dict[str, Any]
    analysis_snapshot: dict[str, Any]
    profile_snapshot: dict[str, Any]
    resume_snapshot: dict[str, Any]
    evidence_snapshots: list[dict[str, Any]]
    answer_snapshots: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    confirmation_items: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    source_fingerprint: str


class ApplicationPacketService:
    """Create frozen application material revisions and approve them atomically."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def generate(
        self,
        *,
        user_id: str,
        application_id: str,
        actor_type: ActorType,
        resume_version_id: str | None = None,
        evidence_ids: list[str] | None = None,
        answer_entry_ids: list[str] | None = None,
        open_questions: list[dict[str, Any]] | None = None,
    ) -> PacketGeneration:
        application_view = ApplicationService(self.session).get_application(
            user_id=user_id,
            application_id=application_id,
        )
        existing = self.session.scalar(
            select(ApplicationPacket).where(
                ApplicationPacket.application_id == application_id,
                ApplicationPacket.user_id == user_id,
            )
        )
        if existing is not None:
            return PacketGeneration(view=self.get(user_id=user_id, packet_id=existing.id), created=False)

        analysis, parse_result = self._latest_analysis(
            user_id=user_id,
            job_posting_id=application_view.posting.id,
            content_hash=application_view.posting.content_hash,
        )
        selected_resume_id = resume_version_id or self._default_resume_id(user_id)
        selected_evidence_ids = (
            evidence_ids
            if evidence_ids is not None
            else self._analysis_evidence_ids(analysis)
        )
        sources = self._freeze_sources(
            user_id=user_id,
            posting=application_view.posting,
            analysis=analysis,
            parse_result=parse_result,
            resume_version_id=selected_resume_id,
            evidence_ids=selected_evidence_ids,
            answer_entry_ids=answer_entry_ids or [],
            open_questions=open_questions or [],
            actor_type=actor_type,
        )
        packet_id = generate_packet_id()
        revision_id = generate_packet_revision_id()
        revision = self._revision_from_sources(
            revision_id=revision_id,
            packet_id=packet_id,
            user_id=user_id,
            application_id=application_id,
            job_posting_id=application_view.posting.id,
            revision_number=1,
            supersedes_revision_id=None,
            analysis=analysis,
            resume_version_id=selected_resume_id,
            actor_type=actor_type,
            sources=sources,
        )
        packet = ApplicationPacket(
            id=packet_id,
            user_id=user_id,
            application_id=application_id,
            job_posting_id=application_view.posting.id,
            current_revision_id=revision_id,
            status=PacketStatus.DRAFT.value,
        )
        self.session.add_all([packet, revision])
        self._add_event(
            user_id=user_id,
            application_id=application_id,
            event_type="ApplicationPacketCreated",
            payload={
                "packet_id": packet.id,
                "packet_revision_id": revision.id,
                "revision_number": 1,
                "status": PacketStatus.DRAFT.value,
            },
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(ApplicationPacket).where(
                    ApplicationPacket.application_id == application_id,
                    ApplicationPacket.user_id == user_id,
                )
            )
            if existing is None:
                raise
            return PacketGeneration(
                view=self.get(user_id=user_id, packet_id=existing.id),
                created=False,
            )
        return PacketGeneration(
            view=self.get(user_id=user_id, packet_id=packet.id),
            created=True,
        )

    def list(self, *, user_id: str) -> list[ApplicationPacketView]:
        packets = list(
            self.session.scalars(
                select(ApplicationPacket)
                .where(ApplicationPacket.user_id == user_id)
                .order_by(
                    ApplicationPacket.updated_at.desc(),
                    ApplicationPacket.id.desc(),
                )
            ).all()
        )
        return [self._view(packet) for packet in packets]

    def get(self, *, user_id: str, packet_id: str) -> ApplicationPacketView:
        packet = self.session.scalar(
            select(ApplicationPacket).where(
                ApplicationPacket.id == packet_id,
                ApplicationPacket.user_id == user_id,
            )
        )
        if packet is None:
            raise ApplicationPacketNotFoundError(packet_id)
        return self._view(packet)

    def get_revision(
        self, *, user_id: str, revision_id: str
    ) -> PacketRevisionView:
        revision = self._revision(user_id=user_id, revision_id=revision_id)
        return self._revision_view(revision)

    def edit_revision(
        self,
        *,
        user_id: str,
        revision_id: str,
        actor_type: ActorType,
        resume_version_id: str | None | object = ...,
        evidence_ids: list[str] | None = None,
        answer_entry_ids: list[str] | None = None,
        open_questions: list[dict[str, Any]] | None = None,
    ) -> ApplicationPacketView:
        revision = self._revision(user_id=user_id, revision_id=revision_id)
        if PacketStatus(revision.status) in {
            PacketStatus.APPROVED,
            PacketStatus.SUPERSEDED,
        }:
            raise ApplicationPacketError(
                code="approved_revision_immutable",
                message="已批准或已失效的投递包版本不可原地修改",
            )
        packet = self._packet(user_id=user_id, packet_id=revision.packet_id)
        if packet.current_revision_id != revision.id:
            raise ApplicationPacketError(
                code="revision_not_current",
                message="只能编辑当前投递包版本",
            )

        selected_resume_id = (
            revision.resume_version_id
            if resume_version_id is ...
            else resume_version_id
        )
        selected_evidence_ids = (
            [item["id"] for item in revision.evidence_snapshots]
            if evidence_ids is None
            else evidence_ids
        )
        selected_answer_ids = (
            [item["id"] for item in revision.form_answer_snapshots]
            if answer_entry_ids is None
            else answer_entry_ids
        )
        selected_open_questions = (
            revision.open_questions if open_questions is None else open_questions
        )
        application_view = ApplicationService(self.session).get_application(
            user_id=user_id,
            application_id=revision.application_id,
        )
        analysis, parse_result = self._latest_analysis(
            user_id=user_id,
            job_posting_id=application_view.posting.id,
            content_hash=application_view.posting.content_hash,
        )
        sources = self._freeze_sources(
            user_id=user_id,
            posting=application_view.posting,
            analysis=analysis,
            parse_result=parse_result,
            resume_version_id=selected_resume_id,
            evidence_ids=selected_evidence_ids,
            answer_entry_ids=selected_answer_ids,
            open_questions=selected_open_questions,
            actor_type=actor_type,
        )
        self._apply_sources(
            revision,
            sources=sources,
            analysis=analysis,
            resume_version_id=selected_resume_id,
        )
        revision.status = PacketStatus.DRAFT.value
        revision.submitted_for_review_at = None
        packet.status = PacketStatus.DRAFT.value
        packet.updated_at = datetime.now(UTC)
        self._add_event(
            user_id=user_id,
            application_id=revision.application_id,
            event_type="ApplicationPacketDraftUpdated",
            payload={
                "packet_id": packet.id,
                "packet_revision_id": revision.id,
                "revision_number": revision.revision_number,
                "status": PacketStatus.DRAFT.value,
            },
        )
        self.session.commit()
        return self.get(user_id=user_id, packet_id=packet.id)

    def submit_for_review(
        self, *, user_id: str, revision_id: str
    ) -> ApplicationPacketView:
        revision = self._revision(user_id=user_id, revision_id=revision_id)
        packet = self._packet(user_id=user_id, packet_id=revision.packet_id)
        if packet.current_revision_id != revision.id:
            raise ApplicationPacketError(
                code="revision_not_current", message="只能提交当前投递包版本"
            )
        if revision.status == PacketStatus.NEEDS_REVIEW.value:
            return self.get(user_id=user_id, packet_id=packet.id)
        if revision.status != PacketStatus.DRAFT.value:
            raise ApplicationPacketError(
                code="invalid_packet_transition",
                message=f"投递包版本不能从 {revision.status} 进入审核",
            )
        drift = self._source_change_codes(revision)
        if drift:
            raise ApplicationPacketError(
                code="packet_sources_changed",
                message="投递包来源已经变化，请刷新当前草稿",
                details={"source_change_codes": drift},
            )
        now = datetime.now(UTC)
        revision.status = PacketStatus.NEEDS_REVIEW.value
        revision.submitted_for_review_at = now
        revision.updated_at = now
        packet.status = PacketStatus.NEEDS_REVIEW.value
        packet.updated_at = now
        self._add_event(
            user_id=user_id,
            application_id=revision.application_id,
            event_type="ApplicationPacketReviewRequested",
            payload={
                "packet_id": packet.id,
                "packet_revision_id": revision.id,
                "revision_number": revision.revision_number,
                "status": PacketStatus.NEEDS_REVIEW.value,
                "blocker_count": len(revision.blockers or []),
            },
        )
        self.session.commit()
        return self.get(user_id=user_id, packet_id=packet.id)

    def approve(
        self,
        *,
        user_id: str,
        revision_id: str,
        actor_type: ActorType,
        confirmed: bool,
    ) -> ApplicationPacketView:
        if actor_type != "user" or not confirmed:
            raise ApplicationPacketError(
                code="user_approval_required",
                message="只有当前用户明确确认后才能批准投递包",
            )
        revision = self._revision(user_id=user_id, revision_id=revision_id)
        packet = self._packet(user_id=user_id, packet_id=revision.packet_id)
        if revision.status == PacketStatus.APPROVED.value:
            return self.get(user_id=user_id, packet_id=packet.id)
        if packet.current_revision_id != revision.id:
            raise ApplicationPacketError(
                code="revision_not_current", message="只能批准当前投递包版本"
            )
        if revision.status != PacketStatus.NEEDS_REVIEW.value:
            raise ApplicationPacketError(
                code="invalid_packet_transition",
                message="投递包必须先进入待审核状态",
            )
        if revision.payload_hash != self._payload_hash(revision):
            raise ApplicationPacketError(
                code="packet_integrity_failed",
                message="投递包冻结内容完整性校验失败",
            )
        source_change_codes = self._source_change_codes(revision)
        if source_change_codes:
            raise ApplicationPacketError(
                code="packet_sources_changed",
                message="岗位、分析或投递资料已变化，请创建新版本",
                details={"source_change_codes": source_change_codes},
            )
        if revision.blockers:
            raise ApplicationPacketError(
                code="packet_approval_blocked",
                message="仍有未解决项，当前版本不能批准",
                details={"blockers": revision.blockers},
            )

        now = datetime.now(UTC)
        changed = self.session.execute(
            update(PacketRevision)
            .where(
                PacketRevision.id == revision.id,
                PacketRevision.user_id == user_id,
                PacketRevision.status == PacketStatus.NEEDS_REVIEW.value,
            )
            .values(
                status=PacketStatus.APPROVED.value,
                approved_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if int(changed.rowcount or 0) != 1:
            self.session.rollback()
            current = self._revision(user_id=user_id, revision_id=revision_id)
            if current.status == PacketStatus.APPROVED.value:
                return self.get(user_id=user_id, packet_id=current.packet_id)
            raise ApplicationPacketError(
                code="concurrent_packet_approval",
                message="投递包审批状态已被其他请求修改",
            )

        packet.status = PacketStatus.APPROVED.value
        packet.updated_at = now
        decision = PacketDecision(
            id=generate_packet_decision_id(),
            user_id=user_id,
            packet_id=packet.id,
            revision_id=revision.id,
            application_id=revision.application_id,
            decision=PacketDecisionType.APPROVE.value,
            actor_type="user",
            created_at=now,
        )
        self.session.add(decision)
        self._add_event(
            user_id=user_id,
            application_id=revision.application_id,
            event_type="ApplicationPacketApproved",
            payload={
                "packet_id": packet.id,
                "packet_revision_id": revision.id,
                "revision_number": revision.revision_number,
                "status": PacketStatus.APPROVED.value,
                "decision_id": decision.id,
            },
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            current = self._revision(user_id=user_id, revision_id=revision_id)
            if current.status == PacketStatus.APPROVED.value:
                return self.get(user_id=user_id, packet_id=current.packet_id)
            raise
        return self.get(user_id=user_id, packet_id=packet.id)

    def create_revision(
        self,
        *,
        user_id: str,
        packet_id: str,
        actor_type: ActorType,
        resume_version_id: str | None | object = ...,
        evidence_ids: list[str] | None = None,
        answer_entry_ids: list[str] | None = None,
        open_questions: list[dict[str, Any]] | None = None,
    ) -> ApplicationPacketView:
        packet = self._packet(user_id=user_id, packet_id=packet_id)
        current = self._revision(
            user_id=user_id, revision_id=packet.current_revision_id
        )
        if current.status not in {
            PacketStatus.APPROVED.value,
            PacketStatus.SUPERSEDED.value,
        }:
            raise ApplicationPacketError(
                code="active_revision_exists",
                message="当前版本仍可编辑，不需要创建新版本",
            )
        selected_resume_id = (
            current.resume_version_id
            if resume_version_id is ...
            else resume_version_id
        )
        selected_evidence_ids = (
            [item["id"] for item in current.evidence_snapshots]
            if evidence_ids is None
            else evidence_ids
        )
        selected_answer_ids = (
            [item["id"] for item in current.form_answer_snapshots]
            if answer_entry_ids is None
            else answer_entry_ids
        )
        selected_open_questions = (
            current.open_questions if open_questions is None else open_questions
        )
        application_view = ApplicationService(self.session).get_application(
            user_id=user_id,
            application_id=packet.application_id,
        )
        analysis, parse_result = self._latest_analysis(
            user_id=user_id,
            job_posting_id=packet.job_posting_id,
            content_hash=application_view.posting.content_hash,
        )
        sources = self._freeze_sources(
            user_id=user_id,
            posting=application_view.posting,
            analysis=analysis,
            parse_result=parse_result,
            resume_version_id=selected_resume_id,
            evidence_ids=selected_evidence_ids,
            answer_entry_ids=selected_answer_ids,
            open_questions=selected_open_questions,
            actor_type=actor_type,
        )
        revision_number = int(
            self.session.scalar(
                select(func.max(PacketRevision.revision_number)).where(
                    PacketRevision.packet_id == packet.id
                )
            )
            or 0
        ) + 1
        revision = self._revision_from_sources(
            revision_id=generate_packet_revision_id(),
            packet_id=packet.id,
            user_id=user_id,
            application_id=packet.application_id,
            job_posting_id=packet.job_posting_id,
            revision_number=revision_number,
            supersedes_revision_id=current.id,
            analysis=analysis,
            resume_version_id=selected_resume_id,
            actor_type=actor_type,
            sources=sources,
        )
        now = datetime.now(UTC)
        if current.status == PacketStatus.APPROVED.value:
            current.status = PacketStatus.SUPERSEDED.value
            current.superseded_at = now
            current.updated_at = now
        packet.current_revision_id = revision.id
        packet.status = PacketStatus.DRAFT.value
        packet.updated_at = now
        self.session.add(revision)
        self._add_event(
            user_id=user_id,
            application_id=packet.application_id,
            event_type="ApplicationPacketRevisionCreated",
            payload={
                "packet_id": packet.id,
                "packet_revision_id": revision.id,
                "revision_number": revision_number,
                "supersedes_revision_id": current.id,
                "status": PacketStatus.DRAFT.value,
            },
        )
        self.session.commit()
        return self.get(user_id=user_id, packet_id=packet.id)

    def _view(self, packet: ApplicationPacket) -> ApplicationPacketView:
        revisions = list(
            self.session.scalars(
                select(PacketRevision)
                .where(
                    PacketRevision.packet_id == packet.id,
                    PacketRevision.user_id == packet.user_id,
                )
                .order_by(PacketRevision.revision_number.desc())
            ).all()
        )
        return ApplicationPacketView(
            packet=packet,
            revisions=[self._revision_view(revision) for revision in revisions],
        )

    def _revision_view(self, revision: PacketRevision) -> PacketRevisionView:
        decisions = list(
            self.session.scalars(
                select(PacketDecision)
                .where(
                    PacketDecision.revision_id == revision.id,
                    PacketDecision.user_id == revision.user_id,
                )
                .order_by(PacketDecision.created_at, PacketDecision.id)
            ).all()
        )
        source_change_codes = self._source_change_codes(revision)
        return PacketRevisionView(
            revision=revision,
            decisions=decisions,
            source_changed=bool(source_change_codes),
            source_change_codes=source_change_codes,
        )

    def _packet(self, *, user_id: str, packet_id: str) -> ApplicationPacket:
        packet = self.session.scalar(
            select(ApplicationPacket).where(
                ApplicationPacket.id == packet_id,
                ApplicationPacket.user_id == user_id,
            )
        )
        if packet is None:
            raise ApplicationPacketNotFoundError(packet_id)
        return packet

    def _revision(self, *, user_id: str, revision_id: str) -> PacketRevision:
        revision = self.session.scalar(
            select(PacketRevision).where(
                PacketRevision.id == revision_id,
                PacketRevision.user_id == user_id,
            )
        )
        if revision is None:
            raise ApplicationPacketNotFoundError(revision_id)
        return revision

    def _latest_analysis(
        self, *, user_id: str, job_posting_id: str, content_hash: str
    ) -> tuple[JobAnalysis, JobParseResult]:
        row = self.session.execute(
            select(JobAnalysis, JobParseResult)
            .join(JobParseResult, JobParseResult.id == JobAnalysis.parse_result_id)
            .where(
                JobAnalysis.user_id == user_id,
                JobAnalysis.job_posting_id == job_posting_id,
                JobAnalysis.invalidated_at.is_(None),
                JobAnalysis.analysis_version == ANALYSIS_VERSION,
                JobParseResult.content_hash == content_hash,
            )
            .order_by(JobAnalysis.created_at.desc(), JobAnalysis.id.desc())
        ).first()
        if row is None:
            raise ApplicationPacketError(
                code="valid_analysis_required",
                message="请先为当前岗位内容生成有效分析",
            )
        return row[0], row[1]

    def _default_resume_id(self, user_id: str) -> str | None:
        return self.session.scalar(
            select(ResumeVersion.id)
            .where(ResumeVersion.user_id == user_id)
            .order_by(
                ResumeVersion.is_default.desc(),
                ResumeVersion.version_number.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def _analysis_evidence_ids(analysis: JobAnalysis) -> list[str]:
        ids: list[str] = []
        for match in analysis.matches or []:
            for evidence_id in match.get("evidence_ids") or []:
                if evidence_id not in ids:
                    ids.append(evidence_id)
        return ids

    def _freeze_sources(
        self,
        *,
        user_id: str,
        posting: Any,
        analysis: JobAnalysis,
        parse_result: JobParseResult,
        resume_version_id: str | None,
        evidence_ids: list[str],
        answer_entry_ids: list[str],
        open_questions: list[dict[str, Any]],
        actor_type: ActorType,
    ) -> _FrozenSources:
        profile = self.session.get(CandidatePrivateProfile, user_id)
        if profile is None:
            profile = CandidateMaterialService(self.session).get_or_create_profile(user_id)
        profile_snapshot = self._profile_snapshot(profile)
        confirmation_items = CandidateMaterialService(
            self.session
        ).profile_confirmation_items(profile)
        resume_snapshot = self._resume_snapshot(
            user_id=user_id, resume_version_id=resume_version_id
        )
        evidence_snapshots = self._evidence_snapshots(
            user_id=user_id, evidence_ids=evidence_ids
        )
        answer_snapshots = self._answer_snapshots(
            user_id=user_id, answer_ids=answer_entry_ids
        )
        normalized_open_questions = self._normalize_open_questions(
            open_questions, actor_type=actor_type
        )
        risks = list(analysis.risks or [])
        blockers = self._build_blockers(
            analysis=analysis,
            profile_confirmation_items=confirmation_items,
            resume_snapshot=resume_snapshot,
            answer_snapshots=answer_snapshots,
            open_questions=normalized_open_questions,
            risks=risks,
        )
        job_snapshot = {
            "id": posting.id,
            "company": posting.company,
            "title": posting.title,
            "locations": list(posting.locations or []),
            "job_type": posting.job_type,
            "source_url": posting.source_url,
            "verification_status": posting.verification_status,
            "availability_status": posting.availability_status,
            "raw_content": posting.raw_content,
            "content_hash": posting.content_hash,
        }
        analysis_snapshot = {
            "id": analysis.id,
            "analysis_version": analysis.analysis_version,
            "input_hash": analysis.input_hash,
            "structured_jd": parse_result.structured_jd,
            "eligibility": analysis.eligibility,
            "matches": analysis.matches,
            "score": analysis.score,
            "risks": risks,
            "missing_information": analysis.missing_information,
        }
        source_payload = {
            "job_content_hash": posting.content_hash,
            "analysis_id": analysis.id,
            "analysis_input_hash": analysis.input_hash,
            "profile_revision": profile.revision,
            "resume": resume_snapshot,
            "evidence": evidence_snapshots,
            "answers": answer_snapshots,
        }
        return _FrozenSources(
            job_snapshot=job_snapshot,
            analysis_snapshot=analysis_snapshot,
            profile_snapshot=profile_snapshot,
            resume_snapshot=resume_snapshot,
            evidence_snapshots=evidence_snapshots,
            answer_snapshots=answer_snapshots,
            open_questions=normalized_open_questions,
            risks=risks,
            confirmation_items=confirmation_items,
            blockers=blockers,
            source_fingerprint=_hash_json(source_payload),
        )

    def _revision_from_sources(
        self,
        *,
        revision_id: str,
        packet_id: str,
        user_id: str,
        application_id: str,
        job_posting_id: str,
        revision_number: int,
        supersedes_revision_id: str | None,
        analysis: JobAnalysis,
        resume_version_id: str | None,
        actor_type: ActorType,
        sources: _FrozenSources,
    ) -> PacketRevision:
        revision = PacketRevision(
            id=revision_id,
            packet_id=packet_id,
            user_id=user_id,
            application_id=application_id,
            job_posting_id=job_posting_id,
            revision_number=revision_number,
            status=PacketStatus.DRAFT.value,
            supersedes_revision_id=supersedes_revision_id,
            job_analysis_id=analysis.id,
            analysis_version=analysis.analysis_version,
            analysis_input_hash=analysis.input_hash,
            jd_content_hash=sources.job_snapshot["content_hash"],
            profile_revision=sources.profile_snapshot["revision"],
            resume_version_id=resume_version_id,
            source_fingerprint=sources.source_fingerprint,
            payload_hash="",
            job_snapshot=sources.job_snapshot,
            analysis_snapshot=sources.analysis_snapshot,
            profile_snapshot=sources.profile_snapshot,
            resume_snapshot=sources.resume_snapshot,
            evidence_snapshots=sources.evidence_snapshots,
            form_answer_snapshots=sources.answer_snapshots,
            open_questions=sources.open_questions,
            risk_snapshots=sources.risks,
            confirmation_items=sources.confirmation_items,
            blockers=sources.blockers,
            created_by_actor=actor_type,
        )
        revision.payload_hash = self._payload_hash(revision)
        return revision

    def _apply_sources(
        self,
        revision: PacketRevision,
        *,
        sources: _FrozenSources,
        analysis: JobAnalysis,
        resume_version_id: str | None,
    ) -> None:
        revision.job_analysis_id = analysis.id
        revision.analysis_version = analysis.analysis_version
        revision.analysis_input_hash = analysis.input_hash
        revision.jd_content_hash = sources.job_snapshot["content_hash"]
        revision.profile_revision = sources.profile_snapshot["revision"]
        revision.resume_version_id = resume_version_id
        revision.source_fingerprint = sources.source_fingerprint
        revision.job_snapshot = sources.job_snapshot
        revision.analysis_snapshot = sources.analysis_snapshot
        revision.profile_snapshot = sources.profile_snapshot
        revision.resume_snapshot = sources.resume_snapshot
        revision.evidence_snapshots = sources.evidence_snapshots
        revision.form_answer_snapshots = sources.answer_snapshots
        revision.open_questions = sources.open_questions
        revision.risk_snapshots = sources.risks
        revision.confirmation_items = sources.confirmation_items
        revision.blockers = sources.blockers
        revision.updated_at = datetime.now(UTC)
        revision.payload_hash = self._payload_hash(revision)

    @staticmethod
    def _profile_snapshot(profile: CandidatePrivateProfile) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": profile.user_id,
            "revision": profile.revision,
            "voluntary_disclosure_policy": profile.voluntary_disclosure_policy,
        }
        for name in (
            "contact_email",
            "contact_phone",
            "current_status",
            "availability_date",
            "work_authorization",
            "sponsorship_required",
            "salary_strategy",
            "relocation_willing",
        ):
            value = getattr(profile, name)
            payload[name] = {
                "state": getattr(profile, f"{name}_state"),
                "value": value.isoformat() if isinstance(value, date) else value,
            }
        return payload

    def _resume_snapshot(
        self, *, user_id: str, resume_version_id: str | None
    ) -> dict[str, Any]:
        if resume_version_id is None:
            return {}
        row = self.session.execute(
            select(ResumeVersion, ResumeAsset)
            .join(ResumeAsset, ResumeAsset.id == ResumeVersion.asset_id)
            .where(
                ResumeVersion.id == resume_version_id,
                ResumeVersion.user_id == user_id,
                ResumeAsset.user_id == user_id,
            )
        ).first()
        if row is None:
            raise ApplicationPacketError(
                code="resume_version_not_found",
                message="简历版本不存在或不属于当前用户",
            )
        version, asset = row
        return {
            "id": version.id,
            "version_number": version.version_number,
            "label": version.label,
            "job_family": version.job_family,
            "source_version_id": version.source_version_id,
            "generation_reason": version.generation_reason,
            "is_default": version.is_default,
            "updated_at": _iso(version.updated_at),
            "asset": {
                "id": asset.id,
                "original_filename": asset.original_filename,
                "media_type": asset.media_type,
                "size_bytes": asset.size_bytes,
                "sha256": asset.sha256,
            },
        }

    def _evidence_snapshots(
        self, *, user_id: str, evidence_ids: list[str]
    ) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(evidence_ids))
        if not unique_ids:
            return []
        items = list(
            self.session.scalars(
                select(EvidenceItem).where(
                    EvidenceItem.user_id == user_id,
                    EvidenceItem.id.in_(unique_ids),
                )
            ).all()
        )
        by_id = {item.id: item for item in items}
        missing = [item_id for item_id in unique_ids if item_id not in by_id]
        if missing:
            raise ApplicationPacketError(
                code="evidence_not_found",
                message="部分经历证据不存在或不属于当前用户",
                details={"evidence_ids": missing},
            )
        return [
            {
                "id": item.id,
                "type": item.type,
                "title": item.title,
                "claim": item.claim,
                "skills": list(item.skills or []),
                "source": item.source,
                "updated_at": _iso(item.updated_at),
            }
            for item in (by_id[item_id] for item_id in unique_ids)
        ]

    def _answer_snapshots(
        self, *, user_id: str, answer_ids: list[str]
    ) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(answer_ids))
        if not unique_ids:
            return []
        entries = list(
            self.session.scalars(
                select(AnswerBankEntry).where(
                    AnswerBankEntry.user_id == user_id,
                    AnswerBankEntry.id.in_(unique_ids),
                )
            ).all()
        )
        by_id = {entry.id: entry for entry in entries}
        missing = [item_id for item_id in unique_ids if item_id not in by_id]
        if missing:
            raise ApplicationPacketError(
                code="answer_not_found",
                message="部分答案不存在或不属于当前用户",
                details={"answer_entry_ids": missing},
            )
        return [
            {
                "id": entry.id,
                "question_pattern": entry.question_pattern,
                "answer": entry.answer,
                "scope_type": entry.scope_type,
                "scope_value": entry.scope_value,
                "sensitivity": entry.sensitivity,
                "confirmed_at": _iso(entry.confirmed_at),
                "updated_at": _iso(entry.updated_at),
            }
            for entry in (by_id[item_id] for item_id in unique_ids)
        ]

    @staticmethod
    def _normalize_open_questions(
        open_questions: list[dict[str, Any]], *, actor_type: ActorType
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for index, item in enumerate(open_questions):
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip() or None
            sensitivity = str(item.get("sensitivity") or "standard")
            try:
                AnswerSensitivity(sensitivity)
            except ValueError as error:
                raise ApplicationPacketError(
                    code="invalid_open_question",
                    message="开放题敏感级别无效",
                ) from error
            confirmed = bool(item.get("confirmed", False))
            if not question:
                raise ApplicationPacketError(
                    code="invalid_open_question",
                    message="开放题问题不能为空",
                )
            if confirmed and not answer:
                raise ApplicationPacketError(
                    code="invalid_open_question",
                    message="确认开放题前必须填写答案",
                )
            if actor_type == "agent" and confirmed:
                raise ApplicationPacketError(
                    code="agent_cannot_confirm",
                    message="Agent 不能替用户确认开放题答案",
                )
            normalized.append(
                {
                    "id": str(item.get("id") or f"open_{index + 1}"),
                    "question": question,
                    "answer": answer,
                    "sensitivity": sensitivity,
                    "confirmed_at": _iso(now) if confirmed else None,
                }
            )
        return normalized

    @staticmethod
    def _build_blockers(
        *,
        analysis: JobAnalysis,
        profile_confirmation_items: list[dict[str, Any]],
        resume_snapshot: dict[str, Any],
        answer_snapshots: list[dict[str, Any]],
        open_questions: list[dict[str, Any]],
        risks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        eligibility = (analysis.eligibility or {}).get("eligible")
        if eligibility != "pass":
            blockers.append(
                {
                    "code": f"eligibility_{eligibility or 'unknown'}",
                    "category": "eligibility",
                    "message": (
                        "硬性资格未通过，不能批准投递包"
                        if eligibility == "fail"
                        else "硬性资格仍有未知项，需要用户确认并重新分析"
                    ),
                }
            )
        if profile_confirmation_items:
            blockers.append(
                {
                    "code": "private_profile_incomplete",
                    "category": "material",
                    "message": "私密候选人档案仍有高影响字段未确认",
                    "fields": [item["field"] for item in profile_confirmation_items],
                }
            )
        if not resume_snapshot:
            blockers.append(
                {
                    "code": "resume_missing",
                    "category": "material",
                    "message": "尚未选择简历版本",
                }
            )
        for answer in answer_snapshots:
            if (
                answer.get("sensitivity")
                in {
                    AnswerSensitivity.PERSONAL.value,
                    AnswerSensitivity.HIGH_IMPACT.value,
                }
                and not answer.get("confirmed_at")
            ):
                blockers.append(
                    {
                        "code": "sensitive_answer_unconfirmed",
                        "category": "answer",
                        "message": "敏感表单答案尚未由用户确认",
                        "answer_id": answer.get("id"),
                    }
                )
        for question in open_questions:
            if not question.get("answer") or not question.get("confirmed_at"):
                blockers.append(
                    {
                        "code": "open_question_unconfirmed",
                        "category": "answer",
                        "message": "开放题答案尚未完成并确认",
                        "question_id": question.get("id"),
                    }
                )
        for risk in risks:
            if (
                risk.get("severity") == "high"
                and str(risk.get("code") or "").startswith("evidence_missing:")
            ):
                blockers.append(
                    {
                        "code": "required_evidence_missing",
                        "category": "evidence",
                        "message": "必备要求缺少可核验经历证据",
                        "requirement_name": risk.get("requirement_name"),
                    }
                )
        return blockers

    def _source_change_codes(self, revision: PacketRevision) -> list[str]:
        codes: list[str] = []
        try:
            application_view = ApplicationService(self.session).get_application(
                user_id=revision.user_id,
                application_id=revision.application_id,
            )
        except ApplicationNotFoundError:
            return ["application_missing"]
        posting = application_view.posting
        if posting.id != revision.job_posting_id:
            codes.append("job_changed")
        if posting.content_hash != revision.jd_content_hash:
            codes.append("jd_content_changed")
        analysis = self.session.scalar(
            select(JobAnalysis).where(
                JobAnalysis.id == revision.job_analysis_id,
                JobAnalysis.user_id == revision.user_id,
            )
        )
        if analysis is None:
            codes.append("analysis_missing")
        else:
            if analysis.invalidated_at is not None:
                codes.append("analysis_invalidated")
            if analysis.analysis_version != ANALYSIS_VERSION:
                codes.append("analysis_version_changed")
            if analysis.input_hash != revision.analysis_input_hash:
                codes.append("analysis_input_changed")
        profile = self.session.get(CandidatePrivateProfile, revision.user_id)
        if profile is None or profile.revision != revision.profile_revision:
            codes.append("private_profile_changed")
        try:
            resume = self._resume_snapshot(
                user_id=revision.user_id,
                resume_version_id=revision.resume_version_id,
            )
            evidence = self._evidence_snapshots(
                user_id=revision.user_id,
                evidence_ids=[item["id"] for item in revision.evidence_snapshots],
            )
            answers = self._answer_snapshots(
                user_id=revision.user_id,
                answer_ids=[item["id"] for item in revision.form_answer_snapshots],
            )
        except ApplicationPacketError as error:
            codes.append(error.code)
            return list(dict.fromkeys(codes))
        current_fingerprint = _hash_json(
            {
                "job_content_hash": posting.content_hash,
                "analysis_id": analysis.id if analysis else revision.job_analysis_id,
                "analysis_input_hash": (
                    analysis.input_hash if analysis else revision.analysis_input_hash
                ),
                "profile_revision": profile.revision if profile else None,
                "resume": resume,
                "evidence": evidence,
                "answers": answers,
            }
        )
        if current_fingerprint != revision.source_fingerprint:
            codes.append("source_fingerprint_changed")
        return list(dict.fromkeys(codes))

    @staticmethod
    def _payload_hash(revision: PacketRevision) -> str:
        return _hash_json(
            {
                "job_snapshot": revision.job_snapshot,
                "analysis_snapshot": revision.analysis_snapshot,
                "profile_snapshot": revision.profile_snapshot,
                "resume_snapshot": revision.resume_snapshot,
                "evidence_snapshots": revision.evidence_snapshots,
                "form_answer_snapshots": revision.form_answer_snapshots,
                "open_questions": revision.open_questions,
                "risk_snapshots": revision.risk_snapshots,
                "confirmation_items": revision.confirmation_items,
                "blockers": revision.blockers,
            }
        )

    def _add_event(
        self,
        *,
        user_id: str,
        application_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.session.add(
            DomainEvent(
                id=generate_domain_event_id(),
                user_id=user_id,
                entity_type="application",
                entity_id=application_id,
                event_type=event_type,
                payload=payload,
            )
        )


def _hash_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

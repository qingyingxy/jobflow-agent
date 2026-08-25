from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.domain.application import (
    Application,
    ApplicationStatus,
    DomainEvent,
    generate_domain_event_id,
)
from src.domain.application_attempt import (
    ATTEMPT_TRANSITIONS,
    ApplicationAttempt,
    ApplicationBlocker,
    AttemptStatus,
    BlockerStatus,
    SubmissionReceipt,
    generate_attempt_id,
    generate_blocker_id,
    generate_receipt_id,
)
from src.domain.application_packet import (
    ApplicationPacket,
    PacketStatus,
)
from src.services.application_packet_service import (
    ApplicationPacketNotFoundError,
    ApplicationPacketService,
)
from src.services.application_service import ApplicationService


class ApplicationAttemptError(RuntimeError):
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


class ApplicationAttemptNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class AttemptChecklistItem:
    code: str
    label: str
    complete: bool
    blocking: bool


@dataclass(frozen=True)
class ApplicationAttemptView:
    attempt: ApplicationAttempt
    blockers: list[ApplicationBlocker]
    receipt: SubmissionReceipt | None
    checklist: list[AttemptChecklistItem]


@dataclass(frozen=True)
class AttemptCreation:
    view: ApplicationAttemptView
    created: bool


class ApplicationAttemptService:
    """Manage manual form execution and verified submission state changes."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        user_id: str,
        packet_revision_id: str,
        application_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> AttemptCreation:
        try:
            revision_view = ApplicationPacketService(self.session).get_revision(
                user_id=user_id,
                revision_id=packet_revision_id,
            )
        except ApplicationPacketNotFoundError as error:
            raise ApplicationAttemptError(
                code="packet_revision_not_found",
                message="投递包版本不存在",
            ) from error
        revision = revision_view.revision
        if revision.status != PacketStatus.APPROVED.value:
            raise ApplicationAttemptError(
                code="packet_revision_not_approved",
                message="只有已批准的投递包版本才能开始投递",
            )
        if revision_view.source_changed:
            raise ApplicationAttemptError(
                code="packet_sources_changed",
                message="投递资料来源已变化，请重新生成并批准投递包",
                details={"source_change_codes": revision_view.source_change_codes},
            )
        packet = self.session.scalar(
            select(ApplicationPacket).where(
                ApplicationPacket.id == revision.packet_id,
                ApplicationPacket.user_id == user_id,
            )
        )
        if packet is None or packet.current_revision_id != revision.id:
            raise ApplicationAttemptError(
                code="packet_revision_not_current",
                message="只能使用当前已批准的投递包版本",
            )
        application_view = ApplicationService(self.session).get_application(
            user_id=user_id,
            application_id=revision.application_id,
        )
        if application_view.application.status != ApplicationStatus.PREPARING.value:
            raise ApplicationAttemptError(
                code="application_not_preparing",
                message="只有准备中的申请可以开始投递尝试",
                details={"application_status": application_view.application.status},
            )
        if application_view.posting.id != revision.job_posting_id:
            raise ApplicationAttemptError(
                code="attempt_binding_mismatch",
                message="投递包与岗位绑定不一致",
            )

        frozen_url = revision.job_snapshot.get("source_url")
        verified_url = self._normalize_http_url(
            str(frozen_url) if frozen_url else None,
            code="official_application_url_missing",
        )
        selected_url = self._normalize_http_url(
            application_url or verified_url,
            code="invalid_application_url",
        )
        if selected_url != verified_url:
            raise ApplicationAttemptError(
                code="application_url_not_verified",
                message="投递地址必须与已验证岗位快照中的官方地址一致",
            )

        existing = self.session.scalar(
            select(ApplicationAttempt).where(
                ApplicationAttempt.application_id == revision.application_id,
                ApplicationAttempt.packet_revision_id == revision.id,
            )
        )
        if existing is not None:
            if existing.user_id != user_id:
                raise ApplicationAttemptNotFoundError(existing.id)
            return AttemptCreation(view=self._view(existing), created=False)

        resolved_key = (idempotency_key or self._attempt_key(
            user_id=user_id,
            application_id=revision.application_id,
            packet_revision_id=revision.id,
            application_url=selected_url,
        )).strip()
        attempt = ApplicationAttempt(
            id=generate_attempt_id(),
            user_id=user_id,
            application_id=revision.application_id,
            job_posting_id=revision.job_posting_id,
            packet_revision_id=revision.id,
            application_url=selected_url,
            status=AttemptStatus.CREATED.value,
            idempotency_key=resolved_key,
        )
        self.session.add(attempt)
        self._add_event(
            user_id=user_id,
            application_id=attempt.application_id,
            event_type="ApplicationAttemptCreated",
            payload={
                "attempt_id": attempt.id,
                "packet_revision_id": attempt.packet_revision_id,
                "job_posting_id": attempt.job_posting_id,
                "status": attempt.status,
            },
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(ApplicationAttempt).where(
                    ApplicationAttempt.user_id == user_id,
                    ApplicationAttempt.application_id == revision.application_id,
                    ApplicationAttempt.packet_revision_id == revision.id,
                )
            )
            if existing is None:
                raise
            return AttemptCreation(view=self._view(existing), created=False)
        return AttemptCreation(view=self.get(user_id=user_id, attempt_id=attempt.id), created=True)

    def list(self, *, user_id: str) -> list[ApplicationAttemptView]:
        attempts = list(
            self.session.scalars(
                select(ApplicationAttempt)
                .where(ApplicationAttempt.user_id == user_id)
                .order_by(
                    ApplicationAttempt.updated_at.desc(),
                    ApplicationAttempt.id.desc(),
                )
            ).all()
        )
        return [self._view(attempt) for attempt in attempts]

    def get(self, *, user_id: str, attempt_id: str) -> ApplicationAttemptView:
        attempt = self.session.scalar(
            select(ApplicationAttempt).where(
                ApplicationAttempt.id == attempt_id,
                ApplicationAttempt.user_id == user_id,
            )
        )
        if attempt is None:
            raise ApplicationAttemptNotFoundError(attempt_id)
        return self._view(attempt)

    def transition(
        self,
        *,
        user_id: str,
        attempt_id: str,
        target_status: AttemptStatus,
    ) -> ApplicationAttemptView:
        view = self.get(user_id=user_id, attempt_id=attempt_id)
        attempt = view.attempt
        current_status = AttemptStatus(attempt.status)
        if target_status == current_status:
            return view
        if target_status is AttemptStatus.SUBMITTED:
            raise ApplicationAttemptError(
                code="submission_receipt_required",
                message="必须通过提交确认接口校验真实凭证后才能标记已投递",
            )
        allowed = ATTEMPT_TRANSITIONS[current_status]
        if target_status not in allowed:
            raise ApplicationAttemptError(
                code="invalid_attempt_transition",
                message=f"投递尝试不能从 {current_status.value} 进入 {target_status.value}",
                details={
                    "current": current_status.value,
                    "target": target_status.value,
                    "allowed": sorted(item.value for item in allowed),
                },
            )
        if target_status is AttemptStatus.READY_TO_SUBMIT and any(
            blocker.status == BlockerStatus.OPEN.value for blocker in view.blockers
        ):
            raise ApplicationAttemptError(
                code="open_blockers_present",
                message="仍有未解决阻塞，不能进入待提交状态",
            )

        now = datetime.now(UTC)
        attempt.status = target_status.value
        attempt.updated_at = now
        if target_status is AttemptStatus.FORM_IN_PROGRESS:
            attempt.form_opened_at = attempt.form_opened_at or now
        elif target_status is AttemptStatus.READY_TO_SUBMIT:
            attempt.ready_at = now
        elif target_status is AttemptStatus.FAILED:
            attempt.failed_at = now
        elif target_status is AttemptStatus.ABANDONED:
            attempt.abandoned_at = now
        self._add_event(
            user_id=user_id,
            application_id=attempt.application_id,
            event_type="ApplicationAttemptStatusChanged",
            payload={
                "attempt_id": attempt.id,
                "packet_revision_id": attempt.packet_revision_id,
                "from_status": current_status.value,
                "to_status": target_status.value,
            },
        )
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self.get(user_id=user_id, attempt_id=attempt.id)

    def add_blocker(
        self,
        *,
        user_id: str,
        attempt_id: str,
        category: str,
        observation: str,
        stop_reason: str,
        retryable: bool,
        next_strategy: str | None,
        required_user_action: str | None,
        idempotency_key: str | None = None,
    ) -> ApplicationAttemptView:
        view = self.get(user_id=user_id, attempt_id=attempt_id)
        attempt = view.attempt
        if AttemptStatus(attempt.status) in {
            AttemptStatus.SUBMITTED,
            AttemptStatus.ABANDONED,
        }:
            raise ApplicationAttemptError(
                code="attempt_closed",
                message="已结束的投递尝试不能新增阻塞",
            )
        resolved_key = (idempotency_key or self._blocker_key(
            category=category,
            observation=observation,
            stop_reason=stop_reason,
        )).strip()
        existing = self.session.scalar(
            select(ApplicationBlocker).where(
                ApplicationBlocker.attempt_id == attempt.id,
                ApplicationBlocker.idempotency_key == resolved_key,
            )
        )
        if existing is not None:
            return view

        blocker = ApplicationBlocker(
            id=generate_blocker_id(),
            user_id=user_id,
            attempt_id=attempt.id,
            application_id=attempt.application_id,
            category=category.strip(),
            observation=observation.strip(),
            stop_reason=stop_reason.strip(),
            retryable=retryable,
            next_strategy=self._optional_text(next_strategy),
            required_user_action=self._optional_text(required_user_action),
            status=BlockerStatus.OPEN.value,
            idempotency_key=resolved_key,
        )
        now = datetime.now(UTC)
        previous_status = attempt.status
        attempt.status = (
            AttemptStatus.NEEDS_USER.value
            if blocker.required_user_action
            else AttemptStatus.BLOCKED.value
        )
        attempt.updated_at = now
        self.session.add(blocker)
        self._add_event(
            user_id=user_id,
            application_id=attempt.application_id,
            event_type="ApplicationBlockerOpened",
            payload={
                "attempt_id": attempt.id,
                "blocker_id": blocker.id,
                "category": blocker.category,
                "retryable": blocker.retryable,
                "from_status": previous_status,
                "to_status": attempt.status,
            },
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return self.get(user_id=user_id, attempt_id=attempt.id)
        return self.get(user_id=user_id, attempt_id=attempt.id)

    def resolve_blocker(
        self,
        *,
        user_id: str,
        attempt_id: str,
        blocker_id: str,
    ) -> ApplicationAttemptView:
        attempt_view = self.get(user_id=user_id, attempt_id=attempt_id)
        blocker = self.session.scalar(
            select(ApplicationBlocker).where(
                ApplicationBlocker.id == blocker_id,
                ApplicationBlocker.attempt_id == attempt_id,
                ApplicationBlocker.user_id == user_id,
            )
        )
        if blocker is None:
            raise ApplicationAttemptNotFoundError(blocker_id)
        if blocker.status == BlockerStatus.RESOLVED.value:
            return attempt_view

        now = datetime.now(UTC)
        blocker.status = BlockerStatus.RESOLVED.value
        blocker.resolved_at = now
        blocker.updated_at = now
        remaining = int(
            self.session.scalar(
                select(func.count(ApplicationBlocker.id)).where(
                    ApplicationBlocker.attempt_id == attempt_id,
                    ApplicationBlocker.status == BlockerStatus.OPEN.value,
                    ApplicationBlocker.id != blocker.id,
                )
            )
            or 0
        )
        attempt = attempt_view.attempt
        if remaining == 0 and AttemptStatus(attempt.status) in {
            AttemptStatus.BLOCKED,
            AttemptStatus.NEEDS_USER,
        }:
            attempt.status = AttemptStatus.FORM_IN_PROGRESS.value
            attempt.form_opened_at = attempt.form_opened_at or now
            attempt.updated_at = now
        self._add_event(
            user_id=user_id,
            application_id=attempt.application_id,
            event_type="ApplicationBlockerResolved",
            payload={
                "attempt_id": attempt.id,
                "blocker_id": blocker.id,
                "remaining_open_blockers": remaining,
                "attempt_status": attempt.status,
            },
        )
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self.get(user_id=user_id, attempt_id=attempt.id)

    def record_receipt(
        self,
        *,
        user_id: str,
        attempt_id: str,
        confirmation_text: str | None,
        confirmation_url: str | None,
        application_number: str | None,
        screenshot_metadata: dict[str, Any] | None,
        user_confirmed: bool,
        captured_at: datetime | None = None,
    ) -> ApplicationAttemptView:
        view = self.get(user_id=user_id, attempt_id=attempt_id)
        attempt = view.attempt
        if attempt.status == AttemptStatus.SUBMITTED.value:
            return view
        if attempt.status != AttemptStatus.READY_TO_SUBMIT.value:
            raise ApplicationAttemptError(
                code="attempt_not_ready",
                message="投递尝试必须先完成检查并进入待提交状态",
            )
        normalized_text = self._optional_text(confirmation_text)
        normalized_number = self._optional_text(application_number)
        normalized_url = (
            self._normalize_http_url(
                confirmation_url, code="invalid_confirmation_url"
            )
            if confirmation_url
            else None
        )
        metadata = dict(screenshot_metadata or {})
        captured = captured_at or datetime.now(UTC)
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=UTC)
        validation_codes, issues = self._validate_receipt(
            confirmation_text=normalized_text,
            confirmation_url=normalized_url,
            application_number=normalized_number,
            screenshot_metadata=metadata,
            user_confirmed=user_confirmed,
            captured_at=captured,
        )
        if issues:
            raise ApplicationAttemptError(
                code="invalid_submission_receipt",
                message="提交凭证不足以证明真实投递成功",
                details={"validation_issues": issues},
            )
        receipt_hash = self._receipt_hash(
            attempt=attempt,
            confirmation_text=normalized_text,
            confirmation_url=normalized_url,
            application_number=normalized_number,
            screenshot_metadata=metadata,
        )
        if view.receipt is not None:
            if view.receipt.receipt_hash == receipt_hash:
                return view
            raise ApplicationAttemptError(
                code="receipt_immutable",
                message="已保存的提交凭证不可原地替换",
            )
        receipt = SubmissionReceipt(
            id=generate_receipt_id(),
            user_id=user_id,
            attempt_id=attempt.id,
            application_id=attempt.application_id,
            packet_revision_id=attempt.packet_revision_id,
            confirmation_text=normalized_text,
            confirmation_url=normalized_url,
            application_number=normalized_number,
            screenshot_metadata=metadata,
            user_confirmed=True,
            is_valid=True,
            validation_codes=validation_codes,
            receipt_hash=receipt_hash,
            captured_at=captured,
        )
        self.session.add(receipt)
        self._add_event(
            user_id=user_id,
            application_id=attempt.application_id,
            event_type="SubmissionReceiptRecorded",
            payload={
                "attempt_id": attempt.id,
                "receipt_id": receipt.id,
                "packet_revision_id": attempt.packet_revision_id,
                "is_valid": True,
                "validation_codes": validation_codes,
            },
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            current = self.get(user_id=user_id, attempt_id=attempt.id)
            if current.receipt and current.receipt.receipt_hash == receipt_hash:
                return current
            raise ApplicationAttemptError(
                code="receipt_already_exists",
                message="这条申请已经绑定了其他提交凭证",
            )
        return self.get(user_id=user_id, attempt_id=attempt.id)

    def finalize_submission(
        self,
        *,
        user_id: str,
        attempt_id: str,
    ) -> ApplicationAttemptView:
        view = self.get(user_id=user_id, attempt_id=attempt_id)
        attempt = view.attempt
        if attempt.status == AttemptStatus.SUBMITTED.value:
            return view
        if attempt.status != AttemptStatus.READY_TO_SUBMIT.value:
            raise ApplicationAttemptError(
                code="attempt_not_ready",
                message="投递尝试尚未进入待提交状态",
            )
        if view.receipt is None or not view.receipt.is_valid:
            raise ApplicationAttemptError(
                code="submission_receipt_required",
                message="缺少有效提交凭证，不能标记已投递",
            )
        if any(
            blocker.status == BlockerStatus.OPEN.value for blocker in view.blockers
        ):
            raise ApplicationAttemptError(
                code="open_blockers_present",
                message="仍有未解决阻塞，不能确认投递",
            )
        revision_view = ApplicationPacketService(self.session).get_revision(
            user_id=user_id,
            revision_id=attempt.packet_revision_id,
        )
        if (
            revision_view.revision.status != PacketStatus.APPROVED.value
            or revision_view.source_changed
        ):
            raise ApplicationAttemptError(
                code="packet_no_longer_approved",
                message="投递包已失效或来源发生变化，不能确认投递",
                details={"source_change_codes": revision_view.source_change_codes},
            )

        now = datetime.now(UTC)
        try:
            attempt_changed = self.session.execute(
                update(ApplicationAttempt)
                .where(
                    ApplicationAttempt.id == attempt.id,
                    ApplicationAttempt.user_id == user_id,
                    ApplicationAttempt.status == AttemptStatus.READY_TO_SUBMIT.value,
                )
                .values(
                    status=AttemptStatus.SUBMITTED.value,
                    submitted_at=now,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if int(attempt_changed.rowcount or 0) != 1:
                raise ApplicationAttemptError(
                    code="concurrent_attempt_update",
                    message="投递尝试状态已被其他请求修改",
                )
            application_changed = self.session.execute(
                update(Application)
                .where(
                    Application.id == attempt.application_id,
                    Application.status == ApplicationStatus.PREPARING.value,
                )
                .values(
                    status=ApplicationStatus.SUBMITTED.value,
                    next_action="等待招聘方后续通知",
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if int(application_changed.rowcount or 0) != 1:
                raise ApplicationAttemptError(
                    code="application_not_preparing",
                    message="申请状态已变化，未执行提交确认",
                )
            self._add_event(
                user_id=user_id,
                application_id=attempt.application_id,
                event_type="ApplicationSubmissionVerified",
                payload={
                    "attempt_id": attempt.id,
                    "receipt_id": view.receipt.id,
                    "packet_revision_id": attempt.packet_revision_id,
                    "attempt_status": AttemptStatus.SUBMITTED.value,
                    "application_status": ApplicationStatus.SUBMITTED.value,
                },
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            current = self.session.scalar(
                select(ApplicationAttempt).where(
                    ApplicationAttempt.id == attempt_id,
                    ApplicationAttempt.user_id == user_id,
                )
            )
            if current is not None and current.status == AttemptStatus.SUBMITTED.value:
                return self._view(current)
            raise
        return self.get(user_id=user_id, attempt_id=attempt.id)

    def _view(self, attempt: ApplicationAttempt) -> ApplicationAttemptView:
        blockers = list(
            self.session.scalars(
                select(ApplicationBlocker)
                .where(
                    ApplicationBlocker.attempt_id == attempt.id,
                    ApplicationBlocker.user_id == attempt.user_id,
                )
                .order_by(
                    ApplicationBlocker.created_at.asc(),
                    ApplicationBlocker.id.asc(),
                )
            ).all()
        )
        receipt = self.session.scalar(
            select(SubmissionReceipt).where(
                SubmissionReceipt.attempt_id == attempt.id,
                SubmissionReceipt.user_id == attempt.user_id,
            )
        )
        open_blockers = sum(
            blocker.status == BlockerStatus.OPEN.value for blocker in blockers
        )
        status = AttemptStatus(attempt.status)
        checklist = [
            AttemptChecklistItem(
                code="approved_packet",
                label="投递包已由用户批准并冻结",
                complete=True,
                blocking=True,
            ),
            AttemptChecklistItem(
                code="official_url",
                label="已绑定官方申请地址",
                complete=bool(attempt.application_url),
                blocking=True,
            ),
            AttemptChecklistItem(
                code="form_opened",
                label="已打开并检查申请表单",
                complete=attempt.form_opened_at is not None,
                blocking=True,
            ),
            AttemptChecklistItem(
                code="blockers_resolved",
                label="所有阻塞项均已解决",
                complete=open_blockers == 0,
                blocking=True,
            ),
            AttemptChecklistItem(
                code="ready_for_submission",
                label="表单内容已完成最终检查",
                complete=status in {AttemptStatus.READY_TO_SUBMIT, AttemptStatus.SUBMITTED},
                blocking=True,
            ),
            AttemptChecklistItem(
                code="valid_receipt",
                label="已保存有效提交凭证",
                complete=receipt is not None and receipt.is_valid,
                blocking=True,
            ),
        ]
        return ApplicationAttemptView(
            attempt=attempt,
            blockers=blockers,
            receipt=receipt,
            checklist=checklist,
        )

    @staticmethod
    def _normalize_http_url(value: str | None, *, code: str) -> str:
        if not value or not value.strip():
            raise ApplicationAttemptError(code=code, message="缺少有效的官方申请地址")
        parts = urlsplit(value.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            raise ApplicationAttemptError(code=code, message="申请地址必须是 HTTP(S) URL")
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        path = parts.path or "/"
        if path != "/":
            path = path.rstrip("/")
        return urlunsplit((scheme, netloc, path, parts.query, ""))

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split()).strip()
        return normalized or None

    @staticmethod
    def _attempt_key(
        *,
        user_id: str,
        application_id: str,
        packet_revision_id: str,
        application_url: str,
    ) -> str:
        raw = f"{user_id}|{application_id}|{packet_revision_id}|{application_url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _blocker_key(*, category: str, observation: str, stop_reason: str) -> str:
        raw = "|".join(
            (category.strip().lower(), observation.strip(), stop_reason.strip())
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_receipt(
        *,
        confirmation_text: str | None,
        confirmation_url: str | None,
        application_number: str | None,
        screenshot_metadata: dict[str, Any],
        user_confirmed: bool,
        captured_at: datetime,
    ) -> tuple[list[str], list[str]]:
        codes: list[str] = []
        issues: list[str] = []
        if not user_confirmed:
            issues.append("user_confirmation_missing")
        if captured_at > datetime.now(UTC) + timedelta(minutes=5):
            issues.append("captured_at_in_future")
        success_markers = (
            "submitted",
            "received",
            "thank you",
            "application complete",
            "提交成功",
            "申请已提交",
            "已收到",
            "感谢申请",
            "投递成功",
            "申请成功",
        )
        if (
            confirmation_text
            and len(confirmation_text) >= 4
            and any(marker in confirmation_text.lower() for marker in success_markers)
        ):
            codes.append("confirmation_text")
        elif confirmation_text:
            issues.append("confirmation_text_missing_success_signal")
        if confirmation_url:
            codes.append("confirmation_url")
        if application_number and len(application_number) >= 3:
            codes.append("application_number")
        elif application_number:
            issues.append("application_number_too_short")

        screenshot_valid = False
        if screenshot_metadata:
            sha256 = str(screenshot_metadata.get("sha256", ""))
            content_type = screenshot_metadata.get("content_type")
            size_bytes = screenshot_metadata.get("size_bytes")
            redacted = screenshot_metadata.get("redacted") is True
            screenshot_valid = (
                redacted
                and len(sha256) == 64
                and all(character in "0123456789abcdefABCDEF" for character in sha256)
                and content_type in {"image/png", "image/jpeg", "image/webp"}
                and isinstance(size_bytes, int)
                and 0 < size_bytes <= 10 * 1024 * 1024
            )
            if screenshot_valid:
                codes.append("redacted_screenshot")
            else:
                issues.append("invalid_screenshot_metadata")
        strong_evidence = any(
            code in codes
            for code in ("confirmation_text", "application_number", "redacted_screenshot")
        )
        if not strong_evidence:
            issues.append("success_evidence_missing")
        return codes, issues

    @staticmethod
    def _receipt_hash(
        *,
        attempt: ApplicationAttempt,
        confirmation_text: str | None,
        confirmation_url: str | None,
        application_number: str | None,
        screenshot_metadata: dict[str, Any],
    ) -> str:
        payload = {
            "attempt_id": attempt.id,
            "application_id": attempt.application_id,
            "packet_revision_id": attempt.packet_revision_id,
            "confirmation_text": confirmation_text,
            "confirmation_url": confirmation_url,
            "application_number": application_number,
            "screenshot_metadata": screenshot_metadata,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

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

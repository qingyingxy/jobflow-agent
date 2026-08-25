from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.application import DomainEvent, generate_domain_event_id
from src.domain.application_attempt import (
    ApplicationBlocker,
    AttemptStatus,
    BlockerStatus,
)
from src.domain.application_packet import PacketStatus
from src.domain.ats_assistance import (
    AtsAssistanceSession,
    AtsFieldAction,
    AtsSessionStatus,
    AtsSubmissionAuthorization,
    generate_ats_authorization_id,
    generate_ats_session_id,
)
from src.domain.materials import ResumeAsset
from src.services.application_attempt_service import (
    ApplicationAttemptService,
)
from src.services.application_packet_service import ApplicationPacketService
from src.services.ats_adapters import (
    AtsAdapter,
    AtsAdapterError,
    AtsAdapterRegistry,
    AtsBrowserExecutor,
    AtsFillOperation,
    AtsPageSnapshot,
    blocking_reasons,
    plan_hash,
)
from src.services.ats_browser import AtsBrowserError


class AtsAssistanceError(RuntimeError):
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


class AtsAssistanceNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class AtsSessionView:
    session: AtsAssistanceSession
    authorization: AtsSubmissionAuthorization | None


@dataclass(frozen=True)
class AtsAuthorizationGrant:
    view: AtsSessionView
    token: str


class AtsAssistanceService:
    """Coordinate bounded ATS assistance without weakening M16 receipt rules."""

    def __init__(
        self,
        session: Session,
        *,
        registry: AtsAdapterRegistry | None = None,
    ) -> None:
        self.session = session
        self.registry = registry or AtsAdapterRegistry()

    def list(self, *, user_id: str) -> list[AtsSessionView]:
        sessions = list(
            self.session.scalars(
                select(AtsAssistanceSession)
                .where(AtsAssistanceSession.user_id == user_id)
                .order_by(
                    AtsAssistanceSession.updated_at.desc(),
                    AtsAssistanceSession.id.desc(),
                )
            ).all()
        )
        return [self._view(item) for item in sessions]

    def get(self, *, user_id: str, session_id: str) -> AtsSessionView:
        item = self.session.scalar(
            select(AtsAssistanceSession).where(
                AtsAssistanceSession.id == session_id,
                AtsAssistanceSession.user_id == user_id,
            )
        )
        if item is None:
            raise AtsAssistanceNotFoundError(session_id)
        return self._view(item)

    async def inspect_attempt(
        self,
        *,
        user_id: str,
        attempt_id: str,
        executor: AtsBrowserExecutor,
    ) -> AtsSessionView:
        existing = self.session.scalar(
            select(AtsAssistanceSession).where(
                AtsAssistanceSession.attempt_id == attempt_id,
                AtsAssistanceSession.user_id == user_id,
            )
        )
        if existing is not None:
            return self._view(existing)
        attempt, revision = self._bound_sources(
            user_id=user_id,
            attempt_id=attempt_id,
        )
        self._ensure_in_progress(user_id=user_id, attempt_id=attempt_id)
        snapshot = await self._inspect(executor, attempt.application_url)
        self._require_bound_url(snapshot.final_url, attempt.application_url)
        adapter = self._detect(snapshot)
        now = datetime.now(UTC)
        packet = self._packet_payload(revision)
        field_plan = adapter.map_fields(snapshot, packet, [])
        item = AtsAssistanceSession(
            id=generate_ats_session_id(),
            user_id=user_id,
            attempt_id=attempt.id,
            application_id=attempt.application_id,
            job_posting_id=attempt.job_posting_id,
            packet_revision_id=attempt.packet_revision_id,
            application_url=attempt.application_url,
            provider=adapter.provider.value,
            status=AtsSessionStatus.INSPECTED.value,
            page_fingerprint=snapshot.fingerprint,
            plan_hash=plan_hash(field_plan),
            field_plan=field_plan,
            field_confirmations=[],
            handoff_reasons=[],
            final_summary={},
            inspected_at=now,
            updated_at=now,
        )
        self.session.add(item)
        self._add_event(
            item,
            "AtsAssistanceInspected",
            {
                "provider": item.provider,
                "field_count": len(field_plan),
                "page_fingerprint": item.page_fingerprint,
            },
        )
        self.session.commit()
        return await self._evaluate_and_prepare(
            user_id=user_id,
            item=item,
            revision=revision,
            snapshot=snapshot,
            adapter=adapter,
            executor=executor,
        )

    async def retry(
        self,
        *,
        user_id: str,
        session_id: str,
        user_completed_handoff: bool,
        executor: AtsBrowserExecutor,
    ) -> AtsSessionView:
        view = self.get(user_id=user_id, session_id=session_id)
        item = view.session
        if item.status not in {
            AtsSessionStatus.NEEDS_USER.value,
            AtsSessionStatus.FAILED.value,
        }:
            raise AtsAssistanceError(
                code="ats_session_not_retryable",
                message="当前 ATS 会话不需要重新检查",
            )
        if any(
            reason.get("category") == "submission"
            for reason in item.handoff_reasons
        ):
            raise AtsAssistanceError(
                code="ats_submission_manual_verification_required",
                message="提交结果不确定，必须先在官网人工核对，不能自动重试",
            )
        if not user_completed_handoff:
            raise AtsAssistanceError(
                code="user_handoff_confirmation_required",
                message="请先确认已经完成人工接管步骤",
            )
        attempt, revision = self._bound_sources(
            user_id=user_id,
            attempt_id=item.attempt_id,
        )
        self._resolve_ats_blockers(user_id=user_id, attempt_id=attempt.id)
        self._ensure_in_progress(user_id=user_id, attempt_id=attempt.id)
        snapshot = await self._inspect(executor, attempt.application_url)
        self._require_bound_url(snapshot.final_url, item.application_url)
        adapter = self._detect(snapshot)
        if adapter.provider.value != item.provider:
            raise AtsAssistanceError(
                code="ats_provider_changed",
                message="页面 ATS 类型已经变化，不能沿用原会话",
            )
        return await self._evaluate_and_prepare(
            user_id=user_id,
            item=item,
            revision=revision,
            snapshot=snapshot,
            adapter=adapter,
            executor=executor,
        )

    async def confirm_fields(
        self,
        *,
        user_id: str,
        session_id: str,
        field_keys: list[str],
        executor: AtsBrowserExecutor,
    ) -> AtsSessionView:
        item = self.get(user_id=user_id, session_id=session_id).session
        if item.status != AtsSessionStatus.NEEDS_USER.value:
            raise AtsAssistanceError(
                code="ats_field_confirmation_not_available",
                message="当前会话没有等待确认的敏感字段",
            )
        requested = set(field_keys)
        confirmable = {
            str(entry.get("field_key")): str(entry.get("value_hash"))
            for entry in item.field_plan
            if entry.get("action") == AtsFieldAction.NEEDS_CONFIRMATION.value
            and entry.get("value_hash")
        }
        if not requested or not requested.issubset(confirmable):
            raise AtsAssistanceError(
                code="invalid_ats_field_confirmation",
                message="只能确认当前等待用户确认的字段",
            )
        now = datetime.now(UTC)
        current = {
            str(entry.get("field_key")): entry
            for entry in item.field_confirmations
        }
        for key in requested:
            current[key] = {
                "field_key": key,
                "value_hash": confirmable[key],
                "confirmed_at": now.isoformat(),
            }
        item.field_confirmations = list(current.values())
        item.updated_at = now
        self._add_event(
            item,
            "AtsSensitiveFieldsConfirmed",
            {"field_keys": sorted(requested)},
        )
        self.session.commit()
        attempt, revision = self._bound_sources(
            user_id=user_id,
            attempt_id=item.attempt_id,
        )
        snapshot = await self._inspect(executor, attempt.application_url)
        self._require_bound_url(snapshot.final_url, item.application_url)
        adapter = self._detect(snapshot)
        return await self._evaluate_and_prepare(
            user_id=user_id,
            item=item,
            revision=revision,
            snapshot=snapshot,
            adapter=adapter,
            executor=executor,
        )

    def authorize(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> AtsAuthorizationGrant:
        item = self.get(user_id=user_id, session_id=session_id).session
        if item.status not in {
            AtsSessionStatus.READY_FOR_APPROVAL.value,
            AtsSessionStatus.AUTHORIZED.value,
        }:
            raise AtsAssistanceError(
                code="ats_session_not_ready_for_authorization",
                message="表单尚未完成填写与验证，不能授权提交",
            )
        attempt, _ = self._bound_sources(
            user_id=user_id,
            attempt_id=item.attempt_id,
        )
        if attempt.status != AttemptStatus.READY_TO_SUBMIT.value:
            raise AtsAssistanceError(
                code="attempt_not_ready",
                message="投递尝试尚未进入待提交状态",
            )
        now = datetime.now(UTC)
        if item.current_authorization_id:
            previous = self.session.get(
                AtsSubmissionAuthorization, item.current_authorization_id
            )
            if previous and previous.used_at is None:
                previous.revoked_at = now
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_text(token)
        authorization = AtsSubmissionAuthorization(
            id=generate_ats_authorization_id(),
            user_id=user_id,
            session_id=item.id,
            attempt_id=item.attempt_id,
            job_posting_id=item.job_posting_id,
            packet_revision_id=item.packet_revision_id,
            application_url_hash=self._hash_text(item.application_url),
            page_fingerprint=item.page_fingerprint,
            plan_hash=item.plan_hash,
            binding_hash=self._binding_hash(item),
            token_hash=token_hash,
            expires_at=now
            + timedelta(seconds=get_settings().ats_authorization_ttl_seconds),
        )
        item.current_authorization_id = authorization.id
        item.status = AtsSessionStatus.AUTHORIZED.value
        item.authorized_at = now
        item.updated_at = now
        self.session.add(authorization)
        self._add_event(
            item,
            "AtsSubmissionAuthorized",
            {
                "authorization_id": authorization.id,
                "expires_at": authorization.expires_at.isoformat(),
                "page_fingerprint": item.page_fingerprint,
                "plan_hash": item.plan_hash,
            },
        )
        self.session.commit()
        return AtsAuthorizationGrant(view=self._view(item), token=token)

    async def submit(
        self,
        *,
        user_id: str,
        session_id: str,
        authorization_token: str,
        executor: AtsBrowserExecutor,
    ) -> AtsSessionView:
        item = self.get(user_id=user_id, session_id=session_id).session
        if item.status == AtsSessionStatus.SUBMITTED.value:
            return self._view(item)
        authorization = self._validate_authorization(
            item=item,
            user_id=user_id,
            token=authorization_token,
        )
        attempt, revision = self._bound_sources(
            user_id=user_id,
            attempt_id=item.attempt_id,
        )
        if attempt.status != AttemptStatus.READY_TO_SUBMIT.value:
            raise AtsAssistanceError(
                code="attempt_not_ready",
                message="投递尝试尚未进入待提交状态",
            )
        now = datetime.now(UTC)
        consumed = self.session.execute(
            update(AtsSubmissionAuthorization)
            .where(
                AtsSubmissionAuthorization.id == authorization.id,
                AtsSubmissionAuthorization.user_id == user_id,
                AtsSubmissionAuthorization.used_at.is_(None),
                AtsSubmissionAuthorization.revoked_at.is_(None),
            )
            .values(used_at=now)
            .execution_options(synchronize_session=False)
        )
        if int(consumed.rowcount or 0) != 1:
            self.session.rollback()
            raise AtsAssistanceError(
                code="ats_authorization_already_used",
                message="一次性提交授权已经使用",
            )
        item.status = AtsSessionStatus.SUBMITTING.value
        item.updated_at = now
        self._add_event(
            item,
            "AtsSubmissionStarted",
            {"authorization_id": authorization.id},
        )
        self.session.commit()
        try:
            snapshot = await self._inspect(executor, item.application_url)
            self._require_bound_url(snapshot.final_url, item.application_url)
            adapter = self._detect(snapshot)
            if adapter.provider.value != item.provider:
                raise AtsAssistanceError(
                    code="ats_provider_changed",
                    message="提交前 ATS 类型发生变化",
                )
            packet = self._packet_payload(revision)
            current_plan = adapter.map_fields(
                snapshot,
                packet,
                item.field_confirmations,
            )
            if (
                snapshot.fingerprint != item.page_fingerprint
                or plan_hash(current_plan) != item.plan_hash
            ):
                raise AtsAssistanceError(
                    code="ats_page_changed",
                    message="提交前页面或字段计划已变化，授权已作废",
                )
            operations = self._materialize_operations(
                adapter.fill(current_plan),
                current_plan,
            )
            evidence = await adapter.submit(
                executor,
                url=item.application_url,
                operations=operations,
            )
            receipt = adapter.capture_receipt(evidence)
        except (AtsAssistanceError, AtsAdapterError, AtsBrowserError) as error:
            self._mark_submission_unverified(
                user_id=user_id,
                item=item,
                code=getattr(error, "code", "ats_submission_unverified"),
            )
            if isinstance(error, AtsAssistanceError):
                raise
            raise AtsAssistanceError(
                code=getattr(error, "code", "ats_submission_unverified"),
                message=str(error),
            ) from error
        except Exception as error:
            self._mark_submission_unverified(
                user_id=user_id,
                item=item,
                code="ats_submission_internal_error",
            )
            raise AtsAssistanceError(
                code="ats_submission_internal_error",
                message="ATS 提交执行异常，请在官网人工核对提交结果",
            ) from error

        attempt_service = ApplicationAttemptService(self.session)
        attempt_service.record_receipt(
            user_id=user_id,
            attempt_id=item.attempt_id,
            confirmation_text=receipt["confirmation_text"],
            confirmation_url=receipt["confirmation_url"],
            application_number=receipt["application_number"],
            screenshot_metadata=None,
            user_confirmed=True,
            captured_at=receipt["captured_at"],
        )
        attempt_service.finalize_submission(
            user_id=user_id,
            attempt_id=item.attempt_id,
        )
        item = self.get(user_id=user_id, session_id=session_id).session
        finished = datetime.now(UTC)
        item.status = AtsSessionStatus.SUBMITTED.value
        item.submitted_at = finished
        item.updated_at = finished
        self._add_event(
            item,
            "AtsSubmissionVerified",
            {
                "authorization_id": authorization.id,
                "provider": item.provider,
            },
        )
        self.session.commit()
        return self._view(item)

    async def _evaluate_and_prepare(
        self,
        *,
        user_id: str,
        item: AtsAssistanceSession,
        revision,
        snapshot: AtsPageSnapshot,
        adapter: AtsAdapter,
        executor: AtsBrowserExecutor,
    ) -> AtsSessionView:
        packet = self._packet_payload(revision)
        field_plan = adapter.map_fields(
            snapshot,
            packet,
            item.field_confirmations,
        )
        reasons = blocking_reasons(snapshot, field_plan)
        now = datetime.now(UTC)
        item.page_fingerprint = snapshot.fingerprint
        item.plan_hash = plan_hash(field_plan)
        item.field_plan = field_plan
        item.handoff_reasons = reasons
        item.final_summary = adapter.request_approval(
            snapshot=snapshot,
            field_plan=field_plan,
            packet=packet,
        )
        item.inspected_at = now
        item.updated_at = now
        item.current_authorization_id = None
        if reasons:
            item.status = AtsSessionStatus.NEEDS_USER.value
            self.session.commit()
            self._open_ats_blocker(
                user_id=user_id,
                attempt_id=item.attempt_id,
                reasons=reasons,
            )
            item = self.get(user_id=user_id, session_id=item.id).session
            self._add_event(
                item,
                "AtsAssistanceNeedsUser",
                {"reason_codes": [str(reason.get("code")) for reason in reasons]},
            )
            self.session.commit()
            return self._view(item)

        self._resolve_ats_blockers(user_id=user_id, attempt_id=item.attempt_id)
        operations = self._materialize_operations(adapter.fill(field_plan), field_plan)
        prepared = await executor.prepare(
            url=item.application_url,
            provider=adapter.provider,
            operations=operations,
        )
        issues = adapter.verify(prepared, field_plan, snapshot.fingerprint)
        if issues:
            reasons = [
                {
                    "code": issue,
                    "category": "verification",
                    "message": "浏览器填写结果未通过确定性验证",
                }
                for issue in issues
            ]
            item.status = AtsSessionStatus.NEEDS_USER.value
            item.handoff_reasons = reasons
            item.updated_at = datetime.now(UTC)
            self.session.commit()
            self._open_ats_blocker(
                user_id=user_id,
                attempt_id=item.attempt_id,
                reasons=reasons,
            )
            return self._view(item)

        item.status = AtsSessionStatus.READY_FOR_APPROVAL.value
        item.handoff_reasons = []
        item.prepared_at = datetime.now(UTC)
        item.updated_at = item.prepared_at
        self.session.commit()
        self._ensure_ready(user_id=user_id, attempt_id=item.attempt_id)
        item = self.get(user_id=user_id, session_id=item.id).session
        self._add_event(
            item,
            "AtsAssistancePrepared",
            {
                "provider": item.provider,
                "fill_count": item.final_summary.get("fill_count", 0),
                "page_fingerprint": item.page_fingerprint,
                "plan_hash": item.plan_hash,
            },
        )
        self.session.commit()
        return self._view(item)

    def _bound_sources(self, *, user_id: str, attempt_id: str):
        attempt = ApplicationAttemptService(self.session).get(
            user_id=user_id,
            attempt_id=attempt_id,
        ).attempt
        if attempt.status in {
            AttemptStatus.SUBMITTED.value,
            AttemptStatus.ABANDONED.value,
        }:
            raise AtsAssistanceError(
                code="attempt_closed",
                message="已结束的投递尝试不能启动浏览器辅助",
            )
        revision_view = ApplicationPacketService(self.session).get_revision(
            user_id=user_id,
            revision_id=attempt.packet_revision_id,
        )
        revision = revision_view.revision
        if revision.status != PacketStatus.APPROVED.value or revision_view.source_changed:
            raise AtsAssistanceError(
                code="packet_no_longer_approved",
                message="投递包已失效或来源发生变化",
                details={"source_change_codes": revision_view.source_change_codes},
            )
        if (
            revision.id != attempt.packet_revision_id
            or revision.application_id != attempt.application_id
            or revision.job_posting_id != attempt.job_posting_id
        ):
            raise AtsAssistanceError(
                code="ats_binding_mismatch",
                message="Attempt、岗位和投递包版本绑定不一致",
            )
        return attempt, revision

    def _ensure_in_progress(self, *, user_id: str, attempt_id: str) -> None:
        service = ApplicationAttemptService(self.session)
        attempt = service.get(user_id=user_id, attempt_id=attempt_id).attempt
        status = AttemptStatus(attempt.status)
        if status in {AttemptStatus.CREATED, AttemptStatus.FAILED}:
            service.transition(
                user_id=user_id,
                attempt_id=attempt_id,
                target_status=AttemptStatus.FORM_IN_PROGRESS,
            )

    def _ensure_ready(self, *, user_id: str, attempt_id: str) -> None:
        service = ApplicationAttemptService(self.session)
        status = AttemptStatus(
            service.get(user_id=user_id, attempt_id=attempt_id).attempt.status
        )
        if status in {AttemptStatus.NEEDS_USER, AttemptStatus.BLOCKED}:
            self._resolve_ats_blockers(user_id=user_id, attempt_id=attempt_id)
            status = AttemptStatus(
                service.get(user_id=user_id, attempt_id=attempt_id).attempt.status
            )
        if status is AttemptStatus.FORM_IN_PROGRESS:
            service.transition(
                user_id=user_id,
                attempt_id=attempt_id,
                target_status=AttemptStatus.READY_TO_SUBMIT,
            )
        elif status is not AttemptStatus.READY_TO_SUBMIT:
            raise AtsAssistanceError(
                code="attempt_not_ready",
                message="投递尝试状态不允许进入 ATS 待授权阶段",
            )

    def _open_ats_blocker(
        self,
        *,
        user_id: str,
        attempt_id: str,
        reasons: list[dict[str, Any]],
    ) -> None:
        codes = sorted({str(reason.get("code")) for reason in reasons})
        ApplicationAttemptService(self.session).add_blocker(
            user_id=user_id,
            attempt_id=attempt_id,
            category="ats_assistance",
            observation=f"ATS 辅助暂停：{', '.join(codes)}",
            stop_reason="需要用户确认敏感字段、补充已批准材料或完成人工验证",
            retryable=True,
            next_strategy="完成页面要求后重新检查 ATS 会话",
            required_user_action="查看跟进原因并明确确认或人工接管",
        )

    def _resolve_ats_blockers(self, *, user_id: str, attempt_id: str) -> None:
        blockers = list(
            self.session.scalars(
                select(ApplicationBlocker).where(
                    ApplicationBlocker.user_id == user_id,
                    ApplicationBlocker.attempt_id == attempt_id,
                    ApplicationBlocker.category == "ats_assistance",
                    ApplicationBlocker.status == BlockerStatus.OPEN.value,
                )
            ).all()
        )
        service = ApplicationAttemptService(self.session)
        for blocker in blockers:
            service.resolve_blocker(
                user_id=user_id,
                attempt_id=attempt_id,
                blocker_id=blocker.id,
            )

    def _materialize_operations(
        self,
        operations: list[AtsFillOperation],
        field_plan: list[dict[str, Any]],
    ) -> list[AtsFillOperation]:
        source_by_key = {
            str(item.get("field_key")): str(item.get("source") or "")
            for item in field_plan
        }
        materialized: list[AtsFillOperation] = []
        for operation in operations:
            if source_by_key.get(operation.field_key) != "resume_snapshot":
                materialized.append(operation)
                continue
            asset = self.session.get(ResumeAsset, operation.value)
            if asset is None:
                raise AtsAssistanceError(
                    code="resume_asset_missing",
                    message="投递包绑定的简历文件不存在",
                )
            root = Path(get_settings().private_storage_dir).resolve()
            target = (root / asset.storage_key).resolve()
            if root != target and root not in target.parents:
                raise AtsAssistanceError(
                    code="resume_storage_path_invalid",
                    message="简历文件路径超出私密存储目录",
                )
            materialized.append(
                AtsFillOperation(
                    field_key=operation.field_key,
                    selector=operation.selector,
                    input_type=operation.input_type,
                    value=str(target),
                )
            )
        return materialized

    def _validate_authorization(
        self,
        *,
        item: AtsAssistanceSession,
        user_id: str,
        token: str,
    ) -> AtsSubmissionAuthorization:
        if item.status != AtsSessionStatus.AUTHORIZED.value:
            raise AtsAssistanceError(
                code="ats_session_not_authorized",
                message="ATS 会话没有有效的一次性提交授权",
            )
        authorization = self.session.scalar(
            select(AtsSubmissionAuthorization).where(
                AtsSubmissionAuthorization.id == item.current_authorization_id,
                AtsSubmissionAuthorization.user_id == user_id,
                AtsSubmissionAuthorization.session_id == item.id,
                AtsSubmissionAuthorization.token_hash == self._hash_text(token),
            )
        )
        if authorization is None:
            raise AtsAssistanceError(
                code="invalid_ats_authorization",
                message="一次性提交授权无效",
            )
        if authorization.used_at is not None:
            raise AtsAssistanceError(
                code="ats_authorization_already_used",
                message="一次性提交授权已经使用",
            )
        if authorization.revoked_at is not None:
            raise AtsAssistanceError(
                code="ats_authorization_revoked",
                message="一次性提交授权已经撤销",
            )
        if self._as_utc(authorization.expires_at) <= datetime.now(UTC):
            raise AtsAssistanceError(
                code="ats_authorization_expired",
                message="一次性提交授权已经过期",
            )
        if authorization.binding_hash != self._binding_hash(item):
            raise AtsAssistanceError(
                code="ats_authorization_binding_changed",
                message="岗位、URL、页面或投递包绑定已经变化",
            )
        return authorization

    def _mark_submission_unverified(
        self,
        *,
        user_id: str,
        item: AtsAssistanceSession,
        code: str,
    ) -> None:
        item = self.get(user_id=user_id, session_id=item.id).session
        now = datetime.now(UTC)
        item.status = AtsSessionStatus.FAILED.value
        item.failed_at = now
        item.updated_at = now
        item.handoff_reasons = [
            {
                "code": code,
                "category": "submission",
                "message": "无法验证是否提交成功，请在官网人工核对，禁止直接重试提交",
            }
        ]
        self._add_event(
            item,
            "AtsSubmissionUnverified",
            {"failure_code": code},
        )
        self.session.commit()
        self._open_ats_blocker(
            user_id=user_id,
            attempt_id=item.attempt_id,
            reasons=item.handoff_reasons,
        )

    def _view(self, item: AtsAssistanceSession) -> AtsSessionView:
        authorization = (
            self.session.get(
                AtsSubmissionAuthorization,
                item.current_authorization_id,
            )
            if item.current_authorization_id
            else None
        )
        return AtsSessionView(session=item, authorization=authorization)

    @staticmethod
    def _packet_payload(revision) -> dict[str, Any]:
        return {
            "id": revision.id,
            "job_snapshot": revision.job_snapshot,
            "profile_snapshot": revision.profile_snapshot,
            "resume_snapshot": revision.resume_snapshot,
            "form_answer_snapshots": revision.form_answer_snapshots,
            "open_questions": revision.open_questions,
        }

    @staticmethod
    async def _inspect(
        executor: AtsBrowserExecutor,
        url: str,
    ) -> AtsPageSnapshot:
        try:
            return await executor.inspect(url)
        except AtsBrowserError as error:
            raise AtsAssistanceError(code=error.code, message=str(error)) from error

    def _detect(self, snapshot: AtsPageSnapshot) -> AtsAdapter:
        try:
            return self.registry.detect(snapshot)
        except AtsAdapterError as error:
            raise AtsAssistanceError(code=error.code, message=str(error)) from error

    @staticmethod
    def _require_bound_url(actual: str, expected: str) -> None:
        if AtsAssistanceService._normalize_url(actual) != AtsAssistanceService._normalize_url(
            expected
        ):
            raise AtsAssistanceError(
                code="ats_url_binding_changed",
                message="ATS 最终地址与 Attempt 绑定地址不一致",
            )

    @staticmethod
    def _normalize_url(value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
            raise AtsAssistanceError(
                code="invalid_application_url",
                message="ATS 地址必须是 HTTP(S) URL",
            )
        path = parts.path or "/"
        if path != "/":
            path = path.rstrip("/")
        return urlunsplit(
            (parts.scheme.casefold(), parts.netloc.casefold(), path, parts.query, "")
        )

    @staticmethod
    def _binding_hash(item: AtsAssistanceSession) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "user_id": item.user_id,
                    "session_id": item.id,
                    "attempt_id": item.attempt_id,
                    "job_posting_id": item.job_posting_id,
                    "packet_revision_id": item.packet_revision_id,
                    "application_url": item.application_url,
                    "provider": item.provider,
                    "page_fingerprint": item.page_fingerprint,
                    "plan_hash": item.plan_hash,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _add_event(
        self,
        item: AtsAssistanceSession,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.session.add(
            DomainEvent(
                id=generate_domain_event_id(),
                user_id=item.user_id,
                entity_type="application",
                entity_id=item.application_id,
                event_type=event_type,
                payload={
                    "ats_session_id": item.id,
                    "attempt_id": item.attempt_id,
                    "packet_revision_id": item.packet_revision_id,
                    "job_posting_id": item.job_posting_id,
                    **payload,
                },
            )
        )

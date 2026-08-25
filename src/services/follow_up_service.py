from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.domain.application import (
    ApplicationStatus,
    DomainEvent,
    generate_domain_event_id,
)
from src.domain.follow_up import (
    FOLLOW_UP_TRANSITIONS,
    FollowUpEffectiveStatus,
    FollowUpEventType,
    FollowUpStatus,
    FollowUpTask,
    generate_follow_up_id,
)
from src.services.application_service import ApplicationService

FollowUpViewName = Literal[
    "all",
    "today",
    "overdue",
    "next_7_days",
    "next_30_days",
]

ACTIVE_APPLICATION_STATUSES = {
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.ASSESSMENT,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
}


class FollowUpError(RuntimeError):
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


class FollowUpNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class FollowUpTaskView:
    task: FollowUpTask
    effective_status: FollowUpEffectiveStatus
    is_overdue: bool
    local_scheduled_at: datetime


@dataclass(frozen=True)
class FollowUpCreation:
    view: FollowUpTaskView
    created: bool


@dataclass(frozen=True)
class FollowUpSummary:
    timezone: str
    generated_at: datetime
    total_pending: int
    today: int
    overdue: int
    next_7_days: int
    next_30_days: int


class FollowUpService:
    """Own manual follow-up tasks without treating reminders as application facts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        user_id: str,
        application_id: str,
        event_type: FollowUpEventType,
        title: str,
        scheduled_at: datetime,
        timezone: str,
        duration_minutes: int | None,
        all_day: bool,
        contact_name: str | None,
        contact_detail: str | None,
        channel: str | None,
        next_action: str,
        notes: str | None,
        idempotency_key: str | None = None,
    ) -> FollowUpCreation:
        application_view = ApplicationService(self.session).get_application(
            user_id=user_id,
            application_id=application_id,
        )
        application_status = ApplicationStatus(application_view.application.status)
        if application_status not in ACTIVE_APPLICATION_STATUSES:
            raise FollowUpError(
                code="application_not_followable",
                message="只有已投递且仍可跟进的申请可以创建任务",
                details={"application_status": application_status.value},
            )
        zone = self._zone(timezone)
        scheduled_utc = self._as_utc(scheduled_at, default_zone=zone)
        normalized_title = self._required_text(title, field="title")
        normalized_action = self._required_text(next_action, field="next_action")
        resolved_key = (idempotency_key or self._idempotency_key(
            user_id=user_id,
            application_id=application_id,
            event_type=event_type,
            title=normalized_title,
            scheduled_at=scheduled_utc,
        )).strip()

        existing = self.session.scalar(
            select(FollowUpTask).where(
                FollowUpTask.user_id == user_id,
                FollowUpTask.idempotency_key == resolved_key,
            )
        )
        if existing is not None:
            return FollowUpCreation(view=self._view(existing), created=False)

        task = FollowUpTask(
            id=generate_follow_up_id(),
            user_id=user_id,
            application_id=application_id,
            job_posting_id=application_view.posting.id,
            event_type=event_type.value,
            title=normalized_title,
            scheduled_at=scheduled_utc,
            timezone=zone.key,
            duration_minutes=duration_minutes,
            all_day=all_day,
            contact_name=self._optional_text(contact_name),
            contact_detail=self._optional_text(contact_detail),
            channel=self._optional_text(channel),
            next_action=normalized_action,
            notes=self._optional_multiline(notes),
            status=FollowUpStatus.PENDING.value,
            idempotency_key=resolved_key,
        )
        self.session.add(task)
        self._add_event(
            user_id=user_id,
            application_id=application_id,
            event_type="FollowUpTaskCreated",
            payload=self._event_payload(task, status=FollowUpStatus.PENDING),
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(FollowUpTask).where(
                    FollowUpTask.user_id == user_id,
                    FollowUpTask.application_id == application_id,
                    FollowUpTask.event_type == event_type.value,
                    FollowUpTask.scheduled_at == scheduled_utc,
                    FollowUpTask.title == normalized_title,
                )
            )
            if existing is None:
                raise
            return FollowUpCreation(view=self._view(existing), created=False)
        return FollowUpCreation(
            view=self.get(user_id=user_id, task_id=task.id),
            created=True,
        )

    def list(
        self,
        *,
        user_id: str,
        view: FollowUpViewName = "all",
        timezone: str = "Asia/Shanghai",
        application_id: str | None = None,
        now: datetime | None = None,
    ) -> list[FollowUpTaskView]:
        zone = self._zone(timezone)
        current = self._as_utc(now or datetime.now(UTC))
        if application_id is not None:
            ApplicationService(self.session).get_application(
                user_id=user_id,
                application_id=application_id,
            )
        statement = select(FollowUpTask).where(FollowUpTask.user_id == user_id)
        if application_id is not None:
            statement = statement.where(
                FollowUpTask.application_id == application_id
            )
        tasks = list(
            self.session.scalars(
                statement.order_by(
                    FollowUpTask.scheduled_at.asc(),
                    FollowUpTask.id.asc(),
                )
            ).all()
        )
        task_views = [self._view(task, now=current) for task in tasks]
        if view == "all":
            return task_views

        local_now = current.astimezone(zone)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(UTC)
        tomorrow_utc = (start_local + timedelta(days=1)).astimezone(UTC)
        seven_day_end = (start_local + timedelta(days=7)).astimezone(UTC)
        thirty_day_end = (start_local + timedelta(days=30)).astimezone(UTC)

        def pending(item: FollowUpTaskView) -> bool:
            return item.task.status == FollowUpStatus.PENDING.value

        if view == "today":
            return [
                item
                for item in task_views
                if pending(item)
                and start_utc <= self._as_utc(item.task.scheduled_at) < tomorrow_utc
            ]
        if view == "overdue":
            return [item for item in task_views if pending(item) and item.is_overdue]
        if view == "next_7_days":
            return [
                item
                for item in task_views
                if pending(item)
                and current <= self._as_utc(item.task.scheduled_at) < seven_day_end
            ]
        if view == "next_30_days":
            return [
                item
                for item in task_views
                if pending(item)
                and current <= self._as_utc(item.task.scheduled_at) < thirty_day_end
            ]
        raise FollowUpError(
            code="invalid_follow_up_view",
            message="跟进视图不存在",
        )

    def summary(
        self,
        *,
        user_id: str,
        timezone: str = "Asia/Shanghai",
        now: datetime | None = None,
    ) -> FollowUpSummary:
        current = self._as_utc(now or datetime.now(UTC))
        all_items = self.list(
            user_id=user_id,
            view="all",
            timezone=timezone,
            now=current,
        )
        return FollowUpSummary(
            timezone=self._zone(timezone).key,
            generated_at=current,
            total_pending=sum(
                item.task.status == FollowUpStatus.PENDING.value
                for item in all_items
            ),
            today=len(
                self.list(
                    user_id=user_id,
                    view="today",
                    timezone=timezone,
                    now=current,
                )
            ),
            overdue=len(
                self.list(
                    user_id=user_id,
                    view="overdue",
                    timezone=timezone,
                    now=current,
                )
            ),
            next_7_days=len(
                self.list(
                    user_id=user_id,
                    view="next_7_days",
                    timezone=timezone,
                    now=current,
                )
            ),
            next_30_days=len(
                self.list(
                    user_id=user_id,
                    view="next_30_days",
                    timezone=timezone,
                    now=current,
                )
            ),
        )

    def get(
        self,
        *,
        user_id: str,
        task_id: str,
        now: datetime | None = None,
    ) -> FollowUpTaskView:
        task = self.session.scalar(
            select(FollowUpTask).where(
                FollowUpTask.id == task_id,
                FollowUpTask.user_id == user_id,
            )
        )
        if task is None:
            raise FollowUpNotFoundError(task_id)
        return self._view(task, now=now)

    def edit(
        self,
        *,
        user_id: str,
        task_id: str,
        updates: dict[str, Any],
    ) -> FollowUpTaskView:
        view = self.get(user_id=user_id, task_id=task_id)
        task = view.task
        if task.status != FollowUpStatus.PENDING.value:
            raise FollowUpError(
                code="follow_up_task_immutable",
                message="已完成或已取消的跟进任务不能再编辑",
            )
        allowed_fields = {
            "event_type",
            "title",
            "scheduled_at",
            "timezone",
            "duration_minutes",
            "all_day",
            "contact_name",
            "contact_detail",
            "channel",
            "next_action",
            "notes",
        }
        if not updates or not set(updates).issubset(allowed_fields):
            raise FollowUpError(
                code="invalid_follow_up_update",
                message="没有可更新的跟进任务字段",
            )

        zone = self._zone(str(updates.get("timezone", task.timezone)))
        changed_fields: list[str] = []
        for field, value in updates.items():
            if field == "event_type":
                value = (
                    value.value
                    if isinstance(value, FollowUpEventType)
                    else FollowUpEventType(value).value
                )
            elif field == "title":
                value = self._required_text(value, field="title")
            elif field == "next_action":
                value = self._required_text(value, field="next_action")
            elif field == "scheduled_at":
                value = self._as_utc(value, default_zone=zone)
            elif field == "timezone":
                value = zone.key
            elif field == "notes":
                value = self._optional_multiline(value)
            elif field in {"contact_name", "contact_detail", "channel"}:
                value = self._optional_text(value)
            if getattr(task, field) != value:
                setattr(task, field, value)
                changed_fields.append(field)
        if not changed_fields:
            return view
        task.updated_at = datetime.now(UTC)
        self._add_event(
            user_id=user_id,
            application_id=task.application_id,
            event_type="FollowUpTaskUpdated",
            payload={
                **self._event_payload(task, status=FollowUpStatus.PENDING),
                "changed_fields": sorted(changed_fields),
            },
        )
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise FollowUpError(
                code="duplicate_follow_up_task",
                message="相同申请、类型、时间和标题的任务已经存在",
            ) from error
        return self.get(user_id=user_id, task_id=task.id)

    def complete(self, *, user_id: str, task_id: str) -> FollowUpTaskView:
        return self._transition(
            user_id=user_id,
            task_id=task_id,
            target_status=FollowUpStatus.COMPLETED,
        )

    def cancel(self, *, user_id: str, task_id: str) -> FollowUpTaskView:
        return self._transition(
            user_id=user_id,
            task_id=task_id,
            target_status=FollowUpStatus.CANCELLED,
        )

    def _transition(
        self,
        *,
        user_id: str,
        task_id: str,
        target_status: FollowUpStatus,
    ) -> FollowUpTaskView:
        view = self.get(user_id=user_id, task_id=task_id)
        task = view.task
        current_status = FollowUpStatus(task.status)
        if current_status is target_status:
            return view
        if target_status not in FOLLOW_UP_TRANSITIONS[current_status]:
            raise FollowUpError(
                code="invalid_follow_up_transition",
                message=(
                    f"跟进任务不能从 {current_status.value} "
                    f"进入 {target_status.value}"
                ),
                details={
                    "current": current_status.value,
                    "target": target_status.value,
                    "allowed": sorted(
                        item.value for item in FOLLOW_UP_TRANSITIONS[current_status]
                    ),
                },
            )
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "status": target_status.value,
            "updated_at": now,
        }
        if target_status is FollowUpStatus.COMPLETED:
            values["completed_at"] = now
        else:
            values["cancelled_at"] = now
        try:
            changed = self.session.execute(
                update(FollowUpTask)
                .where(
                    FollowUpTask.id == task.id,
                    FollowUpTask.user_id == user_id,
                    FollowUpTask.status == FollowUpStatus.PENDING.value,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if int(changed.rowcount or 0) != 1:
                raise FollowUpError(
                    code="concurrent_follow_up_update",
                    message="跟进任务状态已被其他请求修改",
                )
            self._add_event(
                user_id=user_id,
                application_id=task.application_id,
                event_type=(
                    "FollowUpTaskCompleted"
                    if target_status is FollowUpStatus.COMPLETED
                    else "FollowUpTaskCancelled"
                ),
                payload=self._event_payload(task, status=target_status),
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            current = self.session.scalar(
                select(FollowUpTask).where(
                    FollowUpTask.id == task_id,
                    FollowUpTask.user_id == user_id,
                )
            )
            if current is not None and current.status == target_status.value:
                return self._view(current)
            raise
        return self.get(user_id=user_id, task_id=task.id)

    def _view(
        self,
        task: FollowUpTask,
        *,
        now: datetime | None = None,
    ) -> FollowUpTaskView:
        current = self._as_utc(now or datetime.now(UTC))
        scheduled = self._as_utc(task.scheduled_at)
        base_status = FollowUpStatus(task.status)
        is_overdue = (
            base_status is FollowUpStatus.PENDING and scheduled < current
        )
        effective_status = (
            FollowUpEffectiveStatus.OVERDUE
            if is_overdue
            else FollowUpEffectiveStatus(base_status.value)
        )
        return FollowUpTaskView(
            task=task,
            effective_status=effective_status,
            is_overdue=is_overdue,
            local_scheduled_at=scheduled.astimezone(self._zone(task.timezone)),
        )

    @staticmethod
    def _zone(value: str) -> ZoneInfo:
        try:
            return ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise FollowUpError(
                code="invalid_timezone",
                message="时区必须是有效的 IANA timezone",
                details={"timezone": value},
            ) from error

    @staticmethod
    def _as_utc(
        value: datetime,
        *,
        default_zone: ZoneInfo | None = None,
    ) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=default_zone or UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _required_text(value: str, *, field: str) -> str:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            raise FollowUpError(
                code="invalid_follow_up_field",
                message=f"{field} 不能为空",
                details={"field": field},
            )
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split()).strip()
        return normalized or None

    @staticmethod
    def _optional_multiline(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "\n".join(
            line.rstrip() for line in value.strip().splitlines()
        ).strip()
        return normalized or None

    @staticmethod
    def _idempotency_key(
        *,
        user_id: str,
        application_id: str,
        event_type: FollowUpEventType,
        title: str,
        scheduled_at: datetime,
    ) -> str:
        payload = {
            "user_id": user_id,
            "application_id": application_id,
            "event_type": event_type.value,
            "title": title,
            "scheduled_at": scheduled_at.isoformat(),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _event_payload(
        task: FollowUpTask,
        *,
        status: FollowUpStatus,
    ) -> dict[str, Any]:
        scheduled = FollowUpService._as_utc(task.scheduled_at)
        return {
            "follow_up_task_id": task.id,
            "job_posting_id": task.job_posting_id,
            "event_type": task.event_type,
            "scheduled_at": scheduled.isoformat(),
            "timezone": task.timezone,
            "status": status.value,
        }

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

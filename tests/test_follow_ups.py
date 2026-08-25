from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.application import (
    Application,
    ApplicationStatus,
    CandidateJob,
    CandidateStatus,
    DomainEvent,
)
from src.domain.follow_up import FollowUpEventType
from src.domain.job import JobPosting
from src.main import app
from src.services.follow_up_service import FollowUpService


def _seed_application(
    session: Session,
    *,
    user_id: str,
    status: ApplicationStatus = ApplicationStatus.SUBMITTED,
) -> str:
    suffix = hashlib.sha256(user_id.encode()).hexdigest()[:12]
    job_id = f"job_follow_{suffix}"
    candidate_id = f"candidate_follow_{suffix}"
    application_id = f"application_follow_{suffix}"
    content = "Example role used to verify follow-up calendar behavior."
    session.add_all(
        [
            JobPosting(
                id=job_id,
                source_url="https://careers.example.com/jobs/follow-up-role",
                source_type="manual_text",
                source_id=f"source_follow_{suffix}",
                source_job_id=f"role_follow_{suffix}",
                company="Calendar Labs",
                title="Reliability Engineer",
                locations=["Shanghai"],
                job_type="full_time",
                raw_content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                retrieved_at=datetime.now(UTC),
                trace_id=f"trace_follow_{suffix}",
            ),
            CandidateJob(
                id=candidate_id,
                user_id=user_id,
                job_posting_id=job_id,
                status=CandidateStatus.CONVERTED.value,
            ),
            Application(
                id=application_id,
                candidate_job_id=candidate_id,
                status=status.value,
            ),
        ]
    )
    session.commit()
    return application_id


def _create_task(
    service: FollowUpService,
    *,
    user_id: str,
    application_id: str,
    title: str,
    scheduled_at: datetime,
    event_type: FollowUpEventType = FollowUpEventType.INTERVIEW,
) -> str:
    return service.create(
        user_id=user_id,
        application_id=application_id,
        event_type=event_type,
        title=title,
        scheduled_at=scheduled_at,
        timezone="Asia/Shanghai",
        duration_minutes=60,
        all_day=False,
        contact_name="Recruiter Chen",
        contact_detail="private@example.com",
        channel="Tencent Meeting",
        next_action="准备面试材料并准时参加",
        notes="这段私密备注不应写入 DomainEvent。",
    ).view.task.id


def test_follow_up_views_respect_timezone_and_open_boundaries(
    db_session: Session,
) -> None:
    user_id = "follow-up-time-owner"
    application_id = _seed_application(db_session, user_id=user_id)
    service = FollowUpService(db_session)
    fixed_now = datetime.fromisoformat("2026-08-25T09:00:00+08:00")
    task_ids = {
        "previous": _create_task(
            service,
            user_id=user_id,
            application_id=application_id,
            title="前一日截止",
            scheduled_at=datetime.fromisoformat("2026-08-24T23:59:00+08:00"),
        ),
        "today_past": _create_task(
            service,
            user_id=user_id,
            application_id=application_id,
            title="今日已逾期",
            scheduled_at=datetime.fromisoformat("2026-08-25T08:00:00+08:00"),
        ),
        "today_future": _create_task(
            service,
            user_id=user_id,
            application_id=application_id,
            title="今日待办",
            scheduled_at=datetime.fromisoformat("2026-08-25T18:00:00+08:00"),
        ),
        "seven_inside": _create_task(
            service,
            user_id=user_id,
            application_id=application_id,
            title="七日边界内",
            scheduled_at=datetime.fromisoformat("2026-08-31T23:59:00+08:00"),
        ),
        "seven_outside": _create_task(
            service,
            user_id=user_id,
            application_id=application_id,
            title="七日右边界",
            scheduled_at=datetime.fromisoformat("2026-09-01T00:00:00+08:00"),
        ),
        "thirty_inside": _create_task(
            service,
            user_id=user_id,
            application_id=application_id,
            title="三十日边界内",
            scheduled_at=datetime.fromisoformat("2026-09-23T23:59:00+08:00"),
        ),
        "thirty_outside": _create_task(
            service,
            user_id=user_id,
            application_id=application_id,
            title="三十日右边界",
            scheduled_at=datetime.fromisoformat("2026-09-24T00:00:00+08:00"),
        ),
    }

    today = service.list(
        user_id=user_id,
        view="today",
        timezone="Asia/Shanghai",
        now=fixed_now,
    )
    overdue = service.list(
        user_id=user_id,
        view="overdue",
        timezone="Asia/Shanghai",
        now=fixed_now,
    )
    next_seven = service.list(
        user_id=user_id,
        view="next_7_days",
        timezone="Asia/Shanghai",
        now=fixed_now,
    )
    next_thirty = service.list(
        user_id=user_id,
        view="next_30_days",
        timezone="Asia/Shanghai",
        now=fixed_now,
    )

    assert {item.task.id for item in today} == {
        task_ids["today_past"],
        task_ids["today_future"],
    }
    assert {item.task.id for item in overdue} == {
        task_ids["previous"],
        task_ids["today_past"],
    }
    assert {item.task.id for item in next_seven} == {
        task_ids["today_future"],
        task_ids["seven_inside"],
    }
    assert task_ids["seven_outside"] not in {
        item.task.id for item in next_seven
    }
    assert task_ids["thirty_inside"] in {
        item.task.id for item in next_thirty
    }
    assert task_ids["thirty_outside"] not in {
        item.task.id for item in next_thirty
    }
    today_future = service.get(
        user_id=user_id,
        task_id=task_ids["today_future"],
        now=fixed_now,
    )
    assert today_future.local_scheduled_at.isoformat() == "2026-08-25T18:00:00+08:00"
    assert today_future.task.scheduled_at.replace(tzinfo=UTC).isoformat() == (
        "2026-08-25T10:00:00+00:00"
    )


@pytest.mark.asyncio
async def test_follow_up_api_crud_idempotency_ownership_and_timeline(
    db_session: Session,
) -> None:
    user_id = "follow-up-api-owner"
    application_id = _seed_application(db_session, user_id=user_id)
    headers = {"X-User-ID": user_id}
    payload = {
        "event_type": "INTERVIEW",
        "title": "技术二面",
        "scheduled_at": "2027-08-25T10:30:00",
        "timezone": "Asia/Shanghai",
        "duration_minutes": 60,
        "contact_name": "陈老师",
        "contact_detail": "private@example.com",
        "channel": "腾讯会议",
        "next_action": "准备系统设计案例",
        "notes": "只在任务详情中保存",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/applications/{application_id}/follow-ups",
            headers=headers,
            json=payload,
        )
        duplicate = await client.post(
            f"/api/applications/{application_id}/follow-ups",
            headers=headers,
            json=payload,
        )
        task_id = created.json()["id"]
        updated = await client.patch(
            f"/api/follow-ups/{task_id}",
            headers=headers,
            json={
                "title": "技术终面",
                "next_action": "准备系统设计与项目复盘",
            },
        )
        forbidden = await client.get(
            f"/api/follow-ups/{task_id}",
            headers={"X-User-ID": "another-user"},
        )
        listed = await client.get(
            "/api/follow-ups?view=next_30_days&timezone=Asia/Shanghai",
            headers=headers,
        )
        summary = await client.get(
            "/api/follow-ups/summary?timezone=Asia/Shanghai",
            headers=headers,
        )
        completed = await client.post(
            f"/api/follow-ups/{task_id}/complete", headers=headers
        )
        repeated = await client.post(
            f"/api/follow-ups/{task_id}/complete", headers=headers
        )
        invalid_cancel = await client.post(
            f"/api/follow-ups/{task_id}/cancel", headers=headers
        )
        immutable_edit = await client.patch(
            f"/api/follow-ups/{task_id}",
            headers=headers,
            json={"notes": "不能修改终态"},
        )
        timeline = await client.get(
            f"/api/applications/{application_id}/events", headers=headers
        )

    assert created.status_code == 201, created.text
    assert created.json()["local_scheduled_at"].startswith("2027-08-25T10:30:00")
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == task_id
    assert updated.status_code == 200
    assert updated.json()["title"] == "技术终面"
    assert forbidden.status_code == 404
    assert listed.status_code == 200
    assert listed.json() == []
    assert summary.status_code == 200
    assert summary.json()["total_pending"] == 1
    assert completed.json()["status"] == "COMPLETED"
    assert repeated.json()["id"] == task_id
    assert invalid_cancel.status_code == 409
    assert invalid_cancel.json()["error"]["code"] == "invalid_follow_up_transition"
    assert immutable_edit.status_code == 409
    event_types = [item["event_type"] for item in timeline.json()]
    assert event_types == [
        "FollowUpTaskCreated",
        "FollowUpTaskUpdated",
        "FollowUpTaskCompleted",
    ]
    for event in timeline.json():
        assert "notes" not in event["payload"]
        assert "contact_name" not in event["payload"]
        assert "contact_detail" not in event["payload"]
        assert "next_action" not in event["payload"]


@pytest.mark.asyncio
async def test_follow_up_rejects_preparing_application_and_terminal_reversal(
    db_session: Session,
) -> None:
    preparing_user = "follow-up-preparing-owner"
    preparing_application = _seed_application(
        db_session,
        user_id=preparing_user,
        status=ApplicationStatus.PREPARING,
    )
    active_user = "follow-up-cancel-owner"
    active_application = _seed_application(db_session, user_id=active_user)
    transport = httpx.ASGITransport(app=app)
    payload = {
        "event_type": "ASSESSMENT",
        "title": "在线测评",
        "scheduled_at": "2027-01-10T20:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "next_action": "完成在线测评",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(
            f"/api/applications/{preparing_application}/follow-ups",
            headers={"X-User-ID": preparing_user},
            json=payload,
        )
        created = await client.post(
            f"/api/applications/{active_application}/follow-ups",
            headers={"X-User-ID": active_user},
            json=payload,
        )
        cancelled = await client.post(
            f"/api/follow-ups/{created.json()['id']}/cancel",
            headers={"X-User-ID": active_user},
        )
        invalid_complete = await client.post(
            f"/api/follow-ups/{created.json()['id']}/complete",
            headers={"X-User-ID": active_user},
        )
        cross_user_application = await client.get(
            f"/api/applications/{active_application}/follow-ups",
            headers={"X-User-ID": preparing_user},
        )
        invalid_timezone = await client.get(
            "/api/follow-ups?timezone=Not/A_Timezone",
            headers={"X-User-ID": active_user},
        )

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "application_not_followable"
    assert cancelled.json()["status"] == "CANCELLED"
    assert invalid_complete.status_code == 409
    assert cross_user_application.status_code == 404
    assert invalid_timezone.status_code == 422


def test_follow_up_duplicate_natural_identity_is_idempotent(db_session: Session) -> None:
    user_id = "follow-up-duplicate-owner"
    application_id = _seed_application(db_session, user_id=user_id)
    service = FollowUpService(db_session)
    scheduled = datetime.fromisoformat("2027-06-01T09:00:00+08:00")
    first = service.create(
        user_id=user_id,
        application_id=application_id,
        event_type=FollowUpEventType.WRITTEN_TEST,
        title="统一笔试",
        scheduled_at=scheduled,
        timezone="Asia/Shanghai",
        duration_minutes=90,
        all_day=False,
        contact_name=None,
        contact_detail=None,
        channel="在线平台",
        next_action="按时参加笔试",
        notes=None,
        idempotency_key="duplicate-request-one",
    )
    second = service.create(
        user_id=user_id,
        application_id=application_id,
        event_type=FollowUpEventType.WRITTEN_TEST,
        title="统一笔试",
        scheduled_at=scheduled,
        timezone="Asia/Shanghai",
        duration_minutes=120,
        all_day=False,
        contact_name=None,
        contact_detail=None,
        channel="更新后的平台",
        next_action="不同内容不应创建重复自然身份",
        notes=None,
        idempotency_key="duplicate-request-two",
    )

    events = list(
        db_session.scalars(
            select(DomainEvent).where(
                DomainEvent.user_id == user_id,
                DomainEvent.event_type == "FollowUpTaskCreated",
            )
        ).all()
    )
    assert first.created is True
    assert second.created is False
    assert second.view.task.id == first.view.task.id
    assert len(events) == 1


"""Discover employers without job preferences, then queue campus verification."""
import asyncio
import logging
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert

from src.config import get_settings
from src.domain.campaign import CampaignDiscoveryTask, identifier
from src.domain.company_source import ACCEPTED_COMPANY_STATUSES, DiscoveredCompany
from src.infrastructure.database import SessionLocal
from src.services.company_discovery_queue import create_company_discovery_agent

logger = logging.getLogger("jobflow.campaign_discovery")
TOPICS = ("互联网 软件 通信", "制造业 汽车 电子", "银行 证券 保险", "能源 电力 建筑",
          "消费品 零售 物流", "医疗 医药 生物", "国企 央企", "中小企业 专精特新")


class LostLease(RuntimeError):
    pass


def discovery_queries(year, cycle=0):
    # Rotate sectors, never import roles/cities from a personal search goal.
    topics = ["", *(TOPICS[(cycle * 3 + i) % len(TOPICS)] for i in range(3))]
    return [{"query": f"{year}届 秋季校园招聘 {topic} 企业 招聘官网 网申".strip(),
             "fallback": f"{year}届 校园招聘 {topic} 公司官网".strip(),
             "stage": "search", "attempts": 0} for topic in topics]


def task_for(session, user_id, year):
    return session.scalar(select(CampaignDiscoveryTask).where(
        CampaignDiscoveryTask.user_id == user_id, CampaignDiscoveryTask.year == year))


def enqueue_discovery(session, user_id, year):
    now = datetime.now(UTC)
    old = task_for(session, user_id, year)
    if old and old.status in {"queued", "running"}:
        return old
    if old and old.status == "waiting" and old.stage == "model_retry":
        return old  # Repeated clicks must not bypass backoff or reset its budget.
    state = deepcopy(old.state) if old else {}
    resuming = bool(old and old.status in {"blocked", "paused"})
    if resuming:
        for query in state["queries"]:
            if query["stage"] == "failed":
                query.update(stage="extract" if query.get("results") else "search", attempts=0)
        state["verification_attempts"] = {}
        if planner := state.get("planner"):
            # A user-requested retry gets a new execution budget while keeping
            # observed evidence, pending candidates and guarded task ownership.
            planner.update(status="active", steps=0, reads=0, search_count=0,
                           decision_failures=0, verification_attempts={}, verification_revisions={},
                           model_retries=0, model_retry_at=None, model_error=None,
                           model_retry_exhausted=False, invalid_actions=0, invalid_streak=0)
    else:
        cycle = state.get("cycle", -1) + 1
        previous_searches = [*state.get("previous_searches", []),
            *({"query": q["query"], "cycle": state.get("cycle", 0), "stage": q["stage"],
               "result_count": len(q.get("results", []))} for q in state.get("queries", [])
              if q.get("attempts") or q.get("results") or q["stage"] in {"done", "failed"})][-24:]
        backlog = list(session.scalars(select(DiscoveredCompany.id).where(
            DiscoveredCompany.user_id == user_id, DiscoveredCompany.status == "pending",
            DiscoveredCompany.id.in_(state.get("verify_ids", []))))) if old else []
        attempts = {key: value for key, value in state.get("verification_attempts", {}).items() if key in backlog}
        state = {"cycle": cycle, "queries": discovery_queries(year, cycle),
                 "verify_ids": backlog, "scheduled_ids": [], "verification_attempts": attempts,
                 "previous_searches": previous_searches}
    values = {"id": identifier(), "user_id": user_id, "year": year,
              "run_id": old.run_id if resuming else identifier(),
              "status": "queued", "stage": "search", "state": state,
              "lease_token": None, "lease_until": None, "next_run_at": now,
              "error": None, "updated_at": now}
    session.execute(insert(CampaignDiscoveryTask).values(**values).on_conflict_do_update(
        index_elements=["user_id", "year"], set_={k: v for k, v in values.items() if k != "id"},
        where=CampaignDiscoveryTask.status.not_in(["queued", "running"])))
    session.commit()
    session.expire_all()
    return task_for(session, user_id, year)


def discovery_summary(session, user_id, year):
    task = task_for(session, user_id, year)
    state = task.state if task else {}
    queries = state.get("queries", [])
    rows = list(session.scalars(select(DiscoveredCompany).where(
        DiscoveredCompany.user_id == user_id,
        DiscoveredCompany.id.in_(state.get("verify_ids", [])))))
    settings = get_settings()
    # Old saved tasks used "blocked/done" for a normal execution limit.
    limited = bool(task and task.status in {"blocked", "paused"}
                   and state.get("planner", {}).get("status") == "budget_exhausted")
    return {"enabled": settings.company_discovery_enabled and settings.structured_model_provider != "fake",
            "status": "paused" if limited else task.status if task else "idle",
            "stage": "budget_limit" if limited else task.stage if task else "search",
            "queries_completed": sum(q["stage"] in {"done", "failed"} for q in queries),
            "queries_total": len(queries), "companies_found": len(rows),
            "companies_verified": sum(r.status in ACCEPTED_COMPANY_STATUSES for r in rows),
            "companies_queued": len(state.get("scheduled_ids", [])),
            "pending_companies": [{"company": r.company, "reason": r.reason}
                                  for r in rows if r.status == "pending"],
            "model_retries": state.get("planner", {}).get("model_retries", 0),
            "next_run_at": task.next_run_at if task else None,
            "error": None if limited else task.error if task else None}


def _runtime(session, task, *, settings, on_event, checkpoint):
    from src.services.campaign_company_agent import CampaignCompanyAgent
    return create_company_discovery_agent(session, user_id=task.user_id, run_id=task.run_id,
        query=f"发现中国国内面向{task.year}届毕业生的秋季校园招聘公司，不限岗位方向和城市",
        settings=settings, on_event=on_event, checkpoint=checkpoint, agent_class=CampaignCompanyAgent,
        # Up to six suggestions from several pages take longer than one action
        # decision. Decisions retain their own 25-second bound.
        extraction_timeout=75)


async def run_discovery_step(session_factory=SessionLocal, *, settings=None, agent_factory=None, now=None):
    settings = settings or get_settings()
    if not settings.company_discovery_enabled or (settings.structured_model_provider == "fake" and agent_factory is None):
        return False
    from src.services.campaign_service import ensure_watch, utc

    now, token = now or datetime.now(UTC), uuid4().hex
    with session_factory() as session:
        available = or_(CampaignDiscoveryTask.status.in_(["queued", "waiting"]),
                        (CampaignDiscoveryTask.status == "running") & (CampaignDiscoveryTask.lease_until <= now))
        due = or_(CampaignDiscoveryTask.next_run_at.is_(None), CampaignDiscoveryTask.next_run_at <= now)
        task = session.scalar(select(CampaignDiscoveryTask).where(available, due)
                              .order_by(CampaignDiscoveryTask.updated_at).limit(1))
        if task is None:
            return False
        task_id, user_id, year, run_id = task.id, task.user_id, task.year, task.run_id
        claimed = session.execute(update(CampaignDiscoveryTask).where(
            CampaignDiscoveryTask.id == task_id, available, due).values(
                status="running", lease_token=token, lease_until=now + timedelta(minutes=3)),
            execution_options={"synchronize_session": False}).rowcount
        session.commit()
        if not claimed:
            return False
        session.refresh(task)
        state, agent = deepcopy(task.state), None

        def persist(**values):
            changed = session.execute(update(CampaignDiscoveryTask).where(
                CampaignDiscoveryTask.id == task_id, CampaignDiscoveryTask.user_id == user_id,
                CampaignDiscoveryTask.lease_token == token).values(
                    state=deepcopy(state), updated_at=datetime.now(UTC), **values),
                execution_options={"synchronize_session": False}).rowcount
            if not changed:
                session.rollback()
                raise LostLease()
            session.commit()

        def candidates():
            # Also recover candidates committed just before a restart/checkpoint.
            rows = list(session.scalars(select(DiscoveredCompany).where(
                DiscoveredCompany.user_id == user_id, or_(
                    DiscoveredCompany.id.in_(state.get("verify_ids", [])),
                    DiscoveredCompany.discovery_run_id == run_id))))
            state["verify_ids"] = list(dict.fromkeys([*state.get("verify_ids", []), *(r.id for r in rows)]))
            return rows

        current = next((q for q in state["queries"] if q["stage"] not in {"done", "failed"}), None)

        def checkpoint(evidence):
            if "planner" in state:
                state["planner"]["evidence"] = evidence
            elif current is not None and current["stage"] == "extract":
                current["evidence"] = evidence
            persist()

        def event(kind, data):
            state["events"] = [*state.get("events", []), {"kind": kind, **data}][-20:]

        try:
            persist()
            agent = (agent_factory or _runtime)(session, task, settings=settings, on_event=event, checkpoint=checkpoint)
            rows = candidates()
            ready = next((r for r in rows if r.status == "pending" and agent.due(r)
                          and state["verification_attempts"].get(r.id, 0) < 3), None)
            if hasattr(agent, "advance") and state.get("planner", {}).get("status", "active") == "active":
                persist(stage="agent")
                await asyncio.wait_for(agent.advance(state, rows), timeout=155)
            elif ready:
                persist(stage="verify")
                await agent.verify(ready)
                state["verification_attempts"][ready.id] = state["verification_attempts"].get(ready.id, 0) + 1
            elif current:
                stage = current["stage"]
                persist(stage=stage)
                try:
                    if stage == "search":
                        results = await agent.search(current["fallback"] if current["attempts"] else current["query"])
                        current["results"] = [{"source_url": r.source_url, "title_hint": r.title_hint,
                            "search_snippet": (r.search_snippet or "")[:1600]} for r in results]
                        current.update(stage="extract" if results else "done", attempts=0)
                        persist()
                    else:
                        from src.domain.discovery import LeadProvider
                        from src.services.lead_providers import LeadCandidate
                        agent.evidence_reader.restore(current.get("evidence", {}))
                        results = [LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT, discovered_at=now, **r)
                                   for r in current["results"]]
                        extracted = await agent.extract(results)
                        state["verify_ids"] = list(dict.fromkeys([*state["verify_ids"], *(r.id for r in extracted)]))
                        current.update(stage="done", attempts=0)
                        persist()
                except LostLease:
                    raise
                except Exception:  # noqa: BLE001 - one source must not stop other searches
                    session.rollback()
                    current["attempts"] += 1
                    if current["attempts"] >= (2 if stage == "search" else 3):
                        current["stage"] = "failed"
            session.expire_all()
            rows = candidates()
            persist()  # ownership check before scheduling any follow-up writes
            for row in rows:
                if row.status in ACCEPTED_COMPANY_STATUSES and row.id not in state["scheduled_ids"]:
                    watch = ensure_watch(session, user_id, row.id, year)
                    if watch.status not in {"queued", "running"}:
                        watch.status, watch.error, watch.next_check_at = "queued", None, datetime.now(UTC)
                    state["scheduled_ids"].append(row.id)
            unfinished = (state.get("planner", {}).get("status") == "active" or
                          any(q["stage"] not in {"done", "failed"} for q in state["queries"]))
            pending = [r for r in rows if r.status == "pending"]
            retryable = [r for r in pending if state["verification_attempts"].get(r.id, 0) < 3]
            next_at = datetime.now(UTC) + timedelta(seconds=3)
            if not unfinished and retryable:
                next_at = min(utc(r.last_checked_at) + timedelta(hours=min(24, max(1, r.attempts) * 2))
                              if r.last_checked_at else next_at for r in retryable)
            active = unfinished or bool(retryable)
            planner_failed = state.get("planner", {}).get("status") in {"failed", "budget_exhausted", "stalled"}
            blocked = bool(pending) or planner_failed or any(q["stage"] == "failed" for q in state["queries"])
            has_failures = planner_failed or any(q["stage"] == "failed" for q in state["queries"]) or any(r.attempts for r in pending)
            # Flush watches in the same guarded transaction as their scheduled IDs.
            session.flush()
            planner = state.get("planner", {})
            model_retry_at = planner.get("model_retry_at")
            if model_retry_at and planner.get("status") == "active":
                persist(status="waiting", stage="model_retry",
                        next_run_at=datetime.fromisoformat(model_retry_at), lease_token=None, lease_until=None,
                        error=f"模型服务暂时不可用，进度已保存，将自动进行第 {planner['model_retries']} 次重试。")
            elif planner.get("status") == "failed" and planner.get("model_error"):
                # Reaching the retry limit must not be undone by the separate
                # pending-company queue or its later cooldown wakeups.
                message = ("模型服务重试已达上限，进度已保存；服务恢复后可点击重试公司发现。"
                           if planner.get("model_retry_exhausted") else
                           "模型请求未成功，进度已保存；请检查模型配置或服务状态后重试。")
                persist(status="blocked", stage="model_error", next_run_at=None,
                        lease_token=None, lease_until=None, error=message)
            elif planner.get("status") == "stalled":
                persist(status="blocked", stage="action_error", next_run_at=None,
                        lease_token=None, lease_until=None,
                        error="公司发现多次未能纠正无效动作，已暂停并保存进度及纠正提示，可重试继续。")
            elif planner.get("status") == "budget_exhausted":
                persist(status="paused", stage="budget_limit", next_run_at=None,
                        lease_token=None, lease_until=None, error=None)
            else:
                persist(status="queued" if unfinished else "waiting" if retryable else "blocked" if blocked else "completed",
                    stage="agent" if state.get("planner", {}).get("status") == "active" else
                          next((q["stage"] for q in state["queries"] if q["stage"] not in {"done", "failed"}),
                               "verify" if pending else "done"),
                    next_run_at=next_at if active else None, lease_token=None, lease_until=None,
                    error="部分公司或搜索来源暂未核验完成，已保留进度。" if has_failures else None)
        except LostLease:
            session.rollback()
        except asyncio.CancelledError:
            session.rollback()
            try:
                retry_at = state.get("planner", {}).get("model_retry_at")
                persist(status="waiting" if retry_at else "queued",
                        stage="model_retry" if retry_at else task.stage,
                        lease_token=None, lease_until=None,
                        next_run_at=datetime.fromisoformat(retry_at) if retry_at else datetime.now(UTC))
            except LostLease:
                pass
            raise
        except Exception:  # noqa: BLE001 - preserve progress on unexpected provider failures
            session.rollback()
            logger.warning("campaign_company_discovery_failed")
            try:
                persist(status="blocked", error="公司发现未完成，可重试继续。", lease_token=None, lease_until=None)
            except LostLease:
                pass
        finally:
            if agent:
                await agent.aclose()
        return True


async def discovery_loop():
    while True:
        try:
            worked = await run_discovery_step()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - allow migrations or services to recover
            logger.warning("campaign_company_discovery_unavailable")
            worked = False
        await asyncio.sleep(1 if worked else 5)

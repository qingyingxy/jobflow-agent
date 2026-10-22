"""Persist and resume company discovery independently of foreground job searches."""
from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert

from src.config import get_settings
from src.domain.company_source import CompanyDiscoveryTask, DiscoveredCompany
from src.domain.search_goal import SearchGoal
from src.infrastructure.database import SessionLocal
from src.services.company_discovery import (
    CompanyDiscoveryAgent,
    list_discovered_companies,
)
from src.services.search_goal_service import utc_time

logger = logging.getLogger("jobflow.company_discovery")


class StaleDiscovery(RuntimeError):
    pass


def discovery_queries(goal):
    from src.services.search_intent import parse_conditions

    conditions = parse_conditions(goal.query)
    roles = list(dict.fromkeys([*conditions.roles, *conditions.preferred_roles]))[:3] or ["招聘"]
    cities = " ".join(conditions.locations[:2])
    # Graduation year belongs to job eligibility, not company discovery.
    return [{"query": f'{cities} {role} 公司 校园招聘 官网'.strip(),
             "fallback": f'"{role}" 招聘 公司官网', "stage": "search", "attempts": 0}
            for role in roles]


def enqueue_company_discovery(session, goal, *, run_id="manual", retry=False):
    now = datetime.now(UTC)
    pending = [row.id for row in list_discovered_companies(session, goal.user_id) if row.status == "pending"]
    values = {"goal_id": goal.id, "user_id": goal.user_id, "goal_version": goal.version, "run_id": run_id,
              "status": "queued", "stage": "search", "state": {"queries": discovery_queries(goal), "verify_ids": pending,
                  "verification_attempts": {}, "events": [], "cycle": 0},
              "lease_token": None, "lease_until": None, "next_run_at": now, "error": None, "updated_at": now}
    existing = session.get(CompanyDiscoveryTask, goal.id)
    if existing and existing.goal_version == goal.version:
        if existing.status in {"queued", "running"}:
            return existing
        # Ordinary searches do not repeatedly discover the same companies.
        if (existing.status in {"blocked", "completed"} and not retry
                and now - utc_time(existing.updated_at) < timedelta(hours=24)):
            return existing
        state = deepcopy(existing.state)
        if retry and existing.status == "blocked":
            for query in state["queries"]:
                if query["stage"] == "failed":
                    query["stage"] = "extract" if query.get("results") else "search"
                    query["attempts"] = 0
            state["verification_attempts"] = {}
            values["state"] = state
        else:
            cycle = state.get("cycle", 0) + 1
            values["state"]["cycle"] = cycle
            from src.services.company_registry import enabled_company_sources
            sources = enabled_company_sources(session=session, user_id=goal.user_id)
            exclusions = " ".join('-' + s.company.split('/')[0].strip() for s in sources[cycle % max(1, len(sources)):][:4])
            for query in values["state"]["queries"]:
                query["query"] += " " + exclusions
    session.execute(insert(CompanyDiscoveryTask).values(**values).on_conflict_do_update(
        index_elements=["goal_id"], set_={k: v for k, v in values.items() if k != "goal_id"},
        where=(CompanyDiscoveryTask.goal_version != goal.version) | CompanyDiscoveryTask.status.not_in(["queued", "running"])))
    session.commit()
    session.expire_all()
    return session.get(CompanyDiscoveryTask, goal.id)


def discovery_queue_summary(session, goal):
    task = session.get(CompanyDiscoveryTask, goal.id)
    current = task and task.goal_version == goal.version
    state = task.state if current else {}
    queries = state.get("queries", [])
    ids = state.get("verify_ids", [])
    rows = list(session.scalars(select(DiscoveredCompany).where(
        DiscoveredCompany.id.in_(ids), DiscoveredCompany.user_id == goal.user_id))) if ids else []
    settings = get_settings()
    return {"status": task.status if current else "idle", "stage": task.stage if current else "search",
            "enabled": settings.company_discovery_enabled and settings.structured_model_provider != "fake",
            "queries_completed": sum(q["stage"] == "done" for q in queries), "queries_total": len(queries),
            "links_saved": sum(len(q.get("results", [])) for q in queries),
            "companies_pending": sum(row.status == "pending" for row in rows),
            "companies_verified": sum(row.status in {"verified", "manually_confirmed"} for row in rows),
            "error": task.error if current else None,
            "next_run_at": utc_time(task.next_run_at) if current and task.next_run_at else None}


def _runtime(session, goal, task, *, settings, on_event, checkpoint):
    from src.infrastructure.llm_client import create_structured_model_client
    from src.services.browser_job_reader import PlaywrightBrowserJobReader
    from src.services.company_registry import enabled_company_source_hosts
    from src.services.url_reader import SafeHTTPReader
    from src.services.web_search_service import create_web_search_provider

    reader = SafeHTTPReader(timeout_seconds=8, max_retries=0, proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts=enabled_company_source_hosts(session=session, user_id=goal.user_id),
        proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts)
    return CompanyDiscoveryAgent(session, user_id=goal.user_id, run_id=task.run_id, query=goal.query,
        reader=reader, provider_factory=create_web_search_provider,
        client_factory=lambda: create_structured_model_client(settings.model_copy(update={
            "llm_max_retries": 0, "llm_timeout_seconds": 30})),
        on_event=on_event, checkpoint=checkpoint, browser=PlaywrightBrowserJobReader(timeout_seconds=10),
        request_timeout=settings.company_discovery_request_timeout_seconds,
        model_timeout=30, max_candidates=settings.company_discovery_max_candidates)


async def run_company_discovery_step(session_factory=SessionLocal, *, settings=None, agent_factory=None, now=None):
    settings = settings or get_settings()
    if not settings.company_discovery_enabled or (settings.structured_model_provider == "fake" and agent_factory is None):
        return False
    now = now or datetime.now(UTC)
    token = uuid4().hex
    with session_factory() as session:
        due = or_(CompanyDiscoveryTask.next_run_at.is_(None), CompanyDiscoveryTask.next_run_at <= now)
        available = or_(CompanyDiscoveryTask.status == "queued", (CompanyDiscoveryTask.status == "running") &
                        (CompanyDiscoveryTask.lease_until <= now))
        task = session.scalar(select(CompanyDiscoveryTask).where(due, available).order_by(CompanyDiscoveryTask.updated_at).limit(1))
        if task is None:
            return False
        goal_id, version, user_id = task.goal_id, task.goal_version, task.user_id
        claimed = session.execute(update(CompanyDiscoveryTask).where(CompanyDiscoveryTask.goal_id == goal_id,
            CompanyDiscoveryTask.goal_version == version, due, available).values(status="running", lease_token=token,
                lease_until=now + timedelta(minutes=3), updated_at=now),
            execution_options={"synchronize_session": False}).rowcount
        session.commit()
        if not claimed:
            return False
        session.refresh(task)
        state = deepcopy(task.state)

        def persist(**values):
            valid_goal = select(SearchGoal.id).where(SearchGoal.id == goal_id, SearchGoal.version == version,
                                                     SearchGoal.user_id == user_id).exists()
            changed = session.execute(update(CompanyDiscoveryTask).where(
                CompanyDiscoveryTask.goal_id == goal_id, CompanyDiscoveryTask.goal_version == version,
                CompanyDiscoveryTask.lease_token == token, valid_goal,
            ).values(state=deepcopy(state), updated_at=datetime.now(UTC), **values),
                execution_options={"synchronize_session": False}).rowcount
            if not changed:
                session.rollback()
                raise StaleDiscovery()
            session.commit()

        def event(kind, data):
            state["events"] = [*state.get("events", []), {"kind": kind, "at": datetime.now(UTC).isoformat(), **data}][-40:]

        current = next((q for q in state["queries"] if q["stage"] not in {"done", "failed"}), None)

        def checkpoint(evidence):
            if current is not None and task.stage == "extract":
                current["evidence"] = evidence
            persist()

        agent = None
        try:
            persist()
            goal = session.get(SearchGoal, goal_id)
            agent = (agent_factory or _runtime)(session, goal, task, settings=settings, on_event=event, checkpoint=checkpoint)
            pending = [row for row in list_discovered_companies(session, user_id)
                       if row.id in state.get("verify_ids", []) and row.status == "pending"
                       and state.get("verification_attempts", {}).get(row.id, 0) < 3]
            ready = next((row for row in reversed(pending) if agent.due(row)), None)
            if ready is not None:
                persist(stage="verify")
                await agent.verify(ready)
                state.setdefault("verification_attempts", {})[ready.id] = state.get("verification_attempts", {}).get(ready.id, 0) + 1
            elif current is not None:
                stage = current["stage"]
                persist(stage=stage)
                try:
                    if stage == "search":
                        query = current["query"] if not current["attempts"] else current["fallback"]
                        results = await agent.search(query)
                        current["results"] = [{"source_url": r.source_url, "title_hint": r.title_hint,
                            "search_snippet": (r.search_snippet or "")[:1600]} for r in results]
                        current.update(stage="extract" if results else "done", attempts=0)
                        persist()  # save raw search results BEFORE extraction
                    else:
                        from src.domain.discovery import LeadProvider
                        from src.services.lead_providers import LeadCandidate
                        agent.evidence_reader.restore(current.get("evidence", {}))
                        results = [LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT, discovered_at=now, **row)
                                   for row in current["results"]]
                        candidates = await agent.extract(results)
                        state["verify_ids"] = list(dict.fromkeys([*state.get("verify_ids", []), *(r.id for r in candidates)]))
                        current.update(stage="done", attempts=0)
                        persist()  # candidates are durable; verification is another step
                except StaleDiscovery:
                    raise
                except Exception as error:  # noqa: BLE001 - checkpoint and bound each stage's retries
                    session.rollback()
                    current["attempts"] += 1
                    current["last_error"] = "timeout" if isinstance(error, TimeoutError) else type(error).__name__
                    if current["attempts"] >= (2 if stage == "search" else 3):
                        current["stage"] = "failed"
                    event("stage_deferred", {"stage": stage, "error_code": current["last_error"],
                                             "query": current["query"], "attempts": current["attempts"]})
            session.expire_all()
            unfinished = any(q["stage"] not in {"done", "failed"} for q in state["queries"])
            pending = [row for row in list_discovered_companies(session, user_id)
                       if row.id in state.get("verify_ids", []) and row.status == "pending"]
            retryable = [row for row in pending if state.get("verification_attempts", {}).get(row.id, 0) < 3]
            next_at = datetime.now(UTC) + timedelta(seconds=3)
            if not unfinished and retryable:
                next_at = min(utc_time(row.last_checked_at) + timedelta(hours=min(24, max(1, row.attempts)*2))
                              if row.last_checked_at else now for row in retryable)
            active = unfinished or bool(retryable)
            blocked = bool(pending) or any(q["stage"] == "failed" for q in state["queries"])
            persist(status="queued" if active else "blocked" if blocked else "completed",
                    stage=next((q["stage"] for q in state["queries"] if q["stage"] not in {"done", "failed"}), "verify" if pending else "done"),
                    next_run_at=next_at if active else None, lease_token=None, lease_until=None,
                    error="部分来源暂未核验完成，已保存线索与进度。" if blocked else None)
        except StaleDiscovery:
            session.execute(update(CompanyDiscoveryTask).where(CompanyDiscoveryTask.goal_id == goal_id,
                CompanyDiscoveryTask.lease_token == token).values(status="superseded", lease_token=None, lease_until=None))
            session.commit()
        except asyncio.CancelledError:
            # Persisted stages and expiring leases survive process shutdown.
            raise
        except Exception:
            session.rollback()
            logger.exception("company_discovery_step_failed")
            try:
                persist(status="blocked", error="公司发现暂停，已保存进度，可重试。", lease_token=None, lease_until=None)
            except StaleDiscovery:
                pass
        finally:
            if agent is not None:
                await agent.aclose()
        return True


async def company_discovery_loop():
    while True:
        try:
            worked = await run_company_discovery_step()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - migrations may not have run yet
            logger.warning("company_discovery_queue_unavailable")
            worked = False
        await asyncio.sleep(1 if worked else 5)

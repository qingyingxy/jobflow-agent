"""Leased announcement checks, resumed after restart and scheduled per followed company."""
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from src.config import get_settings
from src.domain.campaign import CampaignWatch
from src.infrastructure.database import SessionLocal
from src.services.campaign_reader import create_campaign_reader
from src.services.campaign_service import save_campaign
from src.services.company_registry import enabled_company_sources

logger = logging.getLogger("jobflow.campaigns")


async def run_campaign_check(session_factory=SessionLocal, *, settings=None, reader_factory=None, now=None):
    now = now or datetime.now(UTC)
    settings = settings or get_settings()
    token = uuid4().hex
    available = or_(CampaignWatch.status == "queued",
        and_(CampaignWatch.status == "running", CampaignWatch.lease_until <= now),
        and_(CampaignWatch.followed.is_(True), CampaignWatch.next_check_at <= now,
             CampaignWatch.status != "running"))
    with session_factory() as session:
        watch = session.scalar(select(CampaignWatch).where(available).order_by(
            CampaignWatch.next_check_at, CampaignWatch.id).limit(1))
        if watch is None:
            return False
        watch_id, user_id, year, company_id = watch.id, watch.user_id, watch.year, watch.company_id
        changed = session.execute(update(CampaignWatch).where(CampaignWatch.id == watch_id, available).values(
            status="running", lease_token=token, lease_until=now + timedelta(minutes=3), error=None),
            execution_options={"synchronize_session": False}).rowcount
        session.commit()
        if not changed:
            return False
        session.refresh(watch)
        cache = watch.cache
    result, error, cancelled = None, None, False
    try:
        with session_factory() as session:
            sources = enabled_company_sources([company_id], session=session, user_id=user_id)
        source = sources[0]
        reader = (reader_factory or create_campaign_reader)(settings, sources)
        def checkpoint(facts, url):
            with session_factory() as session:
                owned = session.scalar(select(CampaignWatch.id).where(CampaignWatch.id == watch_id,
                    CampaignWatch.user_id == user_id, CampaignWatch.lease_token == token))
                if owned:
                    save_campaign(session, user_id, source, facts, url, datetime.now(UTC))
                    session.commit()
        reader.on_observation = checkpoint
        result = await asyncio.wait_for(reader.check(source, year, cache),
                                        timeout=min(getattr(reader, "time_budget", 90) + 10, 165))
    except asyncio.CancelledError:
        cancelled = True
    except TimeoutError:
        error = "本次检查超时，已保留历史公告，可重新检查。"
    except ValueError:
        error = "公司来源或模型配置暂不可用，请检查配置后重试。"
    except Exception:  # noqa: BLE001 - persist failed checks without exposing provider errors
        error = "本次官网检查未完成，请稍后重试。"
        logger.warning("campaign_check_failed")
    with session_factory() as session:
        # A deleted account or expired/replaced lease may not recreate data.
        watch = session.scalar(select(CampaignWatch).where(CampaignWatch.id == watch_id,
            CampaignWatch.user_id == user_id, CampaignWatch.lease_token == token))
        if watch is not None:
            finished = datetime.now(UTC)
            if cancelled:
                watch.status = "queued"
            else:
                watch.checked_at = finished
                watch.error = error or (result and result["error"])
                watch.status = "failed" if error or not result or not result["readable"] else "partial" if watch.error else "ready"
                if result:
                    watch.cache = result["cache"]
                    for facts, url in result["found"]:
                        save_campaign(session, user_id, source, facts, url, finished)
                    if result["readable"]:
                        watch.succeeded_at = finished
                watch.next_check_at = finished + timedelta(hours=1) if watch.followed else None
            watch.lease_token = watch.lease_until = None
            session.commit()
    if cancelled:
        raise asyncio.CancelledError
    return True


async def campaign_loop():
    async def worker():
        while True:
            try:
                await run_campaign_check()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep polling after transient database failures
                logger.warning("campaign_scheduler_unavailable")
            await asyncio.sleep(3)
    await asyncio.gather(worker(), worker())

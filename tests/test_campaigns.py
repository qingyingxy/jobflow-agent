import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.campaign import CampaignEvent, CampaignWatch, RecruitmentCampaign
from src.domain.search_goal import SearchGoal
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.campaign_parser import (
    Announcement,
    CampaignParser,
    explicit_campaign_title,
    validate_announcement,
)
from src.services.campaign_reader import CampaignReader, official_url
from src.services.campaign_scheduler import run_campaign_check
from src.services.campaign_service import (
    campaign_payload,
    campaign_snapshot,
    campaign_tracking,
    effective_status,
    queue_checks,
    save_campaign,
    set_followed,
)
from src.services.company_registry import CompanySource, enabled_company_sources

TEXT = """示例科技2027届秋季校园招聘启动
面向2027届毕业生
发布日期：2026年10月20日
网申时间：2026年10月20日—2026年11月30日
招聘方向：研发、产品、设计
""".strip()
FACTS = {"title": "示例科技2027届秋季校园招聘启动", "scope_quote": TEXT, "year": 2027,
    "year_quote": "面向2027届毕业生", "batch": "autumn", "batch_quote": "示例科技2027届秋季校园招聘启动",
    "status": "open", "status_quote": "示例科技2027届秋季校园招聘启动",
    "published": {"value": "2026-10-20", "quote": "发布日期：2026年10月20日"},
    "starts": {"value": "2026-10-20", "quote": "网申时间：2026年10月20日—2026年11月30日"},
    "deadline": {"value": "2026-11-30", "quote": "网申时间：2026年10月20日—2026年11月30日"},
    "directions": ["研发", "产品", "设计"]}
NOW = datetime(2026, 10, 22, tzinfo=UTC)
SOURCE = CompanySource("example", "示例科技", "A", "https://careers.example.com/", "official_campus_page")
SETTINGS = Settings(_env_file=None, app_env="testing", structured_model_provider="fake")


def test_full_announcement_has_literal_evidence():
    assert validate_announcement(Announcement(**FACTS), TEXT, 2027) == {**FACTS, "cohort_status": "confirmed"}


def test_exact_title_fallback_never_infers_dates_or_open_state():
    facts = explicit_campaign_title({"title": "官网", "text": TEXT}, SOURCE, 2027)[0]
    assert facts["year"] == 2027 and facts["status"] == "unknown"
    assert facts["published"] is None and facts["deadline"] is None
    assert explicit_campaign_title({"text": "示例科技2027校园招聘", "title": "官网"}, SOURCE, 2027) == []
    assert explicit_campaign_title({"text": "示例科技2026届秋季校园招聘正式启动", "title": "官网"}, SOURCE, 2027) == []
    assert explicit_campaign_title({"text": "示例科技2027届春季校园招聘正式启动", "title": "官网"}, SOURCE, 2027) == []


@pytest.mark.parametrize("changes", [
    {"year": 2026}, {"year_quote": "2027届博士"}, {"title": "未出现的秋招公告"},
    {"batch": "early"}, {"scope_quote": TEXT.replace("面向", "仅限")},
    {"year_quote": "发布日期：2026年10月20日"},
])
def test_rejects_ungrounded_batch_or_cohort(changes):
    assert validate_announcement(Announcement(**{**FACTS, **changes}), TEXT, 2027) is None


def test_dates_outside_announcement_and_wrong_labels_are_not_claimed():
    changed = deepcopy(FACTS)
    changed["deadline"] = {"value": "2027-12-01", "quote": "其他批次网申截止2027年12月1日"}
    changed["published"] = {"value": "2026-11-30", "quote": FACTS["deadline"]["quote"]}
    result = validate_announcement(Announcement(**changed), TEXT + "\n其他批次网申截止2027年12月1日", 2027)
    assert result["deadline"] is None and result["published"] is None


def test_cannot_reverse_window_or_infer_status_from_future_deadline():
    changed = deepcopy(FACTS)
    changed["starts"]["value"] = "2026-11-30"
    changed["deadline"]["value"] = "2026-10-20"
    result = validate_announcement(Announcement(**changed), TEXT, 2027)
    assert result["starts"] is None and result["deadline"] is None
    assert effective_status({**FACTS, "deadline": None}, NOW) == "announced"
    assert effective_status(FACTS, NOW, NOW) == "open"
    assert effective_status(FACTS, NOW + timedelta(days=50)) == "closed"
    assert effective_status(FACTS, NOW - timedelta(days=5)) == "upcoming"


def test_start_date_cannot_become_deadline():
    text = TEXT + "\n网申开始：2026年10月20日"
    item = Announcement(**{**FACTS, "scope_quote": text,
        "deadline": {"value": "2026-10-20", "quote": "网申开始：2026年10月20日"}})
    assert validate_announcement(item, text, 2027)["deadline"] is None


@pytest.mark.parametrize("status,starts,deadline,quote,age,expected", [
    ("unknown", True, True, "", 2, "unknown"),
    ("unknown", True, True, "", 0, "open"),
    ("unknown", False, True, "", 0, "unknown"),
    ("announced", False, True, "秋招正式启动", 2, "unknown"),
    ("announced", False, True, "秋招正式启动", 0, "open"),
    ("open", False, False, "秋招正式启动", 0, "announced"),
    ("open", True, False, "秋招正式启动", 0, "announced"),
    ("open", False, False, "网申进行中", 0, "open"),
    ("open", False, False, "目前接受简历投递", 0, "open"),
    ("open", False, False, "网申进行中", 2, "unknown"),
    ("open", False, False, "2026年10月1日网申开放", 0, "announced"),
    ("unknown", True, True, "网申暂停接受投递", 0, "unknown"),
    ("closed", True, True, "网申已结束", 0, "closed"),
])
def test_availability_requires_current_evidence_or_a_valid_window(status, starts, deadline, quote, age, expected):
    facts = {**FACTS, "status": status, "status_quote": quote,
             "starts": FACTS["starts"] if starts else None, "deadline": FACTS["deadline"] if deadline else None}
    assert effective_status(facts, NOW, NOW - timedelta(days=age)) == expected


def test_deadline_is_inclusive_in_china_and_future_start_is_not_open():
    facts = {**FACTS, "deadline": {"value": "2026-10-22", "quote": "网申截止2026年10月22日"}}
    assert effective_status(facts, datetime(2026, 10, 22, 15, 59, tzinfo=UTC), NOW) == "open"
    assert effective_status(facts, datetime(2026, 10, 22, 16, 0, tzinfo=UTC)) == "closed"
    assert effective_status(FACTS, NOW - timedelta(days=3)) == "upcoming"


@pytest.mark.parametrize("quote,expected", [
    ("网申尚未开放", "unknown"), ("网申暂停接受投递", "unknown"),
    ("网申已截止", "closed"), ("网申已关闭", "closed"),
])
def test_model_open_label_cannot_override_negative_source_status(quote, expected):
    text = TEXT + "\n" + quote
    item = Announcement(**{**FACTS, "scope_quote": text, "status_quote": quote})
    facts = validate_announcement(item, text, 2027)
    assert effective_status(facts, NOW, NOW) == expected


def test_application_instructions_are_not_a_recruitment_direction():
    text = TEXT + "\n官网或小米招聘公众号提交简历"
    item = Announcement(**{**FACTS, "scope_quote": text, "directions": ["研发", "官网或小米招聘公众号提交简历"]})
    assert validate_announcement(item, text, 2027)["directions"] == ["研发"]


@pytest.mark.parametrize("quote", ["招聘状态：招聘中", "网申受理中", "网申状态：开放", "正在接受简历投递"])
def test_live_status_without_dates_survives_parser_and_has_a_freshness_limit(quote):
    text = TEXT + "\n" + quote
    item = Announcement(**{**FACTS, "scope_quote": text, "starts": None, "deadline": None, "status_quote": quote})
    facts = validate_announcement(item, text, 2027)
    assert effective_status(facts, NOW, NOW) == "open"
    assert effective_status(facts, NOW + timedelta(hours=25), NOW) == "unknown"


def test_snapshot_orders_open_batches_by_opening_date_not_discovery_or_update(db_session, monkeypatch):
    from src.services import campaign_service
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(campaign_service, "datetime", Clock)
    source = enabled_company_sources(["baidu"])[0]
    def store(title, changes, seen=NOW):
        return save_campaign(db_session, "owner", source, {**FACTS, "title": title, **changes}, source.career_url, seen)
    store("未知状态今天发现", {"status": "unknown", "starts": None, "deadline": None, "published": None})
    old = store("旧批次今天发现", {"starts": {"value": "2026-09-01", "quote": "网申开始2026年9月1日"}})
    store("最近开放", {}, NOW - timedelta(days=1))
    store("无日期仍可投", {"starts": None, "deadline": None, "published": None,
        "status_quote": "网申进行中"})
    store("无开放日期有公告", {"starts": None, "deadline": None, "status_quote": "网申进行中"})
    store("已经截止", {"status": "closed"})
    store("即将开放", {"starts": {"value": "2026-10-25", "quote": "网申开始2026年10月25日"}})
    db_session.commit()
    snapshot = campaign_snapshot(db_session, "owner", 2027)
    assert [c["title"] for c in snapshot["campaigns"]] == [
        "最近开放", "旧批次今天发现", "无开放日期有公告", "无日期仍可投", "即将开放", "未知状态今天发现", "已经截止"]
    old.changed_at = NOW + timedelta(days=1)
    db_session.commit()
    assert [c["id"] for c in snapshot["campaigns"]] == [c["id"] for c in campaign_snapshot(db_session, "owner", 2027)["campaigns"]]
    assert snapshot["campaigns"][0]["latest_event"]["kind"] == "first_seen"


def test_failed_parse_does_not_renew_current_open_evidence(db_session):
    facts = {**FACTS, "starts": None, "deadline": None, "status_quote": "网申进行中"}
    row = save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, NOW)
    db_session.commit()
    assert campaign_payload(row, NOW)["status"] == "open"
    save_campaign(db_session, "owner", SOURCE, {**facts, "status": "unknown", "partial": True},
                  SOURCE.career_url, NOW + timedelta(days=2))
    db_session.commit()
    assert campaign_payload(row, NOW + timedelta(days=2))["status"] == "unknown"
    assert row.last_seen_at.replace(tzinfo=UTC) == NOW


def test_startup_without_current_evidence_is_never_a_new_opening_event(db_session):
    upcoming = {**FACTS, "status": "upcoming", "starts": None, "deadline": None}
    save_campaign(db_session, "owner", SOURCE, upcoming, SOURCE.career_url, NOW)
    save_campaign(db_session, "owner", SOURCE, {**upcoming, "status": "open"}, SOURCE.career_url, NOW)
    db_session.commit()
    assert [e.kind for e in db_session.scalars(select(CampaignEvent))] == ["first_seen", "updated"]


@pytest.mark.asyncio
async def test_parser_schema_checks_real_model_output():
    client = FakeModelClient(output={"announcements": [FACTS]})
    parser = CampaignParser(client, SETTINGS)
    result = await parser.parse({"title": FACTS["title"], "text": TEXT, "url": SOURCE.career_url}, 2027)
    assert result == [{**FACTS, "cohort_status": "confirmed"}]
    assert client.last_request.schema_name == "recruitment_campaigns"


@pytest.mark.parametrize("url,expected", [
    ("https://careers.example.com/campus/notice", True),
    ("https://careers.example.com.evil.org/notice", False),
    ("https://evil.org/careers.example.com", False),
    ("javascript:alert(1)", False), ("https://u:p@careers.example.com/", False),
])
def test_only_company_scoped_public_urls(url, expected):
    assert official_url(url, SOURCE) is expected


def test_shared_platform_must_keep_tenant_boundary():
    source = CompanySource("tenant", "企业", "A", "https://app.mokahr.com/campus-recruitment/acme/", "official")
    assert official_url("https://app.mokahr.com/campus-recruitment/acme/notice", source)
    assert not official_url("https://app.mokahr.com/campus-recruitment/other/notice", source)
    source = CompanySource("tenant", "企业", "A", "https://campus.51job.com/acme/", "official")
    assert not official_url("https://campus.51job.com/other/", source)


def test_first_seen_is_not_newly_published_and_identical_refresh_has_no_event(db_session):
    one = save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url, NOW)
    db_session.commit()
    again = save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url, NOW + timedelta(hours=1))
    db_session.commit()
    assert one.id == again.id
    assert [e.kind for e in db_session.scalars(select(CampaignEvent))] == ["first_seen"]
    assert again.last_seen_at.replace(tzinfo=UTC) == NOW + timedelta(hours=1)
    new_url = save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url + "notice", NOW)
    assert new_url.id == one.id


def test_scope_noise_does_not_emit_event_but_changed_deadline_does(db_session):
    row = save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url, NOW)
    db_session.commit()
    noise = {**FACTS, "scope_quote": TEXT + "\n新增导航"}
    save_campaign(db_session, "owner", SOURCE, noise, SOURCE.career_url, NOW)
    later = {**FACTS, "deadline": {"value": "2026-12-01", "quote": "网申截止：2026年12月1日"}}
    save_campaign(db_session, "owner", SOURCE, later, SOURCE.career_url, NOW + timedelta(days=1))
    db_session.commit()
    assert [e.kind for e in db_session.scalars(select(CampaignEvent))] == ["first_seen", "deadline_changed"]
    assert db_session.get(RecruitmentCampaign, row.id).facts["deadline"]["value"] == "2026-12-01"


@pytest.mark.parametrize("transition", ["opened", "closed"])
def test_unchanged_announcements_record_calendar_transitions_once(db_session, transition):
    before = datetime(2026, 10, 22, 15, 59, tzinfo=UTC)
    after = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)
    field = "starts" if transition == "opened" else "deadline"
    value = "2026-10-23" if transition == "opened" else "2026-10-22"
    facts = {**FACTS, "status": "announced", field: {"value": value, "quote": "官网网申时间"}}
    row = save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, before)
    db_session.commit()
    assert row.facts["observed_status"] == ("upcoming" if transition == "opened" else "open")
    save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, after)
    db_session.commit()
    save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, after + timedelta(hours=1))
    db_session.commit()
    events = list(db_session.scalars(select(CampaignEvent).order_by(CampaignEvent.observed_at)))
    assert [e.kind for e in events] == ["first_seen", transition]
    assert events[-1].evidence["before"]["status"] == "announced"
    assert events[-1].evidence["after"]["status"] == "announced"
    assert row.changed_at.replace(tzinfo=UTC) == after


def test_legacy_campaign_uses_previous_observation_time_for_opening_event(db_session):
    facts = {**FACTS, "status": "announced", "starts": {"value": "2026-10-23", "quote": "网申开始2026年10月23日"}}
    row = save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, NOW)
    row.facts = {k: v for k, v in row.facts.items() if k not in {"observed_status", "date_checked_at"}}
    db_session.commit()
    save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, NOW + timedelta(days=1))
    db_session.commit()
    assert [e.kind for e in db_session.scalars(select(CampaignEvent))] == ["first_seen", "opened"]


def test_reconfirming_a_stale_open_campaign_is_not_a_new_opening(db_session):
    row = save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url, NOW)
    db_session.commit()
    later = NOW + timedelta(days=2)
    assert campaign_payload(row, later)["status"] == "unknown"
    save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url, later)
    db_session.commit()
    assert campaign_payload(row, later)["status"] == "open"
    assert [e.kind for e in db_session.scalars(select(CampaignEvent))] == ["first_seen"]


def test_stale_evidence_does_not_masquerade_as_an_announcement_update(db_session):
    facts = {**FACTS, "status": "announced"}
    row = save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, NOW)
    db_session.commit()
    later = NOW + timedelta(days=2)
    save_campaign(db_session, "owner", SOURCE, {**facts, "starts": None, "deadline": None}, SOURCE.career_url, later)
    db_session.commit()
    assert campaign_payload(row, later)["status"] == "unknown"
    assert [e.kind for e in db_session.scalars(select(CampaignEvent))] == ["first_seen"]


def test_different_programs_on_same_page_and_users_remain_separate(db_session):
    one = save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url, NOW)
    two = save_campaign(db_session, "owner", SOURCE, {**FACTS, "title": "另一个专项2027届秋招启动"}, SOURCE.career_url, NOW)
    other = save_campaign(db_session, "other", SOURCE, FACTS, SOURCE.career_url, NOW)
    db_session.commit()
    assert len({one.id, two.id, other.id}) == 3


def test_partial_fallback_does_not_overwrite_prior_verified_facts(db_session):
    row = save_campaign(db_session, "owner", SOURCE, FACTS, SOURCE.career_url, NOW)
    db_session.commit()
    save_campaign(db_session, "owner", SOURCE, {**FACTS, "title": FACTS["title"].removesuffix("启动"),
        "status": "unknown", "partial": True}, SOURCE.career_url, NOW)
    db_session.commit()
    assert row.facts["status"] == "open"
    assert len(list(db_session.scalars(select(CampaignEvent)))) == 1
    assert len(list(db_session.scalars(select(RecruitmentCampaign)))) == 1


def test_read_does_not_queue_and_default_cohort_comes_from_saved_goal(db_session):
    now = datetime.now(UTC)
    assert campaign_snapshot(db_session, "owner")["year"] in {now.year, now.year + 1}
    db_session.add(SearchGoal(user_id="owner", name="目标", input_text="2027届校招", query="2027届校招",
        conditions={"graduation_years": [2027]}, condition_sources={}))
    db_session.commit()
    assert campaign_snapshot(db_session, "owner")["year"] == 2027
    assert list(db_session.scalars(select(CampaignWatch))) == []


def test_queue_covers_all_sources_without_restarting_active_checks(db_session):
    from src.services.company_registry import enabled_company_sources

    queue_checks(db_session, "owner", 2027)
    first = list(db_session.scalars(select(CampaignWatch)))
    assert {w.company_id for w in first} == {s.id for s in enabled_company_sources()}
    before = {w.company_id: w.next_check_at for w in first}
    first[0].status, first[0].lease_token = "running", "worker-owns-check"
    db_session.commit()
    queue_checks(db_session, "owner", 2027)
    assert {w.company_id: w.next_check_at for w in db_session.scalars(select(CampaignWatch))} == before
    assert first[0].status == "running" and first[0].lease_token == "worker-owns-check"
    assert not list(db_session.scalars(select(CampaignWatch).where(CampaignWatch.user_id == "other")))
    assert campaign_tracking(db_session, "owner") == []
    set_followed(db_session, "owner", 2027, "baidu", True)
    assert len(campaign_tracking(db_session, "owner")) == 1
    assert campaign_tracking(db_session, "other") == []
    set_followed(db_session, "owner", 2027, "baidu", False)
    assert campaign_tracking(db_session, "owner") == []


class ReaderFixture:
    async def check(self, source, year, cache):
        return {"found": [(FACTS, source.career_url)], "cache": {}, "readable": True, "error": None}


async def check(session, reader=None, now=None):
    return await run_campaign_check(sessionmaker(bind=session.bind), settings=SETTINGS,
        reader_factory=lambda *_: reader or ReaderFixture(), now=now or NOW)


@pytest.mark.asyncio
async def test_worker_persists_and_does_not_repeat_manual_checks(db_session):
    queue_checks(db_session, "owner", 2027, ["baidu"])
    assert await check(db_session)
    db_session.expire_all()
    watch = db_session.scalar(select(CampaignWatch))
    assert watch.status == "ready" and watch.next_check_at is None
    assert not await check(db_session)
    assert len(campaign_snapshot(db_session, "owner", 2027)["campaigns"]) == 1
    assert campaign_snapshot(db_session, "other", 2027)["campaigns"] == []


@pytest.mark.asyncio
async def test_followed_source_updates_hourly_and_recovers_expired_lease(db_session):
    queue_checks(db_session, "owner", 2027, ["baidu"])
    set_followed(db_session, "owner", 2027, "baidu", True)
    watch = db_session.scalar(select(CampaignWatch))
    watch.status, watch.lease_token = "running", "crashed"
    watch.lease_until = NOW - timedelta(minutes=1)
    db_session.commit()
    assert await check(db_session)
    db_session.refresh(watch)
    assert watch.next_check_at > watch.checked_at
    assert not await check(db_session, now=watch.checked_at.replace(tzinfo=UTC) + timedelta(minutes=59))
    assert await check(db_session, now=watch.checked_at.replace(tzinfo=UTC) + timedelta(minutes=61))


@pytest.mark.asyncio
async def test_cancellation_requeues_and_failure_does_not_close_existing_campaign(db_session):
    queue_checks(db_session, "owner", 2027, ["baidu"])
    await check(db_session)
    class Cancel:
        async def check(self, *_):
            raise asyncio.CancelledError
    queue_checks(db_session, "owner", 2027, ["baidu"])
    with pytest.raises(asyncio.CancelledError):
        await check(db_session, Cancel())
    db_session.expire_all()
    assert db_session.scalar(select(CampaignWatch)).status == "queued"
    class Fail:
        async def check(self, *_):
            raise RuntimeError("provider secret must not be shown")
    await check(db_session, Fail())
    db_session.expire_all()
    assert db_session.scalar(select(CampaignWatch)).status == "failed"
    assert "secret" not in db_session.scalar(select(CampaignWatch)).error
    assert db_session.scalar(select(RecruitmentCampaign)).facts["status"] == "open"


@pytest.mark.asyncio
async def test_account_deleted_during_check_cannot_be_recreated(db_session):
    queue_checks(db_session, "owner", 2027, ["baidu"])
    class Deleted(ReaderFixture):
        async def check(self, *args):
            db_session.execute(delete(CampaignWatch))
            db_session.commit()
            return await super().check(*args)
    await check(db_session, Deleted())
    assert list(db_session.scalars(select(RecruitmentCampaign))) == []


@pytest.mark.asyncio
async def test_first_observation_survives_later_reader_failure(db_session):
    queue_checks(db_session, "owner", 2027, ["baidu"])
    class Partial:
        async def check(self, source, *_):
            self.on_observation(FACTS, source.career_url)
            raise TimeoutError()
    await check(db_session, Partial())
    db_session.expire_all()
    assert db_session.scalar(select(CampaignWatch)).status == "failed"
    assert db_session.scalar(select(RecruitmentCampaign)).title == FACTS["title"]


@pytest.mark.asyncio
async def test_two_workers_cannot_check_the_same_company(db_session):
    queue_checks(db_session, "owner", 2027, ["baidu"])
    started, release = asyncio.Event(), asyncio.Event()
    class Slow(ReaderFixture):
        async def check(self, *args):
            started.set()
            await release.wait()
            return await super().check(*args)
    task = asyncio.create_task(check(db_session, Slow()))
    await started.wait()
    try:
        assert not await check(db_session)
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_model_failure_preserves_only_explicit_source_title_and_retries_later():
    class Pages:
        async def read(self, url):
            return {"url": url, "title": FACTS["title"], "text": TEXT, "links": []}
    class Broken:
        async def parse(self, *_):
            raise TimeoutError()
    reader = CampaignReader(None, None, Broken(), None)
    reader.pages = Pages()
    result = await reader.check(SOURCE, 2027, {})
    assert len(result["found"]) == 1 and result["error"]
    fact, _ = result["found"][0]
    assert fact["status"] == "unknown" and fact["deadline"] is None
    assert not result["cache"]["pages"]


@pytest.mark.asyncio
async def test_http_api_refresh_follow_and_validation(db_session):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"X-User-ID": "owner"}) as client:
        assert (await client.get("/api/campaigns?year=2027")).json()["campaigns"] == []
        assert (await client.post("/api/campaigns/refresh", json={"year": 2027, "company_ids": ["baidu"]})).status_code == 202
        assert (await client.post("/api/campaigns/refresh", json={"year": 2027, "company_ids": ["evil"]})).status_code == 422
        assert (await client.put("/api/campaigns/companies/baidu/watch", json={"year": 2027, "followed": True})).status_code == 200
        tracking = (await client.get("/api/tracking/summary")).json()
        assert tracking["campaign_watches"][0]["company_id"] == "baidu"
        assert (await client.get("/api/campaigns?year=1700")).status_code == 422


@pytest.mark.asyncio
async def test_read_cache_saves_model_work_but_still_reads_official_page():
    class Pages:
        reads = 0
        async def read(self, url):
            self.reads += 1
            return {"url": url, "title": FACTS["title"], "text": TEXT, "links": []}
    client = FakeModelClient(output={"announcements": [FACTS]})
    reader = CampaignReader(None, None, CampaignParser(client, SETTINGS), None)
    reader.pages = Pages()
    first = await reader.check(SOURCE, 2027, {})
    second = await reader.check(SOURCE, 2027, first["cache"])
    assert first["found"] == second["found"]
    assert reader.pages.reads == 2 and len(client.requests) == 1
    assert first["stats"]["model_calls"] == 1 and second["stats"]["model_calls"] == 0
    assert second["stats"]["parse_cache_hits"] == 1


@pytest.mark.asyncio
async def test_topic_without_availability_continues_searching_for_official_application_notice():
    class Pages:
        async def read(self, url):
            return {"url": url, "title": FACTS["title"], "text": TEXT, "links": []}
    class Parser:
        async def parse(self, page, year):
            if page["url"] == SOURCE.career_url:
                return [{**FACTS, "status": "unknown", "starts": None, "deadline": None}]
            return [FACTS]
    class Provider:
        calls = 0
        async def discover(self):
            self.calls += 1
            return [SimpleNamespace(source_url=SOURCE.career_url + "notice")]
    provider = Provider()
    reader = CampaignReader(None, None, Parser(), lambda *_args, **_kwargs: provider)
    reader.pages = Pages()
    result = await reader.check(SOURCE, 2027, {})
    assert provider.calls == 3 and provider.search_purpose == "campaigns"
    assert len({d["purpose"] for d in reader.diagnostics if d.get("purpose")}) == 3
    assert len(result["found"]) == 2
    assert result["found"][1][1] == SOURCE.career_url + "notice"


@pytest.mark.asyncio
async def test_search_summary_and_redirected_third_party_never_become_announcements():
    class Pages:
        async def read(self, url):
            return {"url": "https://evil.example.org/notice", "text": TEXT, "title": FACTS["title"]}
    class Provider:
        async def discover(self):
            return [SimpleNamespace(source_url="https://evil.example.org/notice", search_snippet=TEXT)]
    reader = CampaignReader(None, None, None, lambda *_args, **_kwargs: Provider())
    reader.pages = Pages()
    result = await reader.check(SOURCE, 2027, {})
    assert result["found"] == [] and not result["readable"]


def test_existing_registry_is_used_without_whole_platform_trust():
    source = enabled_company_sources(["baidu"])[0]
    assert official_url(source.career_url, source)

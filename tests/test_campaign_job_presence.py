from datetime import UTC, datetime, timedelta

import pytest

from src.domain.campaign import CampaignWatch
from src.infrastructure.llm_client import FakeModelClient
from src.services.campaign_entry import CampaignEntryParser, entry_campaign
from src.services.campaign_job_presence import check_result
from src.services.campaign_reader import CampaignReader
from src.services.campaign_service import campaign_snapshot, save_campaign
from src.services.company_registry import enabled_company_sources
from tests.test_campaign_entries import SETTINGS, SOURCE, NoticeParser, Pages, page

TEXT = "2027届校园招聘\n算法工程师 上海\n产品经理 深圳"
LIST = {"kind": "listing", "title": "2027届校园招聘", "scope_quote": TEXT,
        "campus_quote": "校园招聘", "year_quote": "2027届", "status": "unknown",
        "status_quote": "", "job_titles": ["算法工程师", "产品经理"], "apply_label": ""}


async def read_list(output=LIST, text=TEXT):
    document = {"url": SOURCE.career_url, "text": text, "application_actions": []}
    parsed = await CampaignEntryParser(FakeModelClient(output=output), SETTINGS).parse(document, 2027)
    return entry_campaign(parsed, document, SOURCE, 2027)


@pytest.mark.asyncio
async def test_visible_campus_jobs_are_enough_without_jd_buttons_dates_or_open_words(db_session):
    facts = await read_list()
    assert facts["entry"]["status"] == "unknown"
    assert facts["entry"]["job_presence"] == "found"
    source = enabled_company_sources()[0]
    save_campaign(db_session, "owner", source, facts, source.career_url, datetime.now(UTC))
    db_session.flush()
    snapshot = campaign_snapshot(db_session, "owner", 2027)
    card = next(c for c in snapshot["company_cards"] if c["company_id"] == source.id)
    assert card["recruitment_status"] == "open"
    assert card["job_titles"] == ["算法工程师", "产品经理"]
    assert snapshot["campaigns"][0]["application_url"] is None


@pytest.mark.asyncio
async def test_listing_cannot_borrow_jobs_from_social_or_intern_sections():
    scope = "2027届校园招聘 暂无职位"
    facts = await read_list({**LIST, "scope_quote": scope}, scope + "\n社会招聘 算法工程师\n实习 产品经理")
    assert facts["entry"]["job_titles"] == []
    assert facts["entry"]["job_presence"] == "empty"


@pytest.mark.asyncio
@pytest.mark.parametrize("quote", ["已截止", "职位已下线", "暂停招聘", "即将开放"])
async def test_unavailable_jobs_are_not_company_presence(quote):
    text = TEXT + "\n" + quote
    facts = await read_list({**LIST, "scope_quote": text, "status_quote": quote}, text)
    assert facts["entry"]["job_presence"] == "unknown"


@pytest.mark.asyncio
async def test_wrong_cohort_is_rejected_and_unspecified_cohort_is_kept():
    assert await read_list({**LIST, "title": "2026届校园招聘", "scope_quote": TEXT.replace("2027", "2026"),
                            "year_quote": "2026届"}, TEXT.replace("2027", "2026")) is None
    text = TEXT.replace("2027届", "")
    facts = await read_list({**LIST, "title": "校园招聘", "scope_quote": text, "year_quote": ""}, text)
    assert facts["entry"]["job_presence"] == "found" and facts["cohort_status"] == "unspecified"


@pytest.mark.asyncio
async def test_populated_list_stops_before_details_and_announcements_even_on_repeated_checks():
    notice, detail = SOURCE.career_url + "/announcements", SOURCE.career_url + "/job/123"
    parser = CampaignEntryParser(FakeModelClient(output=LIST), SETTINGS)
    reader = CampaignReader(None, None, NoticeParser(), None, entry_parser=parser)
    document = {**page(SOURCE.career_url, TEXT, links=[(detail, "算法工程师"), (notice, "校招公告")]),
                "listing_state": "populated", "hiring_links": [detail]}
    cache = {}
    for _ in range(3):
        reader.pages = Pages({SOURCE.career_url: document})
        result = await reader.check(SOURCE, 2027, cache)
        assert reader.pages.visited == [SOURCE.career_url]
        assert result["stats"]["stop_reason"] == "campus_jobs_found"
        assert result["cache"]["pending_checks"] == []
        assert result["cache"]["job_check"]["status"] == "found"
        cache = result["cache"]
    assert len(parser.client.requests) == 1


@pytest.mark.asyncio
async def test_explicit_empty_is_different_from_unloaded():
    text = "2027届校园招聘 暂无职位"
    parser = CampaignEntryParser(FakeModelClient(output={**LIST, "scope_quote": text, "job_titles": []}), SETTINGS)
    reader = CampaignReader(None, None, NoticeParser(), None, entry_parser=parser)
    reader.pages = Pages({SOURCE.career_url: {**page(SOURCE.career_url, text), "listing_state": "empty"}})
    result = await reader.check(SOURCE, 2027, {})
    assert result["cache"]["job_check"]["status"] == "empty"
    reader.pages = Pages({SOURCE.career_url: {**page(SOURCE.career_url, "校园招聘 加载中"), "listing_state": "unloaded"}})
    result = await reader.check(SOURCE, 2027, {})
    assert result["cache"]["job_check"]["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", ["empty", "unknown"])
async def test_latest_company_check_supersedes_older_positive_evidence(db_session, latest):
    source = enabled_company_sources()[0]
    facts = await read_list()
    now = datetime.now(UTC)
    facts["entry"]["checked_at"] = (now - timedelta(hours=1)).isoformat()
    save_campaign(db_session, "owner", source, facts, source.career_url, now)
    db_session.add(CampaignWatch(user_id="owner", company_id=source.id, year=2027, status="ready",
        cache={"job_check": {"status": latest, "checked_at": now.isoformat(), "job_titles": []}}))
    db_session.flush()
    card = next(c for c in campaign_snapshot(db_session, "owner", 2027)["company_cards"] if c["company_id"] == source.id)
    assert card["recruitment_status"] == latest and card["job_titles"] == []


@pytest.mark.asyncio
async def test_keyword_filtered_empty_list_does_not_prove_company_has_no_jobs():
    text = "2027届校园招聘 暂无职位"
    facts = await read_list({**LIST, "scope_quote": text, "job_titles": []}, text)
    facts["entry"]["url"] += "?keyword=算法"
    assert check_result([(facts, SOURCE.career_url)], complete=True)["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("row", ["算法工程师 已下线", "已截止 算法工程师"])
async def test_closed_rows_are_excluded_even_if_model_omits_the_state(row):
    text = "2027届校园招聘\n" + row + "\n产品经理 深圳"
    facts = await read_list({**LIST, "scope_quote": text}, text)
    assert facts["entry"]["job_titles"] == ["产品经理"]


def test_campus_navigation_does_not_promote_an_explicit_social_list():
    text = "职位列表 社会招聘 算法工程师"
    observation = {**LIST, "title": "职位列表", "scope_quote": text, "campus_quote": "", "year_quote": ""}
    assert entry_campaign(observation, {"url": SOURCE.career_url, "text": text}, SOURCE, 2027,
                          {"link_text": "校园招聘"}) is None


def test_open_announcement_without_jobs_is_only_supplementary(db_session):
    from tests.test_campaign_entries import FACT
    source = enabled_company_sources()[0]
    save_campaign(db_session, "owner", source, FACT, source.career_url, datetime.now(UTC))
    db_session.flush()
    card = next(c for c in campaign_snapshot(db_session, "owner", 2027)["company_cards"] if c["company_id"] == source.id)
    assert card["recruitment_status"] == "unknown" and card["job_titles"] == []


@pytest.mark.asyncio
async def test_rendered_trainee_rows_without_recognized_cards_are_still_parsed_and_cached():
    text = "2027届校园招聘 筛选 职位类别 集团管培生 管培生类 应届生 工作城市：深圳市 FMP管培生 管培生类 应届生 工作城市：深圳市 共 2 条"
    output = {**LIST, "scope_quote": text, "job_titles": ["集团管培生", "FMP管培生"]}
    parser = CampaignEntryParser(FakeModelClient(output=output), SETTINGS)
    reader = CampaignReader(None, None, NoticeParser(), None, entry_parser=parser)
    cache = {}
    for _ in range(2):
        reader.pages = Pages({SOURCE.career_url: {**page(SOURCE.career_url, text),
                             "method": "browser", "listing_state": "unloaded"}})
        result = await reader.check(SOURCE, 2027, cache)
        assert result["cache"]["job_check"]["job_titles"] == ["集团管培生", "FMP管培生"]
        assert result["cache"]["pending_checks"] == [] and result["error"] is None
        cache = result["cache"]
    assert len(parser.client.requests) == 1


@pytest.mark.asyncio
async def test_rendered_filter_shell_does_not_become_job_presence():
    text = "2027届校园招聘 筛选 职位类别 加载中"
    parser = CampaignEntryParser(FakeModelClient(output={**LIST, "scope_quote": text, "job_titles": []}), SETTINGS)
    reader = CampaignReader(None, None, NoticeParser(), None, entry_parser=parser)
    reader.pages = Pages({SOURCE.career_url: {**page(SOURCE.career_url, text), "method": "browser", "listing_state": "unloaded"}})
    result = await reader.check(SOURCE, 2027, {})
    assert result["cache"]["job_check"]["status"] == "unknown"

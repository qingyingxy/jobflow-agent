import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import (
    classify_discovery_job,
    search_filter_conditions,
)
from src.services.discovery_sources import JobStub
from src.services.source_understanding import (
    SourceUnderstanding,
    checked_decisions,
    paragraphs,
)

DATA = json.loads((Path(__file__).resolve().parents[1] / "datasets/real_pending_jobs_20261018.json").read_text(encoding="utf-8"))
QUERY = DATA["query"]


def job(index):
    row = DATA["samples"][index]
    return JobStub(**{k: row[k] for k in ("source_id", "source_job_id", "company", "title",
        "locations", "job_type", "raw_content")}, detail_url=row["source_url"], published_at=None)


def decision(field, status, ids, *, diagnosis="supported"):
    return {"field": field, "status": status, "diagnosis": diagnosis,
            "reason": "根据完整原文核对", "evidence_ids": ids}


def engine(decisions, **options):
    return SourceUnderstanding(Settings(_env_file=None, web_search_understanding_mode="hybrid", **options),
                               client=FakeModelClient(output={"decisions": decisions}))


@pytest.mark.asyncio
@pytest.mark.parametrize("qualifications", [True, False])
async def test_two_cohorts_are_recovered_without_erasing_degree_clause_and_cached(qualifications):
    original = job(1)
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "2026/2027" in p)
    runtime = engine([decision("graduation_year", "matched", [index])])
    runtime.include_qualifications = qualifications
    updated = await runtime.review(original, query=QUERY)
    check = next(c for c in classify_discovery_job(updated, query=QUERY).checks if c["field"] == "graduation_year")
    assert check["status"] == "matched"
    assert "本科及以上学历" in check["evidence"][0]
    assert await runtime.review(updated, query=QUERY) is updated
    assert runtime.calls == 1
    mixed_case = search_filter_conditions(QUERY)
    mixed_case["roles"] = [r.upper() for r in mixed_case["roles"]]
    assert checked_decisions(updated, mixed_case)["graduation_year"]["status"] == "matched"
    assert not checked_decisions(replace(updated, raw_content=updated.raw_content + "\n仅限2026届"), search_filter_conditions(QUERY))
    assert not checked_decisions(updated, search_filter_conditions(QUERY.replace("2027", "2028")))
    # JSON-object providers do not transmit json_schema: the prompt must carry it.
    assert '"evidence_ids"' in runtime.client.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_location_loss_is_correctly_excluded_and_novel_duties_are_understood():
    original = job(3)
    parts = paragraphs(original.raw_content)
    loc = next(i for i, p in enumerate(parts) if "安徽省·合肥市,四川省·成都市" == p)
    duty = next(i for i, p in enumerate(parts) if "基于 LLM" in p)
    runtime = engine([decision("location", "excluded", [loc]), decision("role", "matched", [duty])])
    updated = await runtime.review(original, query=QUERY)
    match = classify_discovery_job(updated, query=QUERY)
    assert match.filter_status == "excluded"
    assert {c["field"]: c["status"] for c in match.checks} == DATA["samples"][3]["expected"]


@pytest.mark.asyncio
async def test_missing_cohort_never_acquires_a_year_from_season_or_model():
    original = job(2)
    runtime = engine([decision("graduation_year", "matched", [0])])
    assert await runtime.review(original, query=QUERY) is original
    assert not runtime.client.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    decision("graduation_year", "matched", []),
    decision("graduation_year", "matched", [999]),
    decision("graduation_year", "matched", [0], diagnosis="source_missing"),
])
async def test_unsupported_confirmations_are_discarded(bad):
    original = job(1)
    updated = await engine([bad]).review(original, query=QUERY)
    assert updated.raw_content == original.raw_content
    assert not checked_decisions(updated, search_filter_conditions(QUERY))
    assert classify_discovery_job(updated, query=QUERY) == classify_discovery_job(original, query=QUERY)
    assert updated.recruitment_context["source_review_attempt"]["error_code"] == "semantic_invalid"


@pytest.mark.asyncio
async def test_qualified_cohort_remains_pending_and_literal_conditions_survive():
    original = replace(job(1), raw_content=job(1).raw_content.replace("2026/2027届", "境内2026届，境外2027届"))
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "境外2027" in p)
    updated = await engine([decision("graduation_year", "pending", [index], diagnosis="ambiguous")]).review(original, query=QUERY)
    check = next(c for c in classify_discovery_job(updated, query=QUERY).checks if c["field"] == "graduation_year")
    assert check["status"] == "pending"
    assert "境内2026届，境外2027届" in check["evidence"][0]


@pytest.mark.asyncio
async def test_user_product_scope_is_distinct_from_engineering_scope():
    original = job(6)
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "端到端负责" in p)
    updated = await engine([decision("role", "matched", [index])]).review(original, query=QUERY)
    assert checked_decisions(updated, search_filter_conditions(QUERY))["role"]["status"] == "matched"
    narrower = QUERY.replace("、AI产品", "")
    assert not checked_decisions(updated, search_filter_conditions(narrower))


@pytest.mark.asyncio
async def test_budget_and_timeout_are_bounded_under_concurrency():
    class Slow:
        async def generate(self, request):
            await asyncio.Event().wait()

    runtime = SourceUnderstanding(Settings(_env_file=None, web_search_understanding_mode="hybrid", web_search_semantic_max_calls=1,
        web_search_semantic_timeout_seconds=0.05), client=Slow())
    originals = [job(1), job(3)]
    results = await asyncio.gather(*(runtime.review(j, query=QUERY) for j in originals))
    assert [r.raw_content for r in results] == [j.raw_content for j in originals]
    assert all(not checked_decisions(r, search_filter_conditions(QUERY)) for r in results)
    assert results[0].recruitment_context["source_review_attempt"]["error_code"] == "semantic_timeout"
    assert runtime.calls == 1


@pytest.mark.asyncio
async def test_non_duty_quote_cannot_confirm_role():
    original = job(6)
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "搭过 Agent" in p)
    updated = await engine([decision("role", "matched", [index])]).review(original, query=QUERY)
    assert not checked_decisions(updated, search_filter_conditions(QUERY))
    assert classify_discovery_job(updated, query=QUERY) == classify_discovery_job(original, query=QUERY)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["http", "browser"])
async def test_real_verification_path_recovers_unfamiliar_readable_detail(db_session, mode):
    from src.domain.discovery import LeadProvider
    from src.services.browser_job_reader import BrowserPageSnapshot
    from src.services.job_detail_scope import readable_page_text
    from src.services.job_lead_service import JobLeadService
    from src.services.url_reader import FetchedResponse, parse_html_document

    raw = '<html><title>Careers</title><body><div>Agent技术伙伴</div><div>你的一天</div><div>把检索库接入智能助手，编写工具调用与多轮任务执行模块，测试后交付线上服务。</div><div>你需要带来</div><div>2026/2027届本科毕业生，能够熟练编写Python代码，愿意参与产品工程实践。</div></body></html>'
    document = parse_html_document(raw)
    parts = paragraphs(readable_page_text(raw))
    title_id = parts.index("Agent技术伙伴")
    duty_id = next(i for i, p in enumerate(parts) if "把检索库" in p)
    req_id = next(i for i, p in enumerate(parts) if "2026/2027" in p)
    runtime = SourceUnderstanding(Settings(_env_file=None, web_search_understanding_mode="hybrid"), client=FakeModelClient(output={
        "page_type": "single_job", "title": "Agent技术伙伴", "first_paragraph": title_id,
        "last_paragraph": req_id, "duty_ids": [duty_id], "requirement_ids": [req_id]}))
    service = JobLeadService(db_session, understanding=runtime)
    url = "https://example.com/careers/123"
    lead = service.create_lead(user_id="u", provider=LeadProvider.EXTERNAL_AGENT,
                               source_url=url, title_hint="Agent技术伙伴")

    class Reader:
        async def fetch(self, target):
            return FetchedResponse(requested_url=url, final_url=url, status_code=200,
                                  content_type="text/html", body=raw.encode())

        async def read(self, target):
            return BrowserPageSnapshot(requested_url=url, final_url=url, title="Careers",
                                       raw_html=raw, visible_text=document.text)

    result = await getattr(service, "verify_url" if mode == "http" else "verify_browser")(
        user_id="u", lead_id=lead.id, reader=Reader(), official_hosts={"example.com"}, official_only=True)
    assert result.posting.title == "Agent技术伙伴"
    assert "2026/2027届" in result.posting.raw_content
    assert result.posting.verification_status == "VERIFIED_OFFICIAL"


@pytest.mark.asyncio
async def test_semantic_scope_does_not_turn_job_list_into_a_detail():
    from src.services.url_reader import parse_html_document

    document = parse_html_document('<div>' + ('岗位列表：Agent工程师，产品经理，数据科学家。' * 10) + '</div>')
    runtime = SourceUnderstanding(Settings(_env_file=None, web_search_understanding_mode="hybrid"), client=FakeModelClient(output={
        "page_type": "listing", "title": None, "first_paragraph": None,
        "last_paragraph": None, "duty_ids": [], "requirement_ids": []}))
    assert await runtime.recover_detail(document, url="https://example.com/list") is None


@pytest.mark.asyncio
async def test_page_recovery_cannot_consume_the_field_review_budget():
    from src.services.source_understanding import DetailOutput

    original = job(1)
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "2026/2027" in p)
    client = FakeModelClient(outputs=[{"page_type": "other", "title": None,
        "first_paragraph": None, "last_paragraph": None, "duty_ids": [], "requirement_ids": []},
        {"decisions": [decision("graduation_year", "matched", [index])]}])
    runtime = SourceUnderstanding(Settings(_env_file=None, web_search_understanding_mode="hybrid", web_search_semantic_max_calls=1,
        web_search_semantic_recovery_max_calls=1), client=client)
    assert await runtime.generate(DetailOutput, {}, "读取页面", kind="job_detail_text_scope")
    updated = await runtime.review(original, query=QUERY)
    assert checked_decisions(updated, search_filter_conditions(QUERY))["graduation_year"]["status"] == "matched"
    assert runtime.calls == 2


@pytest.mark.asyncio
async def test_search_persists_semantics_and_refresh_keeps_availability_unknown(db_session, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy.orm import sessionmaker

    from src.domain.discovery import DiscoveryRun
    from src.domain.job import JobAvailabilityStatus
    from src.services import multiround_search, source_understanding, web_search_service
    from src.services.discovery_results import current_run_matches
    from src.services.job_lead_service import JobLeadService
    from tests.test_search_execution import candidate

    original = replace(job(1), detail_url=candidate(1).source_url)
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "2026/2027" in p)
    client = FakeModelClient(output={"decisions": [decision("graduation_year", "matched", [index])]})

    class Provider:
        source_id = "test"

        async def discover(self):
            return [candidate(1)]

    async def verify(service, *, user_id, lead_id, **kwargs):
        return service.verify_stub(user_id=user_id, lead_id=lead_id, stub=original,
                                   availability_status=JobAvailabilityStatus.UNKNOWN)

    settings = Settings(_env_file=None, web_search_understanding_mode="hybrid", structured_model_provider="openai",
        web_search_direct_sources_enabled=False, company_discovery_enabled=False,
        web_search_max_rounds=1, web_search_budget_seconds=5, web_search_verification_budget_seconds=5)
    monkeypatch.setattr(multiround_search, "get_settings", lambda: settings)
    monkeypatch.setattr(multiround_search, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(multiround_search, "enabled_company_source_hosts", lambda **_: {"example.com"})
    monkeypatch.setattr(multiround_search, "enabled_company_sources", lambda *_, **__: [])
    monkeypatch.setattr(web_search_service, "create_web_search_provider", lambda *_, **__: Provider())
    monkeypatch.setattr(source_understanding, "create_structured_model_client", lambda _: client)
    monkeypatch.setattr(JobLeadService, "verify_url", verify)
    run = DiscoveryRun(id="semantic-fields", user_id="u", source="test", source_url="https://example.com", search_query=QUERY,
                       started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    await multiround_search.execute_multiround_search(run_id=run.id, user_id="u", query=QUERY,
                                                     company_ids=[], analysis_limit=0)
    db_session.refresh(run)
    assert len(client.requests) == 1
    for result in [run.result_matches[0], current_run_matches(db_session, [run])[run.id][0]]:
        assert result["filter_status"] == "pending"
        checks = {c["field"]: c for c in result["checks"]}
        assert checks["graduation_year"]["status"] == "matched"
        assert checks["graduation_year"]["method"] == "source_semantics"
        assert checks["availability"]["status"] == "pending"

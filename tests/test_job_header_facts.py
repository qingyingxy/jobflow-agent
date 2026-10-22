from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.domain.discovery import DiscoveryRun, LeadProvider
from src.main import app
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_detail_scope import scope_job_document
from src.services.job_fact_verifier import verify_page_facts
from src.services.job_header_facts import (
    effective_job_locations,
    header_location_evidence,
)
from src.services.job_lead_service import JobLeadService
from src.services.url_reader import parse_html_document

TITLE = "Agent研发工程师"
QUERY = "2027届上海Agent校招，不考虑北京"
BODY = "职位描述\n负责Agent任务规划、工具调用和RAG系统的研发。\n职位要求\n熟悉Python。"
RAW = f"{TITLE}\n上海\n校招\n正式\n2027届校园招聘计划\n{BODY}"
STUB = JobStub(
    source_id="fixture",
    source_job_id="header",
    title=TITLE,
    company="测试公司",
    locations=[],
    job_type="campus",
    published_at=None,
    raw_content=RAW,
    detail_url="https://example.com/jobs/header",
)


@pytest.mark.parametrize(
    "locations", ["上海", "上海市", "北京、上海、合肥", "深圳 / 杭州"]
)
def test_header_locations_persist_with_exact_source_offsets(locations):
    html = f"<nav>北京</nav><main><h1>{TITLE}</h1><div>{locations}</div><div>校招</div><h2>职位描述</h2><p>负责Agent开发。</p><h2>职位要求</h2><p>熟悉Python。</p><aside>推荐岗位：天津</aside></main>"
    doc, _ = scope_job_document(html, parse_html_document(html), url=STUB.detail_url)
    facts = verify_page_facts(doc)
    expected = locations.replace(" / ", "、").split("、")
    assert doc.locations == facts.locations == expected
    for item in facts.evidence["locations"]:
        assert doc.text[item["start_char"] : item["end_char"]] == item["value"]
        assert item["start_char"] > doc.text.index(TITLE)


@pytest.mark.parametrize(
    "raw",
    [
        f"上海\n{TITLE}\n{BODY}",
        f"{TITLE}\n我们在上海拥有研发团队\n{BODY}",
        f"{TITLE}\n岗位职责\n上海\n任职要求\n熟悉Python。",
        f"{TITLE}\n北京、未知区域\n{BODY}",
        f"{TITLE}\n上海\n校招",  # Missing JD boundary: incomplete page.
        f"其他工程师\n上海\n{BODY}",
    ],
)
def test_bare_city_in_navigation_prose_or_incomplete_header_is_not_a_location(raw):
    assert header_location_evidence(raw, TITLE) == []
    assert (
        effective_job_locations(
            SimpleNamespace(raw_content=raw, title=TITLE, locations=[])
        )
        == []
    )


def test_existing_explicit_metadata_is_not_overwritten():
    assert effective_job_locations(replace(STUB, locations=["北京"])) == ["北京"]
    assert (
        classify_discovery_job(
            replace(STUB, locations=["北京"]), query=QUERY
        ).filter_status
        == "excluded"
    )


@pytest.mark.parametrize(
    "inline,expected",
    [
        ("上海", ["上海"]),
        ("北京、深圳", ["北京", "深圳"]),
        ("我们在上海设有办公室", []),
        ("北京、未知区域", []),
    ],
)
def test_inline_title_cities_are_literal_fields_with_exact_offsets(inline, expected):
    raw = f"{TITLE}  {inline}\n正式\n{BODY}"
    evidence = header_location_evidence(raw, TITLE)
    assert [e["value"] for e in evidence] == expected
    assert all(raw[e["start_char"] : e["end_char"]] == e["value"] for e in evidence)


@pytest.mark.parametrize(
    "header,expected",
    [
        ("上海市 校招 技术 5人 2026-07-21", ["上海市"]),
        ("北京市,上海市 新星项目 技术 若干 2026-09-24", ["北京市", "上海市"]),
        ("中国香港", ["中国香港"]),
        ("北京、未知区域 校招 技术 5人", []),
        ("北京 公司计划在上海扩展研发团队", []),
        ("上海 技术 北京项目", ["上海"]),
    ],
)
def test_compact_header_fields_preserve_exact_city_spans(header, expected):
    raw = f"{TITLE}\n  {header}\n{BODY}"
    evidence = header_location_evidence(raw, TITLE)
    assert [e["value"] for e in evidence] == expected
    assert all(raw[e["start_char"] : e["end_char"]] == e["value"] for e in evidence)


@pytest.mark.parametrize("stored", [["查看工作岗位"], ["View all jobs"]])
def test_navigation_location_is_repaired_from_header_without_mutation(stored):
    stub = replace(STUB, locations=stored, raw_content=f"{TITLE} 上海\n{BODY}")
    assert effective_job_locations(stub) == ["上海"]
    assert stub.locations == stored
    check = next(
        c
        for c in classify_discovery_job(stub, query=QUERY).checks
        if c["field"] == "location"
    )
    assert check["status"] == "matched" and check["evidence"] == ["上海"]


def test_unrecognized_location_is_not_silently_discarded():
    stub = replace(STUB, locations=["北京", "未知区域"])
    assert effective_job_locations(stub) == ["北京", "未知区域"]
    assert (
        next(
            c
            for c in classify_discovery_job(stub, query=QUERY).checks
            if c["field"] == "location"
        )["status"]
        == "pending"
    )


def test_new_page_facts_drop_navigation_labels_and_keep_inline_city():
    document = parse_html_document(f"<h1>{TITLE}</h1>")
    raw = f"工作地点：查看工作岗位\n{TITLE} 中国香港\n{BODY}"
    document = replace(document, text=raw, title=TITLE, locations=["查看工作岗位"])
    facts = verify_page_facts(document)
    assert facts.locations == ["中国香港"]
    evidence = facts.evidence["locations"][0]
    assert raw[evidence["start_char"] : evidence["end_char"]] == "中国香港"


@pytest.mark.parametrize("value", ["北京、未知区域", "北京市 / 未知区域"])
def test_partial_header_location_list_does_not_become_a_false_exclusion(value):
    html = f"<main><h1>{TITLE}</h1><div>{value}</div><h2>职位描述</h2><p>负责Agent开发。</p><h2>职位要求</h2><p>熟悉Python。</p></main>"
    doc, _ = scope_job_document(html, parse_html_document(html), url=STUB.detail_url)
    assert verify_page_facts(doc).locations == []


@pytest.mark.parametrize(
    "cohort,requirement,expected",
    [
        ("2027届校园招聘计划", "熟悉Python。", "matched"),
        ("2028届校园招聘项目", "熟悉Python。", "excluded"),
        ("2027校园招聘计划", "熟悉Python。", "pending"),
        ("应届生 (2027届应届生校园招聘)", "熟悉Python。", "matched"),
        ("应届生（2028届应届生校园招聘）", "熟悉Python。", "excluded"),
        ("应届生 (2027届海外应届生校园招聘)", "熟悉Python。", "pending"),
        ("应届生 (2027届应届生校园招聘)，仅限海外毕业生", "熟悉Python。", "pending"),
        ("应届生 (2027届应届生校园招聘)", "2026届应届生。", "pending"),
        (
            "2027届校园招聘-正式批",
            "教育背景 硕士及以上学历，2027届应届生，计算机相关专业 必备能力 熟悉Python。",
            "matched",
        ),
        (
            "2027届校园招聘-正式批",
            "教育背景 硕士及以上学历，2026届应届生，计算机相关专业。",
            "pending",
        ),
        (
            "2027届校园招聘-正式批",
            "教育背景 硕士及以上学历，2027届海外应届生。",
            "pending",
        ),
        (
            "2027届校园招聘-正式批",
            "2027届应届生，毕业时间2026年9月至2027年8月。",
            "pending",
        ),
        ("2027届校园招聘-正式批", "2027届应届生，不接受尚未毕业者。", "pending"),
        ("2027届校园招聘计划（仅限海外毕业生）", "熟悉Python。", "pending"),
    ],
)
def test_cohort_decorations_and_repeated_education_statements(
    cohort, requirement, expected
):
    raw = f"{TITLE}\n上海\n校招\n{cohort}\n职位描述\n负责Agent系统开发。\n职位要求\n{requirement}"
    match = classify_discovery_job(replace(STUB, raw_content=raw), query=QUERY)
    assert match.filter_status == expected
    cohort_check = next(c for c in match.checks if c["field"] == "graduation_year")
    assert all(quote in raw for quote in cohort_check["evidence"])


@pytest.mark.parametrize("stored", [[], ["查看工作岗位"]])
def test_existing_saved_results_agree_with_list_and_detail_without_mutation(
    db_session, stored
):
    run = DiscoveryRun(
        id="header-run",
        user_id="header-user",
        source="fixture",
        source_url="https://example.com",
        search_query=QUERY,
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="header-user",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url=STUB.detail_url,
        discovery_run_id=run.id,
    )
    verified = service.verify_stub(
        user_id="header-user", lead_id=lead.id, stub=replace(STUB, locations=stored)
    )
    job = verified.posting
    assert job.locations == stored
    client = TestClient(app, headers={"X-User-ID": "header-user"})
    for _ in range(2):
        listing = client.get("/api/candidates").json()
        detail = client.get(f"/api/jobs/{job.id}").json()
        result = client.get(f"/api/discovery/runs/{run.id}").json()
        assert listing[0]["job"]["locations"] == detail["locations"] == ["上海"]
        assert result["result_matches"][0]["filter_status"] == "matched"
    db_session.refresh(job)
    assert job.locations == stored
    assert job.raw_content == RAW

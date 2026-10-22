import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.domain.discovery import LeadProvider, LeadVerification
from src.services.browser_job_reader import (
    BrowserPageSnapshot,
    BrowserReadError,
    declared_static_resource_host,
    static_resource_declarations,
)
from src.services.discovery_sources import JobStub
from src.services.job_lead_service import JobLeadService
from src.services.job_role_review import fingerprint, load_role_review
from src.services.lead_presentation import lead_discovery_kind
from src.services.lead_providers import LeadCandidate
from src.services.url_reader import HTMLLink
from tests.test_recruitment_capabilities import SOURCE, Browser, Reader, run_direct


@pytest.mark.parametrize("url,kind,declared,allowed", [
    ("https://assets.cdn.bcebos.com/app.js", "script", True, True),
    ("https://g.alicdn.com/app.css", "stylesheet", True, True),
    ("https://lf-package-cn.feishucdn.com/app.js", "script", True, True),
    ("https://g.alicdn.com/app.js", "script", False, False),
    ("https://g.alicdn.com/api", "xhr", True, False),
    ("https://g.alicdn.com/app.js", "document", True, False),
    ("http://g.alicdn.com/app.js", "script", True, False),
    ("https://g.alicdn.com:444/app.js", "script", True, False),
    ("https://g.alicdn.com:bad/app.js", "script", True, False),
    ("https://[bad/app.js", "script", True, False),
    ("https://user@g.alicdn.com/app.js", "script", True, False),
    ("https://127.0.0.1/app.js", "script", True, False),
    ("https://alicdn.com.evil.example/app.js", "script", True, False),
    ("https://notalicdn.com/app.js", "script", True, False),
])
def test_static_dependency_permission_is_narrow(url, kind, declared, allowed):
    result = declared_static_resource_host(url, resource_type=kind, declared_urls=[url] if declared else [])
    assert bool(result) == allowed


def test_resources_must_be_declared_as_assets_not_arbitrary_links():
    html = '<script src="//g.alicdn.com/app.js"></script><link rel="stylesheet" href="/site.css">' \
           '<a href="https://g.alicdn.com/other.js">link</a><img src="/image.png">'
    assert static_resource_declarations(html, "https://careers.example/") == [
        "https://g.alicdn.com/app.js", "https://careers.example/site.css",
    ]


def test_observed_title_survives_persistence_without_verifying_a_job(db_session):
    candidate = LeadCandidate(LeadProvider.EXTERNAL_AGENT, "https://careers.example/opening-abc",
                              datetime.now(UTC), title_hint="Agent工程师")
    service = JobLeadService(db_session)
    generated = service.capture_candidate(user_id="u", candidate=candidate)
    assert lead_discovery_kind(generated) == "entry"
    observed = service.capture_candidate(user_id="u", candidate=replace(candidate, observed_title=True))
    db_session.expire_all()
    observed = service.get_lead(user_id="u", lead_id=observed.id)
    assert lead_discovery_kind(observed) == "job"
    assert observed.job_posting_id is None
    assert observed.extracted_fields["verified"] is False
    # Recapturing a search hint must not discard an earlier observed card.
    assert lead_discovery_kind(service.capture_candidate(user_id="u", candidate=candidate)) == "job"


@pytest.mark.parametrize("duty,expected", [
    ("负责设计并实现Agent编排方案，开发可复用的Agent工具与协作组件。", "matched"),
    ("负责Agent训练数据生产和数据标注运营，提供训练数据集与评测集。", "pending"),
])
@pytest.mark.parametrize('old_version', ['job-role-review-v20-duty-before-qualification', 'job-role-review-v21-implementation-objects'])
def test_previous_cache_rechecks_original_proposal_without_rewriting_evidence(db_session, duty, expected, old_version):
    query = "上海 ai agent / rag 校招"
    job = JobStub("fixture", "one", "未知公司", "Agent设计交付", ["上海"], "campus", None,
                  "https://unknown.example/opening-one", "官网职能分类：运营\n岗位职责\n" + duty + "\n任职要求\n计算机专业")
    key = fingerprint(job, query, version=old_version)
    evidence = {"fingerprint": key, "version": old_version,
                "proposed_output": {"status": "matched", "reason": "职责相关", "evidence_ids": [0]},
                "decision": {"status": "pending", "reason": "旧规则", "evidence": [duty]},
                "match_guard": "target_duty_evidence_missing"}
    record = LeadVerification(id="check", lead_id="lead", user_id="u", result="ROLE_REVIEW",
                              source_url=job.detail_url, content_hash=key, field_evidence=deepcopy(evidence),
                              checked_at=datetime.now(UTC))
    db_session.add(record)
    db_session.commit()
    review = load_role_review(db_session, user_id="u", job=job, query=query)
    assert review["decision"]["status"] == expected
    assert review["revalidated_from_version"] == old_version
    for user, changed, search in [("other", job, query), ("u", replace(job, raw_content=job.raw_content + "新职责"), query),
                                  ("u", replace(job, detail_url=job.detail_url + "2"), query), ("u", job, "后端")]:
        assert load_role_review(db_session, user_id=user, job=changed, query=search) is None
    db_session.expire_all()
    assert record.field_evidence == evidence
    assert record.content_hash == key


class DynamicBrowser(Browser):
    def __init__(self, *, changed=False, fail_once=False):
        super().__init__({SOURCE.career_url: "<main>校园招聘</main>"})
        self.dynamic_calls = []
        self.changed = changed
        self.fail_once = fail_once

    async def read_dynamic_listing(self, url, *, cursor=None, keywords=(), max_links=8):
        self.dynamic_calls.append(deepcopy(cursor))
        if cursor and self.fail_once:
            self.fail_once = False
            raise BrowserReadError("临时网络错误", code="browser_timeout")
        if cursor and self.changed:
            self.changed = False
            raise BrowserReadError("列表变化", code="pagination_changed")
        start = (cursor or {}).get("offset", 0)
        end = min(7, start + max_links)
        # Both a next link and a UI cursor are observed: only one should be queued.
        html = '<a rel="next" href="?page=2">下一页</a>' if end < 7 else "<main>校园招聘</main>"
        links = tuple(HTMLLink(f"https://careers.example/opening-{i}", f"Agent工程师 {i}") for i in range(start, end))
        return BrowserPageSnapshot(url, url, "", html, "", discovered_links=links,
                                   dynamic_listing={"next_cursor": {"history": [], "fingerprint": "same", "offset": end} if end < 7 else None,
                                                    "reason": None if end < 7 else "listing_boundary"})


@pytest.mark.asyncio
async def test_dynamic_cursor_survives_three_job_quota_and_serialized_resume():
    browser = DynamicBrowser()
    reader = Reader({SOURCE.career_url: "<main>校园招聘</main>"})
    first, a, _ = await run_direct(reader, browser=browser)
    queue = first.states[SOURCE.id]["html_queue"]
    assert len(queue) == 1 and queue[0]["dynamic_cursor"]["offset"] == 3
    second, b, _ = await run_direct(reader, browser=browser, states=json.loads(json.dumps(first.states)))
    third, c, _ = await run_direct(reader, browser=browser, states=json.loads(json.dumps(second.states)))
    assert [j.source_url for j in [*a, *b, *c]] == [f"https://careers.example/opening-{i}" for i in range(7)]
    assert all(lead_discovery_kind(j) == "job" for j in [*a, *b, *c])
    assert third.states[SOURCE.id]["status"] == "paused"
    assert third.states[SOURCE.id]["reason"] == "listing_boundary"
    assert len(browser.dynamic_calls) == 3
    assert not any(e.full_body for e in third.evidence.values())


@pytest.mark.asyncio
async def test_failed_cursor_retries_same_offset_then_changed_page_restarts_without_duplicates():
    browser = DynamicBrowser()
    reader = Reader({SOURCE.career_url: "<main>校园招聘</main>"})
    first, a, _ = await run_direct(reader, browser=browser)
    browser.fail_once = True
    failed, empty, _ = await run_direct(reader, browser=browser, states=deepcopy(first.states))
    assert not empty and failed.states[SOURCE.id]["reason"] == "entry_retry_pending"
    entry = failed.states[SOURCE.id]["html_queue"][0]
    assert entry["last_error"] == "browser_timeout"
    assert entry["dynamic_cursor"]["offset"] == 3
    entry.pop("retry_at")  # Resume when the persisted per-entry cooldown expires.
    browser.changed = True
    resumed, b, _ = await run_direct(reader, browser=browser, states=deepcopy(failed.states))
    assert len(a) == 3 and [j.source_url for j in b] == [f"https://careers.example/opening-{i}" for i in range(3, 6)]
    assert resumed.states[SOURCE.id]["reason"] == "company_read_limit"

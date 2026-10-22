import json
from types import SimpleNamespace

import pytest

from src.services.browser_job_reader import recruitment_api_request
from src.services.recruitment_context import (
    collect_recruitment_context,
    resolve_availability,
)
from src.services.recruitment_templates import alibaba_detail_api

URL = "https://campus-talent.alibaba.com/campus/position/199907640058"
TITLE = "Agent Infra工程师"
HTML = f"<main><h1>{TITLE}</h1><h2>职位描述</h2><p>负责Agent系统与工具调用研发</p><h2>职位要求</h2><p>熟悉Python</p><h2>在招业务</h2><p>阿里云</p></main>"
ITEM = {"id": 199907640058, "name": TITLE, "status": "recruit", "circleNames": ["阿里云"],
        "batchId": 100000760001, "batchName": "阿里巴巴2027届应届生",
        "graduationTime": {"from": 1793491200000, "to": 1824940800000}}


async def context(item=None, request_id="199907640058", html=HTML, official=True):
    from src.services.job_detail_scope import scope_job_document
    from src.services.url_reader import parse_html_document

    document, _ = scope_job_document(html, parse_html_document(html), url=URL)
    return await collect_recruitment_context(raw_html=html, document=document, url=URL,
        fetcher=None, is_official=lambda _: official, save_snapshot=lambda *_: "snapshot",
        api_records=[{"url": "https://campus-talent.alibaba.com/position/detail?_csrf=ephemeral",
                      "request": {"id": request_id}, "payload": {"success": True, "content": item or ITEM}}])


@pytest.mark.asyncio
async def test_alibaba_preserves_exact_job_batch_graduation_window_and_open_evidence():
    result = await context()
    assert result["job_id"] == "199907640058"
    assert "2026年11月01日至2027年10月31日" in result["eligibility_text"]
    assert "csrf" not in str(result)
    assert result["snapshot_id"] == "snapshot"
    assert resolve_availability(HTML, url=URL, context=result)["value"] == "ACTIVE"
    from dataclasses import replace

    from src.services.discovery_matching import classify_discovery_job
    from tests.test_discovery_filtering import BASE, QUERY

    match = classify_discovery_job(replace(BASE, detail_url=URL, recruitment_context=result), query=QUERY)
    assert next(c for c in match.checks if c["field"] == "graduation_year")["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"id": 1}, {"name": "另一个岗位"}])
async def test_alibaba_rejects_other_job_payload(change):
    assert (await context({**ITEM, **change}))["status"] == "unconfirmed"


@pytest.mark.asyncio
async def test_alibaba_never_infers_open_from_unknown_status_button_or_untrusted_site():
    assert (await context({**ITEM, "status": 1}))["availability"]["value"] == "UNKNOWN"
    assert (await context(html=HTML.replace("在招业务", "业务介绍")))["availability"]["value"] == "UNKNOWN"
    assert not await context(request_id="2")
    assert not await context(official=False)
    assert not alibaba_detail_api("https://attacker.example/position/detail", URL)
    hidden = HTML.replace("<h2>在招业务</h2><p>阿里云</p>", '<aside><h2>在招业务</h2><p>阿里云</p></aside>')
    assert (await context(html=hidden))["availability"]["value"] == "UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [{"from": True, "to": 1824940800000},
                                    {"from": 1824940800000, "to": 1793491200000},
                                    {"from": 10**20, "to": 10**21}, []])
async def test_invalid_graduation_dates_do_not_break_readable_job(window):
    result = await context({**ITEM, "graduationTime": window})
    assert result["status"] == "unconfirmed"


@pytest.mark.asyncio
async def test_baidu_uses_exact_project_and_not_unrelated_list_or_internship_cohorts():
    url = "https://talent.baidu.com/jobs/detail/GRADUATE/abc-123"
    detail = {"postInfo": {"postId": "abc-123", "name": TITLE, "projectTypeCode": "1"},
              "recruitType": "GRADUATE", "projectType": "1", "isValid": True}
    data = {"detailData": detail, "listData": {"content": "2025届"}, "indexData": {"schoolProjectConfig": [{"childList": [
        {"recruitType": "GRADUATE", "title": "校园招聘", "content": "面向2026年9月至2027年8月毕业的在校生"},
        {"recruitType": "INTERN", "content": "2028届暑期实习"},
    ]}]}}
    async def collect():
        return await collect_recruitment_context(url=url, raw_html='<script>window.__INITIAL_DATA__ ='+json.dumps(data)+';</script>',
            document=SimpleNamespace(title=TITLE), fetcher=None, is_official=lambda _: True, save_snapshot=lambda *_: "proof")
    result = await collect()
    assert "2027" in result["eligibility_text"] and "2028" not in result["eligibility_text"]
    assert result["availability"]["value"] == "UNKNOWN"
    detail["postInfo"]["postId"] = "other"
    assert (await collect())["status"] == "unconfirmed"


def test_feishu_get_and_post_requests_retain_filters_without_signatures():
    expected = {"keyword": "ai agent", "offset": 10, "limit": 10,
                "location_code_list": ["bj", "sh"], "subject_id_list": []}
    assert recruitment_api_request("https://recruiting.unity.cn/api/v1/search/job/posts?keyword=ai%20agent&limit=10&offset=10&location_code_list=bj%2Csh&subject_id_list=&_signature=unused", None) == expected
    assert recruitment_api_request("https://jobs.example/api/v1/search/job/posts", json.dumps(expected)) == expected

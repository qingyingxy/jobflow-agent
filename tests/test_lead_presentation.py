import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.browser_job_reader import BrowserReadError
from src.services.lead_presentation import discovery_kind
from src.services.recruitment_entry import expand_entry
from src.services.url_reader import FetchedResponse


@pytest.mark.parametrize("url,title,kind", [
    ("https://example.com/careers", "加入我们", "entry"),
    ("https://example.com/about", "关于我们", "entry"),
    ("https://example.com/jobs/list", "工程师招聘", "entry"),
    ("https://example.com/jobs/detail/123", None, "job"),
    ("https://example.com/beisen?job_id=12", None, "job"),
    ("https://example.com/tenant/pb/posDetail.html?postId=abc&postType=campus", None, "job"),
    ("https://example.com/jobs/list?postId=abc", None, "entry"),
    ("https://example.com/campus/position/123", "AI应用工程师", "job"),
])
def test_link_kinds(url,title,kind):
    assert discovery_kind(url,title) == kind


@pytest.mark.parametrize("path", ["/top-talent/", "/graduate-program/", "/campaign-2027/"])
def test_generated_job_title_cannot_turn_campaign_into_detail(path):
    assert discovery_kind("https://unknown.example" + path, "Agent算法工程师（官方项目页）") == "entry"
    assert discovery_kind("https://unknown.example" + path, "Agent算法工程师") == "entry"


@pytest.mark.parametrize("title", ["Agent工程师", "Agent研究员", "RAG Research Scientist"])
def test_observed_card_title_preserves_irregular_detail_links(title):
    assert discovery_kind("https://unknown.example/opening-abc", title, observed_title=True) == "job"
    assert discovery_kind("https://unknown.example/campus/", "Agent工程师", observed_title=True) == "entry"
    assert discovery_kind("https://unknown.example/careers/agent-engineer", None) == "job"


@pytest.mark.asyncio
async def test_entry_follows_list_even_when_browser_fails():
    pages = {
        "https://example.com/careers": '<a href="/jobs/list">所有职位</a>',
        "https://example.com/jobs/list": '<a href="/jobs/1">AI应用工程师</a><a href="/jobs/1">AI应用工程师</a><a href="https://other.com/jobs/2">外部职位</a>',
    }
    snapshots = []
    class Reader:
        async def fetch(self,url):
            return FetchedResponse(requested_url=url, final_url=url, status_code=200, content_type="text/html", body=pages[url].encode())
    class Browser:
        async def read(self,url):
            raise BrowserReadError("暂时不可读")
    links = await expand_entry("https://example.com/careers",reader=Reader(),browser=Browser(),allowed_hosts={"example.com"},record_snapshot=lambda u,h:snapshots.append((u,h)))
    assert [(l.url,l.text) for l in links] == [("https://example.com/jobs/1", "AI应用工程师")]
    assert len(snapshots) == 2


def test_unverified_job_can_be_saved_and_is_user_scoped():
    client=TestClient(app)
    response=client.post("/api/discovery/leads",headers={"X-User-ID":"lead-owner"},json={"provider":"external_agent","source_url":"https://example.com/jobs/123","title_hint":"AI应用工程师"})
    assert response.status_code == 201
    lead=response.json()
    assert lead["discovery_kind"] == "job"
    assert lead["job_posting_id"] is None
    saved=client.patch(f"/api/discovery/leads/{lead['id']}/selection",headers={"X-User-ID":"lead-owner"},json={"status":"SAVED"})
    assert saved.status_code == 200
    assert saved.json()["selection_status"] == "SAVED"
    listed=client.get("/api/discovery/leads",headers={"X-User-ID":"lead-owner"}).json()
    assert next(l for l in listed if l["id"]==lead["id"])["selection_status"] == "SAVED"
    assert client.patch(f"/api/discovery/leads/{lead['id']}/selection",headers={"X-User-ID":"other"},json={"status":"IGNORED"}).status_code == 404

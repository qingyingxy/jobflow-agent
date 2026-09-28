from urllib.parse import parse_qs, urlsplit

import pytest

from src.services.discovery_sources import (
    GreenhouseAdapter,
    SourcePayloadError,
    TencentAdapter,
    _job_type,
)


@pytest.mark.parametrize("content,expected", [
    ("Build internal tools for international teams. Full-time role.", "full_time"),
    ("Software Engineer Internship", "internship"),
    ("Summer Intern", "internship"),
])
def test_english_job_type_requires_whole_word_intern(content, expected):
    assert _job_type(None, "Software Engineer", content) == expected


@pytest.mark.asyncio
async def test_tencent_empty_campus_category_does_not_hide_social_jobs():
    class Reader:
        async def fetch_json(self, url):
            query = parse_qs(urlsplit(url).query)
            if query.get("attrId") in [["2"], ["3"]]:
                return None, {"Code": 200, "Data": {"Count": 0, "Posts": None}}
            item = {
                "PostId": "123",
                "RecruitPostName": "Python 开发工程师",
                "Responsibility": "负责 Python 软件开发",
                "Requirement": "熟悉 Python",
                "LocationName": "北京",
            }
            data = {"Count": 1, "Posts": [item]} if "attrId" in query else item
            return None, {"Code": 200, "Data": data}

    jobs = await TencentAdapter(query="Python", reader=Reader(), max_jobs=1).list_jobs()
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "123"
    assert jobs[0].job_type == "full_time"


def test_tencent_missing_posts_with_positive_count_still_fails():
    adapter = TencentAdapter(query="Python")
    with pytest.raises(SourcePayloadError):
        adapter._payload_jobs(
            {"Code": 200, "Data": {"Count": 3, "Posts": None}}, job_type="campus"
        )


@pytest.mark.asyncio
async def test_bounded_greenhouse_reads_metadata_then_only_selected_details():
    calls = []

    class Reader:
        async def fetch_json(self, url):
            calls.append(url)
            item = {
                "id": 100,
                "title": "Python software engineer",
                "location": {"name": "London"},
                "absolute_url": "https://boards.greenhouse.io/example/jobs/100",
            }
            if url.endswith("/jobs"):
                return None, {
                    "jobs": [item, {**item, "id": 101, "title": "Marketing manager"}]
                }
            return None, {
                **item,
                "content": "<p>Develop Python software. Requirements: Python experience.</p>",
            }

    jobs = await GreenhouseAdapter.from_board_url(
        "https://boards.greenhouse.io/example",
        reader=Reader(),
        max_jobs=1,
        query="Python",
    ).list_jobs()
    assert len(jobs) == 1
    assert "Requirements: Python" in jobs[0].raw_content
    assert calls == [
        "https://boards-api.greenhouse.io/v1/boards/example/jobs",
        "https://boards-api.greenhouse.io/v1/boards/example/jobs/100?content=true",
    ]

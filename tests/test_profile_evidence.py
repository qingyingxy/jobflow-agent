import httpx
import pytest

from src.main import app


@pytest.mark.asyncio
async def test_profile_can_be_created_and_read() -> None:
    headers = {"X-User-ID": "user-a"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.put(
            "/api/profile",
            headers=headers,
            json={
                "display_name": "Qing",
                "graduation_year": 2027,
                "degree": "硕士",
                "major": "计算机科学",
                "search_preferences": {
                    "target_roles": ["AI Agent Engineer"],
                    "locations": ["上海", "杭州"],
                },
            },
        )
        read_response = await client.get("/api/profile", headers=headers)

    assert create_response.status_code == 200
    assert create_response.json()["user_id"] == "user-a"
    assert read_response.status_code == 200
    assert read_response.json()["search_preferences"]["target_roles"] == [
        "AI Agent Engineer"
    ]


@pytest.mark.asyncio
async def test_evidence_is_filtered_by_owner_and_can_be_edited() -> None:
    owner_headers = {"X-User-ID": "user-a"}
    other_headers = {"X-User-ID": "user-b"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post(
            "/api/evidence",
            headers=owner_headers,
            json={
                "type": "project",
                "title": "Memory Assistant",
                "claim": "实现 BM25 与向量检索融合，并加入 rerank。",
                "skills": ["RAG", "Python", "PostgreSQL"],
                "source": "resume_project_1",
            },
        )
        evidence_id = create_response.json()["id"]
        update_response = await client.patch(
            f"/api/evidence/{evidence_id}",
            headers=owner_headers,
            json={"claim": "实现 BM25 与向量检索融合，并加入 rerank 和评测。"},
        )
        owner_list = await client.get("/api/evidence", headers=owner_headers)
        other_list = await client.get("/api/evidence", headers=other_headers)
        other_read = await client.get(
            f"/api/evidence/{evidence_id}",
            headers=other_headers,
        )

    assert create_response.status_code == 201
    assert update_response.status_code == 200
    assert "评测" in update_response.json()["claim"]
    assert len(owner_list.json()) == 1
    assert other_list.json() == []
    assert other_read.status_code == 404

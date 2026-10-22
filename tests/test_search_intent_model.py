"""Boundary tests for model interpretation, execution and manual correction."""

import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import search_goals as goals_api
from src.config import Settings
from src.domain.models import UserProfile
from src.domain.search_goal import SearchGoalConditions
from src.infrastructure.llm_client import (
    FakeModelClient,
    ModelTimeoutError,
    OpenAICompatibleModelClient,
)
from src.main import app
from src.services import search_intent_model
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.search_intent import interpret_intent
from src.services.search_intent_model import IntentConflictError, validated_intent


def clauses(text, **values):
    return {
        "clauses": [
            {"field": field, "value": str(value), "source_text": text}
            for field, items in values.items()
            for value in items
        ]
    }


JOB = JobStub(
    source_id="fixture",
    source_job_id="job",
    company="测试公司",
    title="后端工程师",
    locations=["深圳"],
    job_type="campus",
    published_at=None,
    detail_url="https://example.com/job",
    raw_content="面向2027届毕业生。负责后端服务开发。",
)


@pytest.mark.asyncio
async def test_intent_request_satisfies_provider_json_mode_contract():
    """Exercise the real HTTP payload against the provider's JSON-mode rule."""
    text = "上海后端校招"
    sent = []

    def handle(request):
        payload = json.loads(request.content)
        sent.append(payload)
        assert payload["response_format"] == {"type": "json_object"}
        if not any(
            "json" in item["content"].casefold() for item in payload["messages"]
        ):
            return httpx.Response(
                400, json={"error": {"message": "messages must contain JSON"}}
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                clauses(
                                    text,
                                    locations=["上海"],
                                    roles=["后端"],
                                    job_types=["校招"],
                                ),
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    model = OpenAICompatibleModelClient(
        base_url="https://example.test/v1",
        api_key=None,
        model="test-model",
        response_format="json_object",
        transport=httpx.MockTransport(handle),
    )
    conditions, sources, notice = await interpret_intent(
        text,
        settings=Settings(_env_file=None),
        client=model,
    )
    assert len(sent) == 1
    assert sources["_intent_status"] == "model" and notice is None
    assert conditions.locations == ["上海"]


@pytest.mark.asyncio
async def test_whole_request_is_interpreted_once_and_preference_does_not_exclude():
    text = "27届后端校招，最好上海，其他城市也可以"
    output = clauses(
        text,
        graduation_years=[2027],
        roles=["后端"],
        job_types=["校招"],
        preferred_locations=["上海"],
    )
    output["unrestricted"] = [{"field": "locations", "source_text": "其他城市也可以"}]
    model = FakeModelClient(output=output)
    conditions, sources, notice = await interpret_intent(
        text, settings=Settings(_env_file=None), client=model
    )
    assert len(model.requests) == 1
    assert json.loads(model.last_request.messages[-1].content) == {"input": text}
    assert sources["_intent_status"] == "model" and notice is None
    assert conditions.graduation_years == [2027] and not conditions.locations
    outside = classify_discovery_job(
        JOB, query=text, conditions=conditions.model_dump()
    )
    preferred = classify_discovery_job(
        replace(JOB, locations=["上海"]), query=text, conditions=conditions.model_dump()
    )
    assert outside.filter_status == preferred.filter_status == "matched"
    assert preferred.preference_score > outside.preference_score


@pytest.mark.asyncio
async def test_model_correction_does_not_merge_superseded_rule_locations():
    text = "原来想上海，现在改成北京，后端实习"
    model = FakeModelClient(
        output=clauses(text, locations=["北京"], roles=["后端"], job_types=["实习"])
    )
    result, _, notice = await interpret_intent(
        text, settings=Settings(_env_file=None), client=model
    )
    assert result.locations == ["北京"] and notice is None


def test_alternative_cities_allow_both_but_only_prefer_shanghai():
    text = "上海优先，北京也行，后端校招"
    conditions, _, _ = validated_intent(
        text,
        clauses(
            text,
            locations=["上海", "北京"],
            preferred_locations=["上海"],
            roles=["后端"],
            job_types=["校招"],
        ),
    )
    results = {
        city: classify_discovery_job(
            replace(JOB, locations=[city]),
            query=text,
            conditions=conditions.model_dump(),
        )
        for city in ["上海", "北京", "深圳"]
    }
    assert results["上海"].filter_status == results["北京"].filter_status == "matched"
    assert results["深圳"].filter_status == "excluded"
    assert results["上海"].preference_score > results["北京"].preference_score


def test_unsupported_salary_is_visible_as_pending_and_does_not_exclude():
    text = "后端校招，工资最好20k以上"
    conditions, _, _ = validated_intent(
        text,
        clauses(
            text,
            roles=["后端"],
            job_types=["校招"],
            pending_conditions=["工资最好20k以上"],
        ),
    )
    result = classify_discovery_job(JOB, query=text, conditions=conditions.model_dump())
    assert result.filter_status == "pending"
    assert any(
        check["field"] == "additional" and "工资最好20k以上" in check["reason"]
        for check in result.checks
    )


@pytest.mark.parametrize(
    "text,output",
    [
        ("上海后端校招", clauses("上海后端校招", locations=["杭州"])),
        ("上海后端校招", clauses("模型编造的原文", locations=["上海"])),
        ("我27岁，找后端", clauses("我27岁，找后端", graduation_years=[2027])),
        ("2028届后端", clauses("2028届后端", graduation_years=[2027])),
        ("后端实习", clauses("后端实习", job_types=["校招"])),
        ("后端", {"clauses": [], "conflicts": ["并不存在的冲突"]}),
    ],
)
def test_ungrounded_values_and_false_quotes_are_rejected(text, output):
    with pytest.raises(ValueError):
        validated_intent(text, output)


@pytest.mark.parametrize(
    "output",
    [
        {"clauses": [], "conflicts": ["只考虑上海，上海不要"]},
        clauses(
            "只考虑上海，上海不要", locations=["上海"], excluded_locations=["上海"]
        ),
    ],
)
@pytest.mark.asyncio
async def test_conflict_is_not_silently_relaxed_by_fallback(output):
    with pytest.raises(IntentConflictError):
        await interpret_intent(
            "只考虑上海，上海不要",
            settings=Settings(_env_file=None),
            client=FakeModelClient(output=output),
        )


def configure_model(monkeypatch, model):
    monkeypatch.setattr(
        goals_api,
        "get_settings",
        lambda: Settings(_env_file=None, structured_model_provider="openai_compatible"),
    )
    monkeypatch.setattr(
        search_intent_model, "create_structured_model_client", lambda _: model
    )


def test_model_failure_blocks_save_but_allows_explicit_manual_conditions(monkeypatch):
    model = FakeModelClient(error=ModelTimeoutError("timeout"))
    configure_model(monkeypatch, model)
    text = "我在北京读书，想去深圳做固件实习"
    with TestClient(app) as client:
        response = client.post("/api/discovery/goals", json={"input_text": text})
        assert (
            response.status_code == 422
            and "修改条件" in response.json()["error"]["message"]
        )
        assert client.get("/api/discovery/goals").json() == []
        preview = client.post(
            "/api/discovery/goals/interpret", json={"input_text": text}
        ).json()
        assert preview["conditions"]["locations"] == []
        assert preview["conditions"]["pending_conditions"] == [text]
        assert preview["notice"]
        count = len(model.requests)
        saved = client.post(
            "/api/discovery/goals",
            json={
                "input_text": text,
                "conditions": SearchGoalConditions(
                    locations=["深圳"], roles=["固件"], job_types=["实习"]
                ).model_dump(),
            },
        )
        assert saved.status_code == 201
        assert saved.json()["input_text"] == text
        assert saved.json()["condition_sources"]["locations"] == "用户修改"
        assert len(model.requests) == count
        assert client.get("/api/discovery/goals").json()[0]["conditions"][
            "locations"
        ] == ["深圳"]
        assert len(model.requests) == count


def test_conflicting_request_is_not_saved(monkeypatch):
    text = "只考虑上海，上海不要，后端校招"
    configure_model(
        monkeypatch, FakeModelClient(output={"clauses": [], "conflicts": [text]})
    )
    with TestClient(app) as client:
        assert (
            client.post("/api/discovery/goals", json={"input_text": text}).status_code
            == 422
        )
        assert client.get("/api/discovery/goals").json() == []


def test_explicit_any_cohort_is_not_overridden_by_profile(monkeypatch, db_session):
    db_session.add(
        UserProfile(
            user_id="owner",
            educations=[
                {
                    "id": "master",
                    "level": "master",
                    "major_raw": "机械",
                    "source_text": "预计2027年硕士毕业",
                    "graduation_year": 2027,
                    "graduation_year_kind": "expected",
                    "graduation_year_confirmed": True,
                }
            ],
        )
    )
    db_session.commit()
    text = "Backend roles, any graduation year"
    output = clauses(text, roles=["Backend"])
    output["unrestricted"] = [
        {"field": "graduation_years", "source_text": "any graduation year"}
    ]
    configure_model(monkeypatch, FakeModelClient(output=output))
    with TestClient(app) as client:
        response = client.post(
            "/api/discovery/goals",
            headers={"X-User-ID": "owner"},
            json={"input_text": text},
        )
        assert response.status_code == 201, response.text
        assert response.json()["conditions"]["graduation_years"] == []
        assert (
            response.json()["condition_sources"]["graduation_years"]
            == "本次输入（明确不限）"
        )

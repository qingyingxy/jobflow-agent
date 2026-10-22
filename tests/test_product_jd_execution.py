from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.compare_product_jd_execution import assess, summary
from src.api import jobs as jobs_api
from src.config import Settings
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.graduation import classify_graduation_condition
from src.domain.job import JobPosting, RawJobDocument
from src.domain.runs import AgentRun, JobParseResult
from src.infrastructure.llm_client import (
    FakeModelClient,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    OpenAICompatibleModelClient,
)
from src.main import app
from src.services.analysis_runtime import create_product_parser
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParserError
from src.services.job_parse_service import JDParseFailure, JobParseService
from src.services.product_jd_execution import ProductJDExecutionParser

CLAUSE = "本科要求计算机相关专业，硕士不限专业"
RAW = "招聘开发工程师，任职要求：" + CLAUSE + "。欢迎投递。"
EXTRACTION = {
    "facts": {},
    "requirements": [{"source_text": CLAUSE, "level": "required"}],
    "responsibilities": [],
}
RELATIONS = {
    "decisions": [
        {
            "requirement_index": 0,
            "relation": "any_of",
            "items": CLAUSE.split("，"),
            "reason": "按申请学历任选一个分支",
            "education": {
                "relation": "any_of",
                "branches": [
                    {
                        "source_text": "本科要求计算机相关专业",
                        "degree": {
                            "operator": "eq",
                            "level": "bachelor",
                            "source_text": "本科",
                        },
                        "major": {
                            "mode": "related",
                            "values": ["计算机"],
                            "source_text": "计算机相关专业",
                        },
                        "scope": "application",
                        "scope_source_text": CLAUSE,
                    },
                    {
                        "source_text": "硕士不限专业",
                        "degree": {
                            "operator": "eq",
                            "level": "master",
                            "source_text": "硕士",
                        },
                        "major": {"mode": "any", "source_text": "不限专业"},
                        "scope": "application",
                        "scope_source_text": CLAUSE,
                    },
                ],
            },
        }
    ]
}


class ScriptedClient(FakeModelClient):
    def __init__(self, events, *, model="test-model"):
        super().__init__(model=model)
        self.events = list(events)

    async def generate(self, request):
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            self.requests.append(request)
            raise event
        self.output = event
        response = await super().generate(request)
        response.usage = {"prompt_tokens": 10, "completion_tokens": 5}
        return response


def posting(session):
    result = JobPosting(
        id="job_checkpoint",
        source_type="manual_text",
        raw_content=RAW,
        content_hash=hashlib.sha256(RAW.encode()).hexdigest(),
        retrieved_at=datetime.now(UTC),
        trace_id="trace_checkpoint",
    )
    session.add(result)
    session.commit()
    return result


def outputs(mode):
    return (
        [EXTRACTION, RELATIONS]
        if mode == "two_stage"
        else [{"extraction": EXTRACTION, "relations": RELATIONS}]
    )


def repair_payload():
    decision = deepcopy(RELATIONS["decisions"][0])
    decision.pop("requirement_index")
    return {
        "repaired_requirements": [
            {
                "requirement_index": 0,
                "requirement": {**EXTRACTION["requirements"][0], **decision},
            }
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 524])
async def test_transport_recovery_counts_real_http_calls_without_nested_retries(status):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert "transport_retries" not in payload
        if len(requests) == 1:
            return httpx.Response(status, text="temporary failure")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(outputs("single_call")[0])}}
                ],
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://model.example/v1",
        api_key="test",
        model="test",
        max_retries=3,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    parser = create_product_parser(
        client,
        Settings(
            product_parse_mode="single_call",
            product_parse_retry_backoff_seconds=0,
        ),
    )
    parsed = await parser.parse(RawJobDocument(raw_content=RAW))
    assert len(requests) == parsed.diagnostics["model_call_count"] == 2
    failed, passed = parsed.diagnostics["attempts"]
    assert failed["status_code"] == status
    assert failed["retry_scheduled"] is True
    assert passed["transport_attempt"] == 2
    assert passed["attempt"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 501, 505, None])
async def test_permanent_or_invalid_json_failure_is_not_transport_retried(status):
    error = ModelResponseError("invalid", {"status_code": status})
    client = ScriptedClient([error, outputs("single_call")[0]])
    parser = ProductJDExecutionParser(
        client,
        mode="single_call",
        transport_retries=1,
        retry_backoff_seconds=0,
    )
    with pytest.raises(JDParserError) as caught:
        await parser.parse(RawJobDocument(raw_content=RAW))
    assert len(client.requests) == caught.value.details["model_call_count"] == 1
    assert caught.value.details["recovery_skipped"] == "non_retryable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [ModelTimeoutError("timeout"), ModelUnavailableError("connect")]
)
async def test_network_recovery_does_not_consume_validation_repair(error):
    combined = outputs("single_call")[0]
    invalid = {"extraction": EXTRACTION, "relations": {"decisions": []}}
    client = ScriptedClient(
        [
            error,
            invalid,
            ModelResponseError("gateway", {"status_code": 502}),
            combined,
        ]
    )
    parsed = await ProductJDExecutionParser(
        client,
        mode="single_call",
        transport_retries=1,
        retry_backoff_seconds=0,
    ).parse(RawJobDocument(raw_content=RAW))
    assert parsed.diagnostics["model_call_count"] == 4
    attempts = parsed.diagnostics["attempts"]
    assert [a["attempt"] for a in attempts] == [1, 1, 2, 2]
    assert [a["status"] for a in attempts] == [
        "model_error",
        "validation_failed",
        "model_error",
        "passed",
    ]


@pytest.mark.asyncio
async def test_relation_retry_exhaustion_keeps_checkpoint_for_new_service(db_session):
    job = posting(db_session)
    errors = [ModelResponseError("gateway", {"status_code": 524}) for _ in range(2)]
    client = ScriptedClient([EXTRACTION, *errors])
    parser = ProductJDExecutionParser(
        client, transport_retries=1, retry_backoff_seconds=0
    )
    with pytest.raises(JDParseFailure) as caught:
        await JobParseService(db_session, parser).parse(user_id="a", job_id=job.id)
    assert caught.value.details["model_call_count"] == 3
    assert caught.value.details["status_code"] == 524
    assert db_session.scalar(select(JobParseResult)) is None
    with Session(db_session.bind) as session:
        resumed = ScriptedClient([RELATIONS])
        result = await JobParseService(
            session,
            ProductJDExecutionParser(
                resumed,
                transport_retries=1,
                retry_backoff_seconds=0,
            ),
        ).parse(user_id="a", job_id=job.id)
        assert len(resumed.requests) == 1
        assert result.agent_run.validation_result["execution"]["resumed_extraction"]


@pytest.mark.asyncio
async def test_total_parse_deadline_stops_relation_and_preserves_checkpoint(db_session):
    class SlowRelationClient(ScriptedClient):
        async def generate(self, request):
            if request.schema_name == "product_requirement_relations":
                self.requests.append(request)
                await asyncio.sleep(1)
                raise AssertionError("request must be cancelled")
            return await super().generate(request)

    job = posting(db_session)
    client = SlowRelationClient([EXTRACTION])
    with pytest.raises(JDParseFailure) as caught:
        await JobParseService(
            db_session,
            ProductJDExecutionParser(
                client,
                transport_retries=1,
                run_timeout_seconds=0.1,
            ),
        ).parse(user_id="a", job_id=job.id)
    assert caught.value.code == "model_timeout"
    assert caught.value.details["timeout_scope"] == "parse_run"
    assert caught.value.details["model_call_count"] == 2
    assert db_session.scalar(select(AgentRun)).validation_result["checkpoint"]
    assert db_session.scalar(select(JobParseResult)) is None


@pytest.mark.asyncio
async def test_call_budget_limits_retries_and_new_stages():
    client = ScriptedClient([EXTRACTION, RELATIONS])
    with pytest.raises(JDParserError) as caught:
        await ProductJDExecutionParser(client, max_model_calls=1).parse(
            RawJobDocument(raw_content=RAW)
        )
    assert caught.value.code == "model_call_budget_exhausted"
    assert len(client.requests) == caught.value.details["model_call_count"] == 1

    client = ScriptedClient([ModelTimeoutError("timeout"), outputs("single_call")[0]])
    with pytest.raises(JDParserError) as caught:
        await ProductJDExecutionParser(
            client,
            mode="single_call",
            max_model_calls=1,
            transport_retries=1,
            retry_backoff_seconds=0,
        ).parse(RawJobDocument(raw_content=RAW))
    assert caught.value.details["recovery_skipped"] == "call_budget"
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_retry_backoff_must_fit_remaining_total_time():
    client = ScriptedClient([ModelUnavailableError("connect")])
    with pytest.raises(JDParserError) as caught:
        await ProductJDExecutionParser(
            client,
            mode="single_call",
            transport_retries=1,
            retry_backoff_seconds=1,
            run_timeout_seconds=0.1,
        ).parse(RawJobDocument(raw_content=RAW))
    assert caught.value.details["recovery_skipped"] == "time_budget"
    assert len(client.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "calls"), [("two_stage", 2), ("single_call", 1)])
async def test_modes_share_grounded_predicates_and_local_qualification(mode, calls):
    client = ScriptedClient(outputs(mode))
    parsed = await ProductJDExecutionParser(client, mode=mode).parse(
        RawJobDocument(raw_content=RAW)
    )
    assert len(client.requests) == calls
    assert parsed.diagnostics["model_call_count"] == calls
    assert parsed.diagnostics["resumed_extraction"] is False
    assert (
        sum(a["usage"]["prompt_tokens"] for a in parsed.diagnostics["attempts"])
        == calls * 10
    )
    job = parsed.structured_jd.model_copy(update={"graduation_years": []})
    profile = CandidateProfileInput(
        educations=[
            {"level": "bachelor", "major_raw": "机械", "source_text": "本科机械"},
            {"level": "master", "major_raw": "金融", "source_text": "硕士金融"},
        ]
    )
    eligibility = check_eligibility(
        EligibilityInput(profile=profile, job=job, preferences=SearchPreferences()),
        include_search_preferences=False,
    )
    assert eligibility.eligible == "pass"
    education_check = next(c for c in eligibility.checks if c.field == "educations")
    assert education_check.education_evidence[0].level == "master"
    for requirement in job.requirements:
        for evidence in requirement.evidence:
            assert RAW[evidence.start_char : evidence.end_char] == evidence.source_text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "invalid", "interrupted"])
async def test_checkpoint_survives_failure_and_new_service_session(db_session, failure):
    job = posting(db_session)
    job_id = job.id
    events = [EXTRACTION, ModelTimeoutError("timeout")]
    expected_error = JDParseFailure
    if failure == "invalid":
        events = [EXTRACTION, {"decisions": []}, {"decisions": []}]
    if failure == "interrupted":
        events = [EXTRACTION, asyncio.CancelledError()]
        expected_error = asyncio.CancelledError
    first = ScriptedClient(events)
    with pytest.raises(expected_error):
        await JobParseService(db_session, ProductJDExecutionParser(first)).parse(
            user_id="a", job_id=job_id
        )
    run = db_session.scalar(select(AgentRun))
    assert (
        run.validation_result["checkpoint"]["extraction"]["requirements"][0][
            "source_text"
        ]
        == CLAUSE
    )
    assert run.output is None
    assert db_session.scalar(select(JobParseResult)) is None
    original_run_id = run.id
    # No reused parser/session instance: the checkpoint must actually be committed.
    with Session(db_session.bind) as resumed_session:
        second = ScriptedClient([RELATIONS])
        execution = await JobParseService(
            resumed_session, ProductJDExecutionParser(second)
        ).parse(user_id="a", job_id=job_id)
        assert [r.schema_name for r in second.requests] == [
            "product_requirement_relations"
        ]
        diagnostics = execution.agent_run.validation_result["execution"]
        assert diagnostics["resumed_extraction"] is True
        assert diagnostics["resumed_from_run_id"] == original_run_id
        assert diagnostics["model_call_count"] == 1
        assert (
            len(diagnostics["attempts"]) == 1
        )  # cached extraction is not billed twice
        third = ScriptedClient([])
        cached = await JobParseService(
            resumed_session, ProductJDExecutionParser(third)
        ).parse(user_id="a", job_id=job_id)
        assert third.requests == []
        assert cached.agent_run.validation_result["execution"]["model_call_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["body", "model", "prompt", "parser", "provider", "schema", "corrupt", "user"],
)
async def test_checkpoint_invalidation(db_session, change):
    job = posting(db_session)
    first = ScriptedClient([EXTRACTION, ModelTimeoutError("timeout")])
    with pytest.raises(JDParseFailure):
        await JobParseService(db_session, ProductJDExecutionParser(first)).parse(
            user_id="a", job_id=job.id
        )
    kwargs = {}
    user_id = "a"
    second = ScriptedClient([EXTRACTION, RELATIONS])
    if change == "body":
        job.raw_content += "联系招聘团队了解详情。"
        job.content_hash = hashlib.sha256(job.raw_content.encode()).hexdigest()
        db_session.commit()
    elif change == "model":
        second = ScriptedClient([EXTRACTION, RELATIONS], model="other-model")
    elif change == "prompt":
        kwargs["prompt_version"] = "changed-prompt"
    elif change == "parser":
        kwargs["parser_version"] = "changed-parser"
    elif change == "provider":
        second.provider = "other-provider"
    elif change == "user":
        user_id = "b"
    elif change == "corrupt":
        run = db_session.scalar(select(AgentRun))
        result = deepcopy(run.validation_result)
        result["checkpoint"]["extraction"]["requirements"][0]["source_text"] = (
            "不存在的条件原文"
        )
        run.validation_result = result
        db_session.commit()
    parser = ProductJDExecutionParser(second, **kwargs)
    if change == "schema":
        original = parser.build_request

        def changed_request(document):
            request = original(document)
            request.json_schema["description"] = "changed contract"
            return request

        parser.build_request = changed_request
    execution = await JobParseService(db_session, parser).parse(
        user_id=user_id, job_id=job.id
    )
    assert len(second.requests) == 2
    assert not execution.agent_run.validation_result["execution"]["resumed_extraction"]


@pytest.mark.asyncio
async def test_failed_extraction_never_becomes_checkpoint(db_session):
    job = posting(db_session)
    client = ScriptedClient([{"unexpected": True}, {"unexpected": True}])
    with pytest.raises(JDParseFailure):
        await JobParseService(db_session, ProductJDExecutionParser(client)).parse(
            user_id="a", job_id=job.id
        )
    run = db_session.scalar(select(AgentRun))
    assert "checkpoint" not in run.validation_result
    assert db_session.scalar(select(JobParseResult)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_field", ["education", "scope", "index", "source"])
async def test_single_call_repairs_invalid_output_with_full_validation(bad_field):
    good = {"extraction": EXTRACTION, "relations": RELATIONS}
    bad = deepcopy(good)
    decision = bad["relations"]["decisions"][0]
    if bad_field == "education":
        decision["education"]["branches"][1]["degree"] = {
            "operator": "any",
            "source_text": "不限专业",
        }
    elif bad_field == "scope":
        decision["education"]["branches"][0]["scope_source_text"] = (
            "正文未出现的范围说明"
        )
    elif bad_field == "index":
        decision["requirement_index"] = 3
    else:
        bad["extraction"]["requirements"][0]["source_text"] = "正文没有的条件"
    client = ScriptedClient(
        [bad, repair_payload() if bad_field in {"education", "scope"} else good]
    )
    parsed = await ProductJDExecutionParser(client, mode="single_call").parse(
        RawJobDocument(raw_content=RAW)
    )
    assert len(client.requests) == 2
    assert [a["status"] for a in parsed.diagnostics["attempts"]] == [
        "validation_failed",
        "passed",
    ]
    assert all(a["stage"] == "combined" for a in parsed.diagnostics["attempts"])


@pytest.mark.asyncio
async def test_single_call_failure_does_not_publish_partial_result_or_auto_switch(
    db_session,
):
    job = posting(db_session)
    client = ScriptedClient(
        [{"extraction": EXTRACTION, "relations": {"decisions": []}}] * 2
    )
    with pytest.raises(JDParseFailure) as error:
        await JobParseService(
            db_session, ProductJDExecutionParser(client, mode="single_call")
        ).parse(user_id="a", job_id=job.id)
    assert error.value.details["model_call_count"] == 2
    assert error.value.details["mode"] == "single_call"
    assert db_session.scalar(select(JobParseResult)) is None
    assert "checkpoint" not in db_session.scalar(select(AgentRun)).validation_result


@pytest.mark.asyncio
async def test_modes_do_not_share_complete_result_cache(db_session):
    job = posting(db_session)
    results = []
    for mode in ("two_stage", "single_call"):
        client = ScriptedClient(outputs(mode))
        result = await JobParseService(
            db_session, ProductJDExecutionParser(client, mode=mode)
        ).parse(user_id="a", job_id=job.id)
        results.append(result.parse_result)
        assert client.requests
    assert results[0].id != results[1].id
    assert results[0].parser_version != results[1].parser_version
    assert results[0].structured_jd == results[1].structured_jd


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["two_stage", "single_call"])
async def test_no_requirements_needs_one_call_and_model_output_honors_mode(mode):
    extraction = {"facts": {}, "requirements": [], "responsibilities": []}
    event = (
        extraction
        if mode == "two_stage"
        else {"extraction": extraction, "relations": {"decisions": []}}
    )
    client = ScriptedClient([event])
    result = await ProductJDExecutionParser(client, mode=mode).parse_model_output(
        RawJobDocument(raw_content=RAW)
    )
    assert result.model_call_count == 1
    assert result.output.requirements == []
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_api_uses_selected_single_call_mode(db_session, monkeypatch):
    job = posting(db_session)
    client = ScriptedClient(outputs("single_call"))
    monkeypatch.setattr(
        jobs_api, "create_structured_model_client", lambda settings: client
    )
    monkeypatch.setattr(
        jobs_api, "get_settings", lambda: Settings(product_parse_mode="single_call")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post(
            f"/api/jobs/{job.id}/parse", headers={"X-User-ID": "a"}
        )
    assert response.status_code == 200, response.text
    assert response.json()["parser_version"].endswith("-single-call")
    assert [r.schema_name for r in client.requests] == ["product_job_inline"]
    assert '"EducationCondition"' in client.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_comparison_does_not_count_valid_json_as_correct_semantics():
    parsed = await ProductJDExecutionParser(
        ScriptedClient(outputs("single_call")), mode="single_call"
    ).parse(RawJobDocument(raw_content=RAW))
    expected = {
        "requirement_count": 1,
        "relations": [{"contains": "硕士", "relation": "any_of", "mandatory": True}],
        "education": [
            {
                "level": "bachelor",
                "operator": "eq",
                "major_mode": "related",
                "scope": "application",
            },
            {
                "level": "master",
                "operator": "eq",
                "major_mode": "any",
                "scope": "application",
            },
        ],
        "qualifications": [],
    }
    assert all(assess(parsed.structured_jd, expected).values())
    parsed.structured_jd.requirements[0].education.branches[0].scope = "historical"
    assert assess(parsed.structured_jd, expected)["education_0"] is False


def test_comparison_usage_marks_missing_data_instead_of_claiming_zero_cost():
    result = {
        "mode": "single_call",
        "status": "failed",
        "correct": False,
        "duration_ms": 10,
        "calls": [{"status": "failed_or_cancelled"}],
    }
    metrics = summary([result])["single_call"]
    assert metrics["model_call_count"] == 1
    assert not metrics["usage_complete"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("本岗位面向2028届毕业生", "simple"),
        ("该职位招收2027届、2028届毕业生。", "simple"),
        ("本岗位面向海外2028届毕业生", "qualified"),
        ("本岗位面向2028届毕业生且须取得硕士学位", "qualified"),
        ("本岗位不面向2028届毕业生", "ambiguous"),
        ("本岗位面向2028届毕业生以外的求职者", "ambiguous"),
    ],
)
def test_cohort_subject_prefix_does_not_discard_restrictive_context(source, expected):
    assert classify_graduation_condition(source) == expected

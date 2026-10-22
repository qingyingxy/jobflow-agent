import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
)
from src.services.discovery_sources import JobStub
from src.services.search_run_metrics import SearchRunMetrics

NOW = datetime(2026, 10, 18, tzinfo=UTC)
QUERY = "2027届上海后端校招"
BASE = JobStub(source_id="official", source_job_id="one", title="后端工程师",
               company="测试公司", locations=["上海"], job_type="campus", published_at=None,
               detail_url="https://example.com/jobs/one", raw_content="岗位职责：负责后端Python服务设计和开发。")


def classify(job=BASE, *, availability="UNKNOWN", verification="VERIFIED_OFFICIAL", age=0, query=QUERY):
    posting = SimpleNamespace(verification_status=verification, availability_status=availability,
                              last_verified_at=NOW - timedelta(days=age), source_url=job.detail_url,
                              recruitment_context={})
    return apply_posting_availability(classify_discovery_job(job, query=query), posting, now=NOW)


def test_relevant_job_is_visible_without_inventing_missing_cohort_or_availability():
    match = classify()
    assert match.review_status == "recommended"
    assert match.filter_status == "pending" and match.match_tier == "expanded"
    checks = {c["field"]: c["status"] for c in match.checks}
    assert checks["graduation_year"] == checks["availability"] == "pending"
    assert match.as_dict(job_posting_id="one")["review_status"] == "recommended"


@pytest.mark.parametrize("job,expected", [
    (replace(BASE, locations=[]), "pending"),
    (replace(BASE, job_type=None), "pending"),
    (replace(BASE, title="储备人才", raw_content="期待优秀应届人才加入团队，共同参与业务发展。"), "pending"),
    (replace(BASE, locations=["深圳"]), "excluded"),
    (replace(BASE, raw_content=BASE.raw_content + "仅限2026届毕业生。"), "excluded"),
    (replace(BASE, raw_content=BASE.raw_content + "境内仅限2026届，海外2027届另行安排。"), "pending"),
])
def test_core_unknowns_and_explicit_conflicts_are_not_promoted(job, expected):
    assert classify(job).review_status == expected


@pytest.mark.parametrize("verification", ["LEGACY_UNVERIFIED", "USER_PROVIDED"])
def test_unverified_source_cannot_be_promoted_on_unknown_availability(verification):
    assert classify(verification=verification).review_status == "pending"


def test_closed_excluded_stale_visible_with_warning_and_confirmed_remains_distinct():
    assert classify(availability="CLOSED").review_status == "excluded"
    stale = classify(age=9)
    assert stale.review_status == "recommended" and stale.filter_status == "pending"
    assert "待更新" in stale.checks[-1]["reason"]
    confirmed = classify(replace(BASE, raw_content=BASE.raw_content + "面向2027届毕业生。"), availability="ACTIVE")
    assert confirmed.review_status == "recommended" and confirmed.filter_status == "matched"


def test_additional_required_conditions_remain_required():
    assert classify(query=QUERY + "，必须精通Rust").review_status == "pending"


def test_priority_metrics_do_not_inflate_fully_confirmed_or_repeat_counts():
    metrics = SearchRunMetrics(NOW, {"old": {"filter_status": "pending", "review_status": "pending"},
                                    "legacy": {"filter_status": "pending"}},
                               clock=lambda: NOW + timedelta(seconds=1))
    metrics.publish("new", False, recommended=True)
    metrics.publish("new", False, recommended=True)
    metrics.publish("old", False, recommended=True, fresh=True)
    metrics.publish("legacy", False, recommended=True)
    result = metrics.snapshot()
    assert result["first_recommended_ms"] == result["first_fresh_recommended_ms"] == 1000
    assert result["first_useful_ms"] is None
    assert result["new_recommended_jobs"] == result["resolved_recommended_jobs"] == 1
    assert result["recommended_jobs"] == 3
    assert result["new_effective_jobs"] == result["resolved_effective_jobs"] == 0
    metrics.publish("new", False, recommended=False)
    assert metrics.snapshot()["new_recommended_jobs"] == 0
    metrics.baseline["changed"] = {"filter_status": "excluded", "review_status": "excluded"}
    metrics.publish("changed", False, recommended=True)
    assert metrics.snapshot()["resolved_recommended_jobs"] == 2


def test_fixed_official_sources_keep_product_and_do_not_hide_relevant_unknowns():
    from scripts.evaluate_job_review_acceptance import frozen_results

    root = Path(__file__).resolve().parents[1]
    dataset = json.loads((root / "datasets/real_job_understanding_acceptance_20261018.json").read_text(encoding="utf-8"))
    recorded = json.loads((root / "datasets/real_job_understanding_recorded_v3_20261018.json").read_text(encoding="utf-8"))
    rows = frozen_results(dataset, recorded, NOW)
    assert len(rows) == 11
    assert sum(r["review_status"] == "recommended" for r in rows) == 6
    for row in rows:
        assert row["review_status"] == row["expected_review_status"], row["title"]
        assert row["filter_status"] == row["expected_filter_status"], row["title"]
        assert all(row["actual_fields"][f] == status for f, status in row["expected_fields"].items()), row["title"]
    product = next(r for r in rows if "AI产品经理" in r["title"])
    assert product["review_status"] == "recommended" and product["filter_status"] == "pending"
    # Replaying an output for changed public text must fail, not silently certify it.
    dataset["samples"][0]["raw_content"] += "本岗位已关闭。"
    with pytest.raises(ValueError, match="Frozen source changed"):
        frozen_results(dataset, recorded, NOW)

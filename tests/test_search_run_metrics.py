from datetime import UTC, datetime, timedelta

from src.services.search_run_metrics import SearchRunMetrics


def test_first_new_recommendation_does_not_count_refreshed_or_pending_jobs():
    start = datetime(2026, 10, 19, tzinfo=UTC)
    now = start
    metrics = SearchRunMetrics(start, {"old": {}}, clock=lambda: now)
    metrics.publish("old", True, fresh=True, recommended=True)
    metrics.publish("new-pending", True, fresh=True, recommended=False)
    assert metrics.snapshot()["first_new_recommended_ms"] is None
    now += timedelta(seconds=12)
    metrics.publish("new", True, recommended=True)
    now += timedelta(seconds=3)
    metrics.publish("another", True, recommended=True)
    assert metrics.snapshot()["first_new_recommended_ms"] == 12000
    assert metrics.snapshot()["new_recommended_jobs"] == 2


def test_metrics_separate_fresh_reads_cache_retries_and_new_or_resolved_jobs():
    start = datetime(2026, 10, 17, tzinfo=UTC)
    metrics = SearchRunMetrics(start, {"old": {"filter_status": "matched"},
                                      "pending": {"filter_status": "pending"}},
                               clock=lambda: start + timedelta(seconds=2))
    assert metrics.snapshot()["read_success_rate"] is None
    metrics.cache_hit("cached")
    metrics.publish("old", True)
    metrics.start_read("recovered", previous={"last_failure_code": "browser_timeout", "mode": "cooldown"})
    metrics.finish_read("recovered", success=True)
    metrics.start_read("recovered")  # Same URL via another query is one observation.
    metrics.publish("pending", True)
    metrics.publish("pending", True)
    metrics.start_read("failed")
    metrics.publish("new", True)
    result = metrics.snapshot()
    assert result["read_success_rate"] == 0.5
    assert result["read_attempts"] == 2
    assert result["retry_recovered"] == result["retry_attempts"] == 1
    assert result["new_effective_jobs"] == result["resolved_effective_jobs"] == 1
    assert result["effective_job_gain"] == 2
    assert result["first_result_ms"] == result["first_useful_ms"] == 2000
    metrics.publish("new", False)  # A late direction review may invalidate a result.
    assert metrics.snapshot()["new_effective_jobs"] == 0


def test_budget_deferral_and_previously_successful_evidence_are_not_recoveries():
    metrics = SearchRunMetrics(datetime.now(UTC), {})
    for i, state in enumerate([
        {"last_failure_code": "verification_budget_exhausted"},
        {"last_failure_code": "browser_timeout", "mode": "succeeded", "last_outcome": "verified"},
    ]):
        metrics.start_read(str(i), previous=state)
        metrics.finish_read(str(i), success=True)
    metrics.cache_hit("previously_failed_but_cached")
    assert metrics.snapshot()["retry_attempts"] == 0
    assert metrics.snapshot()["retry_recovered"] == 0
    assert metrics.snapshot()["first_result_ms"] is None

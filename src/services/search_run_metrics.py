"""Per-run measurements; cached evidence is never a successful fresh read."""

from datetime import UTC, datetime
from statistics import median

from src.services.lead_retry import DEFERRED, utc_time


class SearchRunMetrics:
    def __init__(self, started_at, baseline, *, clock=None):
        self.started_at = utc_time(started_at)
        self.baseline = baseline or {}
        self.clock = clock or (lambda: datetime.now(UTC))
        self.reads = {}
        self.sources = {}
        self.cached = set()
        self.results = {}
        self.recommended = {}
        self.first_result_ms = None
        self.first_useful_ms = None
        self.first_fresh_useful_ms = None
        self.first_recommended_ms = None
        self.first_fresh_recommended_ms = None
        self.first_new_recommended_ms = None
        self.first_three_recommended_ms = None
        self.first_three_new_recommended_ms = None
        self.first_three_effective_ms = None
        self.performance = {}
        self.result_windows = {30: {}, 60: {}}

    def observe(self, kind, details):
        if kind not in {"transport", "source_understanding", "verification", "role_review_queue", "search_query"}:
            return
        # Budget-skipped calls have not spent model time.
        if not isinstance(details.get("duration_ms"), (int, float)):
            return
        key = f"{kind}:{details['stage']}" if details.get("stage") else kind
        bucket = self.performance.setdefault(key, {"calls": 0, "timeouts": 0, "errors": 0,
                                                   "duration_ms": [], "queue_wait_ms": []})
        bucket["calls"] += 1
        error = details.get("error_code")
        bucket["timeouts"] += int(bool(error and "timeout" in error.lower()))
        bucket["errors"] += int(bool(error))
        for name in ("duration_ms", "queue_wait_ms"):
            if isinstance(details.get(name), (int, float)) and len(bucket[name]) < 1000:
                bucket[name].append(details[name])

    def start_read(self, url, *, previous=None):
        previous = previous or {}
        recovered_candidate = bool(
            previous.get("last_failure_code")
            and previous["last_failure_code"] not in DEFERRED
            and previous.get("last_outcome") != "verified"
            and previous.get("mode") != "succeeded"
        )
        self.reads.setdefault(url, {"success": False, "retry": recovered_candidate})

    def finish_read(self, url, *, success):
        if url in self.reads:
            self.reads[url]["success"] |= success

    def cache_hit(self, url):
        self.cached.add(url)

    def source_read(self, source_id, *, success, retry=False):
        value = self.sources.setdefault(source_id, {"success": False, "retry": False})
        value["success"] |= success
        value["retry"] |= retry

    def publish(self, job_id, useful, *, fresh=False, recommended=None):
        recommended = useful if recommended is None else recommended
        elapsed = max(0, int((self.clock() - self.started_at).total_seconds() * 1000))
        if self.first_result_ms is None:
            self.first_result_ms = elapsed
        if useful and self.first_useful_ms is None:
            self.first_useful_ms = elapsed
        if useful and fresh and self.first_fresh_useful_ms is None:
            self.first_fresh_useful_ms = elapsed
        if recommended and self.first_recommended_ms is None:
            self.first_recommended_ms = elapsed
        if recommended and fresh and self.first_fresh_recommended_ms is None:
            self.first_fresh_recommended_ms = elapsed
        if recommended and job_id not in self.baseline and self.first_new_recommended_ms is None:
            self.first_new_recommended_ms = elapsed
        self.results[job_id] = useful
        self.recommended[job_id] = recommended
        current = {key for key, value in self.recommended.items() if value}
        new = current - self.baseline.keys()
        if len(current) >= 3 and self.first_three_recommended_ms is None:
            self.first_three_recommended_ms = elapsed
        if len(new) >= 3 and self.first_three_new_recommended_ms is None:
            self.first_three_new_recommended_ms = elapsed
        if sum(self.results.values()) >= 3 and self.first_three_effective_ms is None:
            self.first_three_effective_ms = elapsed
        for seconds in self.result_windows:
            if elapsed <= seconds * 1000:
                self.result_windows[seconds] = {"recommended": len(current), "new_recommended": len(new),
                                               "effective": sum(self.results.values())}

    def snapshot(self):
        attempts = len(self.reads)
        successful = sum(r["success"] for r in self.reads.values())
        useful = {k for k, v in self.results.items() if v}
        new_useful = useful - self.baseline.keys()
        promoted = {k for k in useful & self.baseline.keys()
                    if self.baseline[k].get("filter_status") != "matched"}
        recommended = {k for k, v in self.recommended.items() if v}
        newly_recommended = recommended - self.baseline.keys()
        promoted_recommended = {k for k in recommended & self.baseline.keys()
                               if self.baseline[k].get("review_status") in {"pending", "excluded"}}
        return {
            "version": 5,
            "first_three_recommended_ms": self.first_three_recommended_ms,
            "first_three_new_recommended_ms": self.first_three_new_recommended_ms,
            "first_three_effective_ms": self.first_three_effective_ms,
            "result_windows": {str(k): v or {"recommended": 0, "new_recommended": 0, "effective": 0}
                               for k, v in self.result_windows.items()},
            "performance": {key: {**{k: b[k] for k in ("calls", "timeouts", "errors")},
                **{name + "_median": round(median(b[name]), 1) if b[name] else None
                   for name in ("duration_ms", "queue_wait_ms")}}
                for key, b in self.performance.items()},
            "first_new_recommended_ms": self.first_new_recommended_ms,
            "first_recommended_ms": self.first_recommended_ms,
            "first_fresh_recommended_ms": self.first_fresh_recommended_ms,
            "recommended_jobs": len(recommended),
            "new_recommended_jobs": len(newly_recommended),
            "resolved_recommended_jobs": len(promoted_recommended),
            "recommended_job_gain": len(newly_recommended | promoted_recommended),
            "first_fresh_useful_ms": self.first_fresh_useful_ms,
            "source_read_attempts": len(self.sources),
            "source_read_successes": sum(s["success"] for s in self.sources.values()),
            "source_read_success_rate": round(sum(s["success"] for s in self.sources.values()) / len(self.sources), 4) if self.sources else None,
            "source_retry_attempts": sum(s["retry"] for s in self.sources.values()),
            "source_retry_recovered": sum(s["retry"] and s["success"] for s in self.sources.values()),
            "first_result_ms": self.first_result_ms,
            "first_useful_ms": self.first_useful_ms,
            "read_attempts": attempts,
            "read_successes": successful,
            "read_success_rate": round(successful / attempts, 4) if attempts else None,
            "cache_hits": len(self.cached),
            "retry_attempts": sum(r["retry"] for r in self.reads.values()),
            "retry_recovered": sum(r["retry"] and r["success"] for r in self.reads.values()),
            "new_effective_jobs": len(new_useful),
            "resolved_effective_jobs": len(promoted),
            "effective_job_gain": len(new_useful | promoted),
        }

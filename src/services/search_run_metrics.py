"""Per-run measurements; cached evidence is never a successful fresh read."""

from datetime import UTC, datetime

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
            "version": 4,
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

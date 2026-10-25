"""Bounded browser diagnostics without cookies, request bodies or URL query values."""
from time import monotonic
from urllib.parse import urlsplit


def diagnostic_url(url):
    try:
        parsed = urlsplit(url)
        # Strip URL credentials, fragments, query values and servlet session identifiers.
        path = parsed.path.split(";", 1)[0]
        return f"{parsed.scheme}://{parsed.hostname or ''}{path}"[:400]
    except ValueError:
        return "invalid_url"


class BrowserReadTrace:
    def __init__(self, url):
        self.started = monotonic()
        self.finished = None
        self.url = diagnostic_url(url)
        self.phases = []
        self.network = []
        self.status = "running"
        self.failure_phase = None
        self.dropped_events = 0
        self.current_phase = "start"

    def phase(self, name, **details):
        now = self.elapsed()
        self.current_phase = name
        if self.phases and "elapsed_ms" not in self.phases[-1]:
            self.phases[-1]["elapsed_ms"] = now - self.phases[-1]["started_ms"]
        if len(self.phases) < 60:
            self.phases.append({"phase": name, "started_ms": now, **details})

    def event(self, kind, url, **details):
        if len(self.network) < 100:
            self.network.append({"event": kind, "url": diagnostic_url(url), "at_ms": self.elapsed(), **details})
        else:
            self.dropped_events += 1

    def elapsed(self):
        return round(((self.finished if self.finished is not None else monotonic()) - self.started) * 1000)

    def finish(self, status, error_type=None):
        self.finished = monotonic()
        self.status = status
        if self.phases and "elapsed_ms" not in self.phases[-1]:
            self.phases[-1]["elapsed_ms"] = self.elapsed() - self.phases[-1]["started_ms"]
        if status != "success" and not self.failure_phase:
            self.failure_phase = self.current_phase
        self.error_type = error_type

    def snapshot(self):
        return {"url": self.url, "status": self.status, "elapsed_ms": self.elapsed(),
                "failure_phase": self.failure_phase, "phases": [dict(p) for p in self.phases],
                "network": list(self.network), "dropped_events": self.dropped_events,
                "error_type": getattr(self, "error_type", None)}

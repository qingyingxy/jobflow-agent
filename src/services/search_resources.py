"""Bounded transport work and provider-wide interpretation capacity.

Only the actual I/O holds a transport slot. A saved page can wait for its
interpretation without preventing another candidate from being downloaded.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from weakref import WeakKeyDictionary


@dataclass
class _Waiter:
    priority: int
    sequence: int
    queued_at: float
    future: asyncio.Future
    granted: bool = False


class ModelCapacity:
    def __init__(self, limit):
        self.limit = limit
        self.active = 0
        self.background_active = 0
        self.waiters = []
        self.sequence = 0
        self.foreground_runs = 0

    @asynccontextmanager
    async def foreground(self):
        self.foreground_runs += 1
        try:
            yield
        finally:
            self.foreground_runs -= 1
            self.dispatch()

    def dispatch(self):
        while self.active < self.limit:
            foreground_waiting = self.foreground_runs or any(
                w.priority < 2 and not w.future.done() for w in self.waiters)
            eligible = [w for w in self.waiters if not w.future.done()
                        and (w.priority < 2 or self.background_active < 1 or not foreground_waiting)
                        and (w.priority < 3 or not self.foreground_runs)]
            if not eligible:
                return
            # Aging prevents historical work from being permanently starved.
            now = monotonic()
            waiter = min(eligible, key=lambda w: (
                max(0, w.priority - int((now - w.queued_at) / 30)), w.sequence))
            self.waiters.remove(waiter)
            waiter.granted = True
            self.active += 1
            self.background_active += int(waiter.priority >= 2)
            waiter.future.set_result(None)

    @asynccontextmanager
    async def slot(self, priority=0):
        waiter = _Waiter(priority, self.sequence, monotonic(),
                         asyncio.get_running_loop().create_future())
        self.sequence += 1
        self.waiters.append(waiter)
        self.dispatch()
        try:
            await waiter.future
            yield
        finally:
            if waiter.granted:
                self.active -= 1
                self.background_active -= int(priority >= 2)
            elif waiter in self.waiters:
                self.waiters.remove(waiter)
            self.dispatch()


_model_capacities = WeakKeyDictionary()


def model_capacity(settings, client=None):
    from src.services.semantic_retry import provider_key

    capacities = _model_capacities.setdefault(asyncio.get_running_loop(), {})
    key = provider_key(settings, client)
    if key not in capacities:
        capacities[key] = ModelCapacity(settings.web_search_semantic_concurrency)
    return capacities[key]


class BoundedReader:
    """Preserve reader capabilities while independently bounding transport calls."""

    def __init__(self, reader, *, limit, stage, on_event):
        object.__setattr__(self, "_reader", reader)
        object.__setattr__(self, "_slots", asyncio.Semaphore(limit))
        object.__setattr__(self, "_stage", stage)
        object.__setattr__(self, "_on_event", on_event)

    def __setattr__(self, name, value):
        setattr(self._reader, name, value)

    def __getattr__(self, name):
        method = getattr(self._reader, name)
        if name not in {"fetch", "fetch_json", "post_json", "read", "read_evidence",
                        "read_listing", "read_search_listing", "read_dynamic_listing"}:
            return method

        async def bounded(*args, **kwargs):
            queued = monotonic()
            async with self._slots:
                started = monotonic()
                error = None
                try:
                    return await method(*args, **kwargs)
                except BaseException as exc:
                    error = getattr(exc, "code", type(exc).__name__)
                    raise
                finally:
                    self._on_event("transport", {
                        "stage": self._stage, "url": args[0] if args else kwargs.get("url"),
                        "queue_wait_ms": int((started - queued) * 1000),
                        "duration_ms": int((monotonic() - started) * 1000),
                        "error_code": error,
                    })

        return bounded

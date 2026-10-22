"""Bounded transport recovery shared by both product parsing modes."""

from __future__ import annotations

import asyncio
from time import perf_counter

from src.infrastructure.llm_client import ModelClientError, is_retryable_model_error
from src.services.jd_parser import JDParserError


class ParseExecutionBudget:
    def __init__(
        self, *, timeout_seconds, max_calls, transport_retries, backoff_seconds
    ):
        self.deadline = perf_counter() + timeout_seconds
        self.max_calls = max_calls
        self.transport_retries = transport_retries
        self.backoff_seconds = backoff_seconds

    def remaining_seconds(self):
        return max(0.0, self.deadline - perf_counter())

    def check(self, stage, attempts):
        self.check_time(stage)
        if len(attempts) >= self.max_calls:
            raise JDParserError(
                "model_call_budget_exhausted",
                "岗位解析已达到模型调用次数上限",
                {"stage": stage},
            )

    def check_time(self, stage):
        if self.remaining_seconds() <= 0:
            raise JDParserError(
                "model_timeout",
                "岗位解析已达到总耗时上限",
                {"stage": stage, "timeout_scope": "parse_run"},
            )

    async def generate(self, client, request, *, stage, attempt, attempts):
        # The parser owns recovery; disable hidden retries in the HTTP client.
        request = request.model_copy(update={"transport_retries": 0})
        for retry in range(self.transport_retries + 1):
            self.check(stage, attempts)
            started = perf_counter()
            details = {
                "stage": stage,
                "attempt": attempt,
                "transport_attempt": retry + 1,
                "status": "started",
            }
            attempts.append(details)
            try:
                async with asyncio.timeout(self.remaining_seconds()):
                    response = await client.generate(request)
            except asyncio.CancelledError:
                details.update(status="cancelled", duration_ms=_duration(started))
                raise
            except TimeoutError as error:
                details.update(
                    status="model_error",
                    duration_ms=_duration(started),
                    error_code="model_timeout",
                    timeout_scope="parse_run",
                )
                raise JDParserError(
                    "model_timeout",
                    "岗位解析已达到总耗时上限",
                    {"stage": stage, "timeout_scope": "parse_run"},
                ) from error
            except Exception as error:
                details.update(status="model_error", duration_ms=_duration(started))
                if not isinstance(error, ModelClientError):
                    raise JDParserError(
                        "model_error", "产品 JD 模型调用失败", {"stage": stage}
                    ) from error
                safe = {
                    key: error.details[key]
                    for key in (
                        "status_code",
                        "timeout_scope",
                        "timeout_stage",
                        "usage",
                        "response_id",
                        "finish_reason",
                    )
                    if key in error.details
                }
                details.update(error_code=error.code, **safe)
                delay = min(self.backoff_seconds * (2**retry), 10.0)
                reason = (
                    "non_retryable"
                    if not is_retryable_model_error(error)
                    else "retry_limit"
                    if retry >= self.transport_retries
                    else "call_budget"
                    if len(attempts) >= self.max_calls
                    else "time_budget"
                    if self.remaining_seconds() <= delay
                    else None
                )
                if reason:
                    details["recovery_skipped"] = reason
                    raise JDParserError(
                        error.code,
                        str(error),
                        {"stage": stage, **safe, "recovery_skipped": reason},
                    ) from error
                details.update(retry_scheduled=True, retry_delay_seconds=delay)
                if delay:
                    await asyncio.sleep(delay)
                continue
            details.update(
                duration_ms=_duration(started),
                usage=response.usage,
                response_id=response.response_id,
                finish_reason=response.finish_reason,
            )
            return response, details
        raise AssertionError("unreachable")


def _duration(started):
    return round((perf_counter() - started) * 1000, 2)

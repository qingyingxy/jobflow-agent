from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from time import perf_counter
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class StructuredModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str
    json_schema: dict[str, Any]
    messages: list[ChatMessage]
    prompt_version: str
    max_output_tokens: int | None = Field(default=None, gt=0)


class StructuredModelResponse(BaseModel):
    output: dict[str, Any]
    model: str
    provider: str
    response_id: str | None = None
    finish_reason: str | None = None
    request_duration_ms: float | None = Field(default=None, ge=0)
    usage: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ModelClientError(RuntimeError):
    code = "model_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ModelTimeoutError(ModelClientError):
    code = "model_timeout"


class ModelUnavailableError(ModelClientError):
    code = "model_unavailable"


class ModelResponseError(ModelClientError):
    code = "model_response_invalid"


class StructuredModelClient(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def provider(self) -> str: ...

    async def generate(
        self,
        request: StructuredModelRequest,
    ) -> StructuredModelResponse: ...


class FakeModelClient:
    """Deterministic model double used by local development and tests."""

    provider = "fake"

    def __init__(
        self,
        output: dict[str, Any] | None = None,
        error: Exception | None = None,
        model: str = "fake-jd-parser",
        outputs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.output = output
        self.outputs = copy.deepcopy(outputs) if outputs is not None else None
        self.error = error
        self._model = model
        self.last_request: StructuredModelRequest | None = None
        self.requests: list[StructuredModelRequest] = []
        self._output_index = 0

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.last_request = request
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.outputs is not None:
            if self._output_index >= len(self.outputs):
                raise RuntimeError("FakeModelClient outputs exhausted")
            output = self.outputs[self._output_index]
            self._output_index += 1
        else:
            output = self.output if self.output is not None else {"field_evidence": []}
        return StructuredModelResponse(
            output=copy.deepcopy(output),
            model=self.model_name,
            provider=self.provider,
        )


class DemoModelClient:
    """Deterministic schema-aware fake used by the local M7 walkthrough."""

    provider = "fake"

    def __init__(self, model: str = "fake-jobflow-demo") -> None:
        self._model = model
        self.last_request: StructuredModelRequest | None = None

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.last_request = request
        if request.schema_name == "job_description":
            output = _demo_job_description(request)
        elif request.schema_name == "product_job_description":
            output = _demo_product_job_description(request)
        elif request.schema_name == "product_job_extraction":
            output = _demo_product_job_extraction(request)
        elif request.schema_name == "product_requirement_relations":
            output = _demo_product_requirement_relations(request)
        elif request.schema_name == "core_job_fields":
            output = _demo_core_job_fields(request)
        elif request.schema_name == "detail_job_fields":
            output = _demo_detail_job_fields(request)
        elif request.schema_name == "requirement_match":
            output = _demo_requirement_match(request)
        elif request.schema_name == "resume_suggestion":
            output = _demo_resume_suggestion(request)
        elif request.schema_name == "resume_evidence":
            output = _demo_resume_evidence(request)
        else:
            output = {}
        return StructuredModelResponse(
            output=output,
            model=self.model_name,
            provider=self.provider,
        )


def _demo_job_description(request: StructuredModelRequest) -> dict[str, Any]:
    user_prompt = "\n".join(
        message.content for message in request.messages if message.role == "user"
    )
    content = user_prompt
    for tag in ("job_description", "job_description_clauses"):
        match = re.search(
            rf"<{tag}>\s*(.*?)\s*</{tag}>",
            user_prompt,
            re.DOTALL,
        )
        if match is not None:
            content = match.group(1).strip()
            break
    output: dict[str, Any] = {"field_evidence": []}
    field_evidence: list[dict[str, Any]] = []

    company_match = re.search(r"([\u4e00-\u9fffA-Za-z0-9]{2,24}公司)", content)
    if company_match:
        output["company"] = company_match.group(1)
        field_evidence.append(
            {"field_path": "company", "source_text": company_match.group(1)}
        )

    title_match = re.search(
        r"(AI\s*应用开发实习生|[\u4e00-\u9fffA-Za-z0-9 /+-]{2,30}(?:工程师|实习生|开发岗|算法岗))",
        content,
    )
    if title_match:
        title = title_match.group(1).strip()
        output["title"] = title
        field_evidence.append({"field_path": "title", "source_text": title})

    job_type = None
    job_type_source = None
    for candidate, source in (
        ("internship", "实习"),
        ("campus", "校招"),
        ("full_time", "全职"),
        ("part_time", "兼职"),
    ):
        if source in content:
            job_type = candidate
            job_type_source = source
            break
    if job_type is not None and job_type_source is not None:
        output["job_type"] = job_type
        field_evidence.append(
            {"field_path": "job_type", "source_text": job_type_source}
        )

    locations = [
        location
        for location in ("北京", "上海", "广州", "深圳", "杭州", "南京", "成都")
        if location in content
    ]
    if locations:
        output["locations"] = locations
        field_evidence.append(
            {"field_path": "locations", "source_text": locations[0]}
        )

    skill_terms = (
        ("RAG", "RAG"),
        ("Python", "Python"),
        ("FastAPI", "FastAPI"),
        ("BM25", "BM25"),
        ("Vector Search", "向量检索"),
        ("Reranker", "rerank"),
    )
    skill_pairs = [
        (name, phrase)
        for name, phrase in skill_terms
        if phrase.casefold() in content.casefold()
    ]
    skills = [name for name, _ in skill_pairs]
    if skill_pairs:
        requirements = [
            {
                "category": "required_skill",
                "name": skill,
                "description": f"岗位文本提到 {skill}",
                "mandatory": True,
                "evidence": [
                    {
                        "field_path": f"requirements[{index}]",
                        "source_text": phrase,
                    }
                ],
            }
            for index, (skill, phrase) in enumerate(
                item for item in skill_pairs
            )
        ]
        output["required_skills"] = skills
        output["requirements"] = requirements
        field_evidence.append(
            {"field_path": "required_skills", "source_text": skill_pairs[0][1]}
        )
        field_evidence.extend(
            {
                "field_path": f"requirements[{index}]",
                "source_text": requirement["evidence"][0]["source_text"],
            }
            for index, requirement in enumerate(requirements)
        )

    output["field_evidence"] = field_evidence
    return output


def _demo_product_job_description(
    request: StructuredModelRequest,
) -> dict[str, Any]:
    legacy = _demo_job_description(request)
    evidence_by_path = {
        item["field_path"]: item["source_text"]
        for item in legacy.get("field_evidence", [])
    }
    facts: dict[str, Any] = {}
    if legacy.get("job_type") and evidence_by_path.get("job_type"):
        facts["job_type"] = {
            "value": legacy["job_type"],
            "source_text": evidence_by_path["job_type"],
        }
    if legacy.get("locations") and evidence_by_path.get("locations"):
        facts["locations"] = {
            "values": legacy["locations"],
            "source_text": evidence_by_path["locations"],
        }

    requirements = []
    for index, requirement in enumerate(legacy.get("requirements") or []):
        source_text = requirement["evidence"][0]["source_text"]
        requirements.append(
            {
                "source_text": source_text,
                "level": (
                    "preferred"
                    if requirement["category"] == "preferred_skill"
                    else "required"
                ),
                "relation": "all_of",
                "items": [source_text],
            }
        )

    user_prompt = "\n".join(
        message.content for message in request.messages if message.role == "user"
    )
    content_match = re.search(
        r"<job_description>\s*(.*?)\s*</job_description>",
        user_prompt,
        re.DOTALL,
    )
    content = content_match.group(1) if content_match else user_prompt
    responsibilities = [
        item.strip()
        for item in re.findall(r"负责[^，。；;\n]+", content)
        if item.strip()
    ]
    return {
        "facts": facts,
        "requirements": requirements,
        "responsibilities": responsibilities,
    }


def _demo_product_job_extraction(
    request: StructuredModelRequest,
) -> dict[str, Any]:
    output = _demo_product_job_description(request)
    return {
        "facts": output["facts"],
        "requirements": [
            {
                "source_text": requirement["source_text"],
                "level": requirement["level"],
            }
            for requirement in output["requirements"]
        ],
        "responsibilities": output["responsibilities"],
    }


def _demo_product_requirement_relations(
    request: StructuredModelRequest,
) -> dict[str, Any]:
    user_prompt = "\n".join(
        message.content for message in request.messages if message.role == "user"
    )
    match = re.search(
        r"<requirements_json>\s*(.*?)\s*</requirements_json>",
        user_prompt,
        re.DOTALL,
    )
    try:
        requirements = json.loads(match.group(1)) if match else []
    except json.JSONDecodeError:
        requirements = []
    if not isinstance(requirements, list):
        requirements = []
    return {
        "decisions": [
            {
                "requirement_index": int(requirement["requirement_index"]),
                "relation": "all_of",
                "items": [str(requirement["source_text"])],
                "reason": "演示客户端保守地保留完整条件。",
            }
            for requirement in requirements
            if isinstance(requirement, dict)
            and isinstance(requirement.get("requirement_index"), int)
            and isinstance(requirement.get("source_text"), str)
        ]
    }


def _demo_core_job_fields(request: StructuredModelRequest) -> dict[str, Any]:
    output = _demo_job_description(request)
    skill_clauses = [
        {
            "source_text": requirement["evidence"][0]["source_text"],
            "strength": "required",
            "relation": "all_of",
            "skills": [requirement["name"]],
        }
        for requirement in output.get("requirements") or []
        if requirement.get("category") == "required_skill"
        and requirement.get("evidence")
    ]
    return {
        "job_type": output.get("job_type"),
        "locations": output.get("locations"),
        "skill_clauses": skill_clauses or None,
    }


def _demo_detail_job_fields(request: StructuredModelRequest) -> dict[str, Any]:
    output = _demo_job_description(request)
    return {
        field_name: output.get(field_name)
        for field_name in (
            "company",
            "title",
            "graduation_years",
            "recruitment_batch",
            "education_requirements",
            "major_requirements",
            "preferred_skills",
            "internship_duration_months",
            "weekly_days",
            "earliest_start_date",
            "deadline",
            "application_url",
            "qualification_conditions",
            "requirements",
        )
    }


def _demo_requirement_match(request: StructuredModelRequest) -> dict[str, Any]:
    content = request.messages[-1].content
    evidence_marker = "候选证据："
    evidence_text = content.split(evidence_marker, 1)[-1]
    try:
        candidates = json.loads(evidence_text)
    except json.JSONDecodeError:
        candidates = []
    if not isinstance(candidates, list) or not candidates:
        return {
            "support_level": "unsupported",
            "evidence_ids": [],
            "explanation": "没有找到可以验证该岗位要求的当前用户经历证据。",
            "claims": [],
        }
    candidate = candidates[0]
    evidence_id = str(candidate.get("id", ""))
    title = str(candidate.get("title", "当前项目"))
    claim = str(candidate.get("claim", ""))
    return {
        "support_level": "supported",
        "evidence_ids": [evidence_id],
        "explanation": f"证据支持该岗位要求：{claim or title}",
        "claims": [],
    }


def _demo_resume_suggestion(request: StructuredModelRequest) -> dict[str, Any]:
    content = "\n".join(message.content for message in request.messages)
    original_match = re.search(
        r"<original_text>\s*(.*?)\s*</original_text>",
        content,
        re.DOTALL,
    )
    original = original_match.group(1).strip() if original_match else ""
    evidence_match = re.search(
        r"<candidate_evidence>\s*(.*?)\s*</candidate_evidence>",
        content,
        re.DOTALL,
    )
    try:
        candidates = json.loads(evidence_match.group(1)) if evidence_match else []
    except json.JSONDecodeError:
        candidates = []
    if not isinstance(candidates, list) or not candidates:
        return {
            "suggestion_text": original or "请补充一条可编辑的经历描述。",
            "evidence_ids": [],
            "claims": [],
        }

    candidate = candidates[0]
    evidence_id = str(candidate.get("id", ""))
    claim = str(candidate.get("claim", "")).strip()
    suggestion_text = original
    if claim and claim not in suggestion_text:
        suggestion_text = f"{suggestion_text}；补充经历：{claim}"
    return {
        "suggestion_text": suggestion_text,
        "evidence_ids": [evidence_id],
        "claims": [claim] if claim else [],
    }


def _demo_resume_evidence(request: StructuredModelRequest) -> dict[str, Any]:
    content = "\n".join(
        message.content for message in request.messages if message.role == "user"
    )
    match = re.search(r"<resume>\s*(.*?)\s*</resume>", content, re.DOTALL)
    resume_text = match.group(1).strip() if match else ""
    claim = resume_text[:2000].strip()
    first_line = next(
        (line.strip() for line in resume_text.splitlines() if line.strip()),
        "简历经历",
    )
    known_skills = [
        skill
        for skill in ("Python", "Java", "JavaScript", "TypeScript", "MATLAB", "SQL")
        if skill.casefold() in resume_text.casefold()
    ]
    return {
        "evidence": [
            {
                "type": "other",
                "title": first_line[:160],
                "claim": claim,
                "skills": known_skills,
            }
        ]
    }


class OpenAICompatibleModelClient:
    """Small dependency-light client for OpenAI-compatible JSON-schema APIs."""

    provider = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        response_format: Literal["json_schema", "json_object"] = "json_schema",
        thinking_mode: Literal["enabled", "disabled"] | None = None,
        reasoning_effort: Literal[
            "none", "minimal", "low", "medium", "high", "xhigh"
        ]
        | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = (
            base_url.rstrip("/")
            if base_url.rstrip("/").endswith("/chat/completions")
            else f"{base_url.rstrip('/')}/chat/completions"
        )
        self._api_key = api_key
        self._model = model
        self._response_format = response_format
        self._thinking_mode = thinking_mode
        self._reasoning_effort = reasoning_effort
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._transport = transport

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def reasoning_effort(self) -> str | None:
        return self._reasoning_effort

    @property
    def response_format(self) -> str:
        return self._response_format

    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        last_error: ModelClientError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._generate_once(request)
            except ModelClientError as error:
                last_error = error
                if attempt >= self._max_retries or not self._is_retryable(error):
                    raise
                delay = self._retry_backoff_seconds * (2**attempt)
                if delay:
                    await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    async def _generate_once(
        self,
        request: StructuredModelRequest,
    ) -> StructuredModelResponse:
        request_started = perf_counter()
        if self._response_format == "json_object":
            response_format: dict[str, Any] = {"type": "json_object"}
        else:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.json_schema,
                },
            }
        payload = {
            "model": self.model_name,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": 0,
            "response_format": response_format,
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if self._thinking_mode is not None:
            payload["thinking"] = {"type": self._thinking_mode}
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        client_options: dict[str, Any] = {"timeout": self._timeout_seconds}
        if self._transport is not None:
            client_options["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_options) as client:
                response = await client.post(
                    self._endpoint,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise ModelTimeoutError(
                "结构化模型请求超时",
                {
                    "timeout_scope": "http_request",
                    "timeout_stage": _httpx_timeout_stage(error),
                    "timeout_seconds": self._timeout_seconds,
                    "request_duration_ms": round(
                        (perf_counter() - request_started) * 1000,
                        2,
                    ),
                },
            ) from error
        except httpx.HTTPError as error:
            raise ModelUnavailableError("无法连接结构化模型服务") from error

        if response.status_code >= 400:
            raise ModelResponseError(
                "结构化模型服务返回错误",
                {
                    "status_code": response.status_code,
                    "response_format": self._response_format,
                },
            )

        try:
            body = response.json()
            choice = body["choices"][0]
            if not isinstance(choice, dict):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ModelResponseError("结构化模型响应缺少可解析内容") from error

        response_id = body.get("id")
        response_id = response_id if isinstance(response_id, str) else None
        finish_reason = choice.get("finish_reason")
        finish_reason = finish_reason if isinstance(finish_reason, str) else None
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
        message = choice.get("message")
        response_details = _model_response_diagnostics(
            response_id=response_id,
            finish_reason=finish_reason,
            max_tokens=request.max_output_tokens,
            thinking_mode=self._thinking_mode or "provider_default",
            usage=usage,
            message=message if isinstance(message, dict) else None,
        )
        if not isinstance(message, dict) or "content" not in message:
            raise ModelResponseError(
                "结构化模型响应缺少可解析内容",
                response_details,
            )
        content = message["content"]

        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        if not isinstance(content, str):
            raise ModelResponseError(
                "结构化模型 content 不是文本",
                {**response_details, "content_type": type(content).__name__},
            )

        content_details = {
            **response_details,
            "content_length": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
        try:
            output = self._decode_json_object(content)
        except ModelResponseError as error:
            raise ModelResponseError(
                str(error),
                {**error.details, **content_details},
            ) from error
        if not isinstance(output, dict):
            raise ModelResponseError(
                "结构化模型 JSON 顶层必须是对象",
                content_details,
            )

        return StructuredModelResponse(
            output=output,
            model=str(body.get("model") or self.model_name),
            provider=self.provider,
            response_id=response_id,
            finish_reason=finish_reason,
            request_duration_ms=round(
                (perf_counter() - request_started) * 1000,
                2,
            ),
            usage=usage,
            diagnostics=content_details,
        )

    @staticmethod
    def _is_retryable(error: ModelClientError) -> bool:
        if isinstance(error, (ModelTimeoutError, ModelUnavailableError)):
            return True
        if isinstance(error, ModelResponseError):
            status_code = error.details.get("status_code")
            return status_code == 429 or (
                isinstance(status_code, int) and status_code >= 500
            )
        return False

    @staticmethod
    def _decode_json_object(content: str) -> dict[str, Any]:
        normalized = content.strip()
        if normalized.startswith("```") and normalized.endswith("```"):
            lines = normalized.splitlines()
            normalized = "\n".join(lines[1:-1]).strip()
        try:
            output = json.loads(normalized)
        except json.JSONDecodeError:
            start = normalized.find("{")
            end = normalized.rfind("}")
            if start < 0 or end <= start:
                raise ModelResponseError("结构化模型没有返回合法 JSON") from None
            try:
                output = json.loads(normalized[start : end + 1])
            except json.JSONDecodeError as error:
                raise ModelResponseError("结构化模型没有返回合法 JSON") from error
        if not isinstance(output, dict):
            raise ModelResponseError("结构化模型 JSON 顶层必须是对象")
        return output


def _httpx_timeout_stage(error: httpx.TimeoutException) -> str:
    if isinstance(error, httpx.ConnectTimeout):
        return "connect"
    if isinstance(error, httpx.ReadTimeout):
        return "read"
    if isinstance(error, httpx.WriteTimeout):
        return "write"
    if isinstance(error, httpx.PoolTimeout):
        return "pool"
    return "unknown"


def _model_response_diagnostics(
    *,
    response_id: str | None,
    finish_reason: str | None,
    max_tokens: int | None,
    thinking_mode: str,
    usage: dict[str, Any] | None,
    message: dict[str, Any] | None,
) -> dict[str, Any]:
    usage = usage or {}
    completion_details = usage.get("completion_tokens_details")
    output_details = usage.get("output_tokens_details")
    reasoning_tokens = _first_token_count(
        usage.get("reasoning_tokens"),
        completion_details.get("reasoning_tokens")
        if isinstance(completion_details, dict)
        else None,
        output_details.get("reasoning_tokens")
        if isinstance(output_details, dict)
        else None,
    )
    reasoning_present = bool(
        isinstance(message, dict)
        and "reasoning_content" in message
        and message["reasoning_content"] is not None
    )
    reasoning_content = message.get("reasoning_content") if message else None
    return {
        "response_id": response_id,
        "finish_reason": finish_reason,
        "prompt_tokens": _first_token_count(usage.get("prompt_tokens")),
        "completion_tokens": _first_token_count(usage.get("completion_tokens")),
        "reasoning_tokens": reasoning_tokens,
        "reasoning_content_present": reasoning_present,
        "reasoning_content_length": _content_length(reasoning_content),
        "max_tokens": max_tokens,
        "thinking_mode": thinking_mode,
    }


def _first_token_count(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _content_length(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(
            len(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text", ""), str)
        )
    return 0


def create_structured_model_client(settings: Settings) -> StructuredModelClient:
    provider = settings.structured_model_provider.strip().lower()
    if provider == "fake":
        return DemoModelClient()
    if provider in {"openai", "openai_compatible"}:
        if not settings.llm_base_url:
            raise ModelClientError("STRUCTURED_MODEL_PROVIDER 需要配置 LLM_BASE_URL")
        hostname = urlparse(settings.llm_base_url).hostname or ""
        is_deepseek = hostname == "api.deepseek.com" or hostname.endswith(
            ".deepseek.com"
        )
        response_format = settings.llm_response_format.strip().lower()
        if response_format == "auto":
            response_format = (
                "json_object" if is_deepseek else "json_schema"
            )
        if response_format not in {"json_schema", "json_object"}:
            raise ModelClientError(
                "LLM_RESPONSE_FORMAT 只能是 json_schema、json_object 或 auto"
            )
        configured_thinking_mode = settings.llm_thinking_mode.strip().lower()
        if configured_thinking_mode == "auto":
            thinking_mode = "disabled" if is_deepseek else None
        elif configured_thinking_mode == "omit":
            thinking_mode = None
        elif configured_thinking_mode in {"enabled", "disabled"}:
            thinking_mode = configured_thinking_mode
        else:
            raise ModelClientError(
                "LLM_THINKING_MODE 只能是 auto、enabled、disabled 或 omit"
            )
        configured_reasoning_effort = settings.llm_reasoning_effort.strip().lower()
        if configured_reasoning_effort in {"auto", "omit"}:
            reasoning_effort = None
        else:
            if configured_reasoning_effort == "middle":
                configured_reasoning_effort = "medium"
            if configured_reasoning_effort not in {
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
            }:
                raise ModelClientError(
                    "LLM_REASONING_EFFORT 只能是 auto、none、minimal、low、"
                    "medium、high、xhigh 或 omit"
                )
            reasoning_effort = configured_reasoning_effort
        return OpenAICompatibleModelClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            response_format=response_format,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            retry_backoff_seconds=settings.llm_retry_backoff_seconds,
        )
    raise ModelClientError(f"不支持的结构化模型提供方: {provider}")

from __future__ import annotations

import asyncio
import copy
import json
import re
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict

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


class StructuredModelResponse(BaseModel):
    output: dict[str, Any]
    model: str
    provider: str
    response_id: str | None = None


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
    ) -> None:
        self.output = output
        self.error = error
        self._model = model
        self.last_request: StructuredModelRequest | None = None

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.last_request = request
        if self.error is not None:
            raise self.error
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
        elif request.schema_name == "core_job_fields":
            output = _demo_core_job_fields(request)
        elif request.schema_name == "detail_job_fields":
            output = _demo_detail_job_fields(request)
        elif request.schema_name == "requirement_match":
            output = _demo_requirement_match(request)
        elif request.schema_name == "resume_suggestion":
            output = _demo_resume_suggestion(request)
        else:
            output = {}
        return StructuredModelResponse(
            output=output,
            model=self.model_name,
            provider=self.provider,
        )


def _demo_job_description(request: StructuredModelRequest) -> dict[str, Any]:
    prompt = "\n".join(message.content for message in request.messages)
    match = re.search(
        r"<job_description>\s*(.*?)\s*</job_description>",
        prompt,
        re.DOTALL,
    )
    content = match.group(1).strip() if match else prompt
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
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._transport = transport

    @property
    def model_name(self) -> str:
        return self._model

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
            raise ModelTimeoutError("结构化模型请求超时") from error
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
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ModelResponseError("结构化模型响应缺少可解析内容") from error

        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        if not isinstance(content, str):
            raise ModelResponseError("结构化模型 content 不是文本")

        output = self._decode_json_object(content)
        if not isinstance(output, dict):
            raise ModelResponseError("结构化模型 JSON 顶层必须是对象")

        response_id = body.get("id")
        return StructuredModelResponse(
            output=output,
            model=str(body.get("model") or self.model_name),
            provider=self.provider,
            response_id=response_id if isinstance(response_id, str) else None,
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


def create_structured_model_client(settings: Settings) -> StructuredModelClient:
    provider = settings.structured_model_provider.strip().lower()
    if provider == "fake":
        return DemoModelClient()
    if provider in {"openai", "openai_compatible"}:
        if not settings.llm_base_url:
            raise ModelClientError("STRUCTURED_MODEL_PROVIDER 需要配置 LLM_BASE_URL")
        response_format = settings.llm_response_format.strip().lower()
        if response_format == "auto":
            hostname = urlparse(settings.llm_base_url).hostname or ""
            response_format = (
                "json_object"
                if hostname == "api.deepseek.com" or hostname.endswith(".deepseek.com")
                else "json_schema"
            )
        if response_format not in {"json_schema", "json_object"}:
            raise ModelClientError(
                "LLM_RESPONSE_FORMAT 只能是 json_schema、json_object 或 auto"
            )
        return OpenAICompatibleModelClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            response_format=response_format,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            retry_backoff_seconds=settings.llm_retry_backoff_seconds,
        )
    raise ModelClientError(f"不支持的结构化模型提供方: {provider}")

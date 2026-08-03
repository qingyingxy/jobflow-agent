from __future__ import annotations

import copy
import json
from typing import Any, Literal, Protocol

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


class OpenAICompatibleModelClient:
    """Small dependency-light client for OpenAI-compatible JSON-schema APIs."""

    provider = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = (
            base_url.rstrip("/")
            if base_url.rstrip("/").endswith("/chat/completions")
            else f"{base_url.rstrip('/')}/chat/completions"
        )
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        payload = {
            "model": self.model_name,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.json_schema,
                },
            },
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
                {"status_code": response.status_code},
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

        try:
            output = json.loads(content)
        except json.JSONDecodeError as error:
            raise ModelResponseError("结构化模型没有返回合法 JSON") from error
        if not isinstance(output, dict):
            raise ModelResponseError("结构化模型 JSON 顶层必须是对象")

        response_id = body.get("id")
        return StructuredModelResponse(
            output=output,
            model=str(body.get("model") or self.model_name),
            provider=self.provider,
            response_id=response_id if isinstance(response_id, str) else None,
        )


def create_structured_model_client(settings: Settings) -> StructuredModelClient:
    provider = settings.structured_model_provider.strip().lower()
    if provider == "fake":
        return FakeModelClient()
    if provider in {"openai", "openai_compatible"}:
        if not settings.llm_base_url:
            raise ModelClientError("STRUCTURED_MODEL_PROVIDER 需要配置 LLM_BASE_URL")
        return OpenAICompatibleModelClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise ModelClientError(f"不支持的结构化模型提供方: {provider}")

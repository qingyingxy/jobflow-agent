from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


class URLReaderError(RuntimeError):
    code = "url_read_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class URLSafetyError(URLReaderError):
    code = "unsafe_url"


class URLFetchError(URLReaderError):
    code = "url_fetch_failed"


class URLFetchTimeout(URLFetchError):
    code = "url_fetch_timeout"


class ResponseTooLargeError(URLFetchError):
    code = "response_too_large"


class ResponseDecodeError(URLFetchError):
    code = "response_decode_failed"


Resolver = Callable[[str, int], list[Any]]


def _default_resolver(host: str, port: int) -> list[Any]:
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


class URLSafetyChecker:
    """Validate outbound URLs before any network request is made."""

    def __init__(self, resolver: Resolver | None = None) -> None:
        self.resolver = resolver or _default_resolver

    async def validate(self, url: str) -> str:
        try:
            parsed = urlsplit(url.strip())
        except ValueError as error:
            raise URLSafetyError("URL 格式无效") from error

        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise URLSafetyError("只允许访问 HTTP 或 HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise URLSafetyError("URL 不能携带用户名或密码")
        if not parsed.hostname:
            raise URLSafetyError("URL 缺少主机名")

        try:
            port = parsed.port
        except ValueError as error:
            raise URLSafetyError("URL 端口无效") from error
        expected_port = 443 if scheme == "https" else 80
        if port is not None and port != expected_port:
            raise URLSafetyError("只允许访问 HTTP 默认端口或 HTTPS 默认端口")

        host = parsed.hostname.rstrip(".").lower()
        self._reject_host_name(host)
        resolved_ips = self._resolve(host, port or expected_port)
        if not resolved_ips:
            raise URLSafetyError("URL 主机无法解析")
        for resolved_ip in resolved_ips:
            try:
                address = ipaddress.ip_address(resolved_ip)
            except ValueError as error:
                raise URLSafetyError("URL 主机解析结果无效") from error
            if not address.is_global:
                raise URLSafetyError("出于安全原因，禁止访问内网或保留地址")

        normalized_netloc = host
        if port is not None:
            normalized_netloc = f"{host}:{port}"
        normalized_path = parsed.path or "/"
        return urlunsplit(
            (scheme, normalized_netloc, normalized_path, parsed.query, "")
        )

    def _reject_host_name(self, host: str) -> None:
        if host in {"localhost", "localhost.localdomain"}:
            raise URLSafetyError("禁止访问本机地址")
        if host.endswith((".local", ".localhost", ".internal")):
            raise URLSafetyError("禁止访问本地或内部域名")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return
        if not address.is_global:
            raise URLSafetyError("出于安全原因，禁止访问内网或保留地址")

    def _resolve(self, host: str, port: int) -> list[str]:
        try:
            records = self.resolver(host, port)
        except (OSError, socket.gaierror) as error:
            raise URLSafetyError("URL 主机解析失败") from error

        resolved: list[str] = []
        for record in records:
            if isinstance(record, str):
                resolved.append(record)
                continue
            if isinstance(record, tuple):
                address = record[-1]
                if isinstance(address, tuple) and address:
                    resolved.append(str(address[0]))
                elif isinstance(address, str):
                    resolved.append(address)
        return resolved


@dataclass(frozen=True)
class FetchedResponse:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str | None
    body: bytes


class SafeHTTPReader:
    """Small HTTP client with SSRF, redirect, size, and retry guardrails."""

    def __init__(
        self,
        *,
        safety_checker: URLSafetyChecker | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 12.0,
        max_bytes: int = 1_500_000,
        max_redirects: int = 3,
        max_retries: int = 1,
    ) -> None:
        self.safety_checker = safety_checker or URLSafetyChecker()
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.max_retries = max_retries

    async def fetch(self, url: str) -> FetchedResponse:
        requested_url = await self.safety_checker.validate(url)
        current_url = requested_url
        redirect_count = 0

        async with httpx.AsyncClient(
            transport=self.transport,
            follow_redirects=False,
            timeout=self.timeout_seconds,
        ) as client:
            while True:
                response = await self._request_with_retry(client, current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise URLFetchError("服务器重定向缺少 Location")
                    if redirect_count >= self.max_redirects:
                        raise URLFetchError("重定向次数超过安全限制")
                    current_url = await self.safety_checker.validate(
                        urljoin(current_url, location)
                    )
                    redirect_count += 1
                    continue

                body = await self._read_body(response)
                content_type = response.headers.get("content-type")
                return FetchedResponse(
                    requested_url=requested_url,
                    final_url=current_url,
                    status_code=response.status_code,
                    content_type=content_type,
                    body=body,
                )

    async def fetch_json(self, url: str) -> tuple[FetchedResponse, Any]:
        response = await self.fetch(url)
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResponseDecodeError("来源返回的内容不是有效 JSON") from error
        return response, payload

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(url)
            except httpx.TimeoutException as error:
                if attempt >= self.max_retries:
                    raise URLFetchTimeout("读取来源超时") from error
                continue
            except httpx.TransportError as error:
                if attempt >= self.max_retries:
                    raise URLFetchError("读取来源失败") from error
                continue

            if response.status_code >= 500:
                if attempt >= self.max_retries:
                    raise URLFetchError(
                        f"来源服务返回错误状态 {response.status_code}",
                        code="source_server_error",
                    )
                continue
            if response.status_code >= 400:
                raise URLFetchError(
                    f"来源拒绝请求，状态码为 {response.status_code}",
                    code="source_http_error",
                )
            return response
        raise URLFetchError("读取来源失败")

    async def _read_body(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    raise ResponseTooLargeError("来源内容超过大小限制")
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise ResponseTooLargeError("来源内容超过大小限制")
            chunks.append(chunk)
        return b"".join(chunks)


@dataclass(frozen=True)
class ParsedHTMLDocument:
    text: str
    title: str | None
    company: str | None
    locations: list[str]
    job_type: str | None
    published_at: datetime | None
    json_ld: list[dict[str, Any]]


class _HTMLTextParser(HTMLParser):
    _ignored_tags: ClassVar[set[str]] = {"script", "style", "noscript", "template"}
    _block_tags: ClassVar[set[str]] = {
        "address",
        "article",
        "br",
        "dd",
        "div",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "p",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self._tag_stack: list[str] = []
        self._hidden_flags: list[bool] = []
        self._ignored_depth = 0
        self._hidden_depth = 0
        self._title_depth = 0
        self._heading_depth = 0
        self._jsonld_buffer: list[str] | None = None
        self.jsonld: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        self._tag_stack.append(normalized_tag)

        if normalized_tag == "script" and attributes.get("type", "").lower() in {
            "application/ld+json",
            "application/json+ld",
        }:
            self._jsonld_buffer = []
            self._ignored_depth += 1
        elif normalized_tag in self._ignored_tags:
            self._ignored_depth += 1

        is_hidden = self._is_hidden(attributes)
        self._hidden_flags.append(is_hidden)
        if is_hidden:
            self._hidden_depth += 1
        if normalized_tag == "title":
            self._title_depth += 1
        if normalized_tag == "h1":
            self._heading_depth += 1
        if normalized_tag in self._block_tags and self._ignored_depth == 0:
            self.parts.append("\n")

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "script" and self._jsonld_buffer is not None:
            self._parse_jsonld("".join(self._jsonld_buffer))
            self._jsonld_buffer = None
            if self._ignored_depth > 0:
                self._ignored_depth -= 1
        elif normalized_tag in self._ignored_tags and self._ignored_depth > 0:
            self._ignored_depth -= 1
        if normalized_tag == "title" and self._title_depth > 0:
            self._title_depth -= 1
        if normalized_tag == "h1" and self._heading_depth > 0:
            self._heading_depth -= 1
        hidden_flag = self._hidden_flags.pop() if self._hidden_flags else False
        if hidden_flag and self._hidden_depth > 0:
            self._hidden_depth -= 1
        if normalized_tag in self._block_tags and self._ignored_depth == 0:
            self.parts.append("\n")
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._jsonld_buffer is not None:
            self._jsonld_buffer.append(data)
        if self._ignored_depth > 0 or self._hidden_depth > 0:
            return
        if self._title_depth > 0:
            self.title_parts.append(data)
        if self._heading_depth > 0:
            self.heading_parts.append(data)
        self.parts.append(data)

    def _is_hidden(self, attrs: dict[str, str]) -> bool:
        if "hidden" in attrs:
            return True
        if attrs.get("aria-hidden", "").lower() == "true":
            return True
        style = re.sub(r"\s+", "", attrs.get("style", "").lower())
        return "display:none" in style or "visibility:hidden" in style

    def _parse_jsonld(self, raw: str) -> None:
        try:
            payload = json.loads(raw.strip())
        except json.JSONDecodeError:
            return
        for item in _iter_jsonld_objects(payload):
            if isinstance(item, dict):
                self.jsonld.append(item)


def parse_html_document(raw_html: str) -> ParsedHTMLDocument:
    parser = _HTMLTextParser()
    parser.feed(raw_html)
    parser.close()

    job_data = _first_job_posting(parser.jsonld)
    description = _clean_html_text(str(job_data.get("description", "")))
    body_text = _clean_html_text(" ".join(parser.parts))
    text_parts = [item for item in [description, body_text] if item]
    text = "\n".join(dict.fromkeys(text_parts))

    title = _clean_value(job_data.get("title"))
    if title is None:
        title = _clean_value(" ".join(parser.heading_parts)) or _clean_value(
            " ".join(parser.title_parts)
        )

    organization = job_data.get("hiringOrganization")
    company = None
    if isinstance(organization, dict):
        company = _clean_value(organization.get("name"))
    elif isinstance(organization, str):
        company = _clean_value(organization)

    locations = _extract_locations(job_data.get("jobLocation"))
    published_at = _parse_datetime(job_data.get("datePosted"))
    job_type = _clean_value(job_data.get("employmentType"))
    return ParsedHTMLDocument(
        text=text,
        title=title,
        company=company,
        locations=locations,
        job_type=job_type,
        published_at=published_at,
        json_ld=parser.jsonld,
    )


def _iter_jsonld_objects(value: Any) -> list[Any]:
    if isinstance(value, list):
        items: list[Any] = []
        for child in value:
            items.extend(_iter_jsonld_objects(child))
        return items
    if isinstance(value, dict):
        items = [value]
        if isinstance(value.get("@graph"), list):
            items.extend(_iter_jsonld_objects(value["@graph"]))
        return items
    return []


def _first_job_posting(items: list[dict[str, Any]]) -> dict[str, Any]:
    for item in items:
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if any(str(value).casefold() == "jobposting" for value in types):
            return item
    return {}


def _extract_locations(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    locations: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            cleaned = _clean_value(item)
            if cleaned:
                locations.append(cleaned)
            continue
        address = item.get("address")
        if isinstance(address, dict):
            parts = [
                _clean_value(address.get(key))
                for key in ("streetAddress", "addressLocality", "addressRegion", "addressCountry")
            ]
            cleaned = ", ".join(part for part in parts if part)
        else:
            cleaned = _clean_value(address or item.get("name"))
        if cleaned and cleaned not in locations:
            locations.append(cleaned)
    return locations


def _parse_datetime(value: Any) -> datetime | None:
    cleaned = _clean_value(value)
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _clean_html_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", unescape(value))
    return re.sub(r"\s+", " ", without_tags).strip()


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", unescape(str(value))).strip()
    return cleaned or None

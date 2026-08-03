from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Protocol
from urllib.parse import urlsplit

from src.services.url_reader import (
    ParsedHTMLDocument,
    SafeHTTPReader,
    parse_html_document,
)


class SourceNotSupportedError(ValueError):
    code = "source_not_supported"


class SourcePayloadError(ValueError):
    code = "source_payload_invalid"


@dataclass(frozen=True)
class JobStub:
    source_id: str
    source_job_id: str
    company: str | None
    title: str | None
    locations: list[str]
    job_type: str | None
    published_at: datetime | None
    detail_url: str
    raw_content: str


class JobSourceAdapter(Protocol):
    source_id: str
    source_url: str

    async def list_jobs(self) -> list[JobStub]:
        ...

    async def fetch_job(self, source_job_id: str) -> JobStub:
        ...


class GreenhouseAdapter:
    """Adapter for Greenhouse's public, read-only Job Board API."""

    supported_hosts: ClassVar[set[str]] = {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
    }
    api_host: ClassVar[str] = "boards-api.greenhouse.io"

    def __init__(
        self,
        *,
        source_url: str,
        board_token: str,
        reader: SafeHTTPReader,
        company: str | None = None,
    ) -> None:
        self.source_url = source_url
        self.board_token = board_token
        self.reader = reader
        self.company_override = company.strip() if company else None
        self.source_id = f"greenhouse:{board_token}"

    @classmethod
    def from_board_url(
        cls,
        source_url: str,
        *,
        reader: SafeHTTPReader | None = None,
        company: str | None = None,
    ) -> GreenhouseAdapter:
        board_token = cls._board_token(source_url)
        return cls(
            source_url=source_url,
            board_token=board_token,
            reader=reader or SafeHTTPReader(),
            company=company,
        )

    @property
    def api_base_url(self) -> str:
        return f"https://{self.api_host}/v1/boards/{self.board_token}"

    async def list_jobs(self) -> list[JobStub]:
        _, payload = await self.reader.fetch_json(f"{self.api_base_url}/jobs?content=true")
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise SourcePayloadError("Greenhouse 返回中缺少 jobs 列表")

        jobs: list[JobStub] = []
        for item in payload["jobs"]:
            try:
                jobs.append(self._to_stub(item))
            except (KeyError, TypeError, ValueError) as error:
                raise SourcePayloadError("Greenhouse 岗位字段格式无效") from error
        return jobs

    async def fetch_job(self, source_job_id: str) -> JobStub:
        if not re.fullmatch(r"\d+", source_job_id):
            raise SourcePayloadError("Greenhouse 岗位 ID 无效")
        _, payload = await self.reader.fetch_json(
            f"{self.api_base_url}/jobs/{source_job_id}?content=true"
        )
        if not isinstance(payload, dict):
            raise SourcePayloadError("Greenhouse 岗位详情格式无效")
        return self._to_stub(payload)

    def _to_stub(self, item: dict[str, object]) -> JobStub:
        raw_id = item.get("id")
        if raw_id is None:
            raise SourcePayloadError("Greenhouse 岗位缺少 id")
        source_job_id = str(raw_id)
        title = _clean_text(item.get("title"))
        location = item.get("location")
        locations = _location_names(location)
        content = _clean_text(item.get("content")) or ""
        parsed = parse_html_document(content) if content else _empty_document()
        raw_content = parsed.text or _fallback_content(title, locations, item)
        if len(raw_content) < 20:
            raw_content = _fallback_content(title, locations, item)
        if len(raw_content) < 20:
            raise SourcePayloadError("Greenhouse 岗位正文过短")

        detail_url = _clean_text(item.get("absolute_url"))
        if not detail_url:
            detail_url = (
                f"https://boards.greenhouse.io/{self.board_token}/jobs/{source_job_id}"
            )
        parsed_locations = parsed.locations or locations
        company = self.company_override or parsed.company or _clean_text(
            item.get("company_name")
        )
        if company is None:
            company = self.board_token
        return JobStub(
            source_id=self.source_id,
            source_job_id=source_job_id,
            company=company,
            title=title or parsed.title,
            locations=_unique(parsed_locations),
            job_type=_job_type(parsed.job_type, title, raw_content),
            published_at=parsed.published_at or _parse_datetime(item.get("updated_at")),
            detail_url=detail_url,
            raw_content=raw_content,
        )

    @classmethod
    def _board_token(cls, source_url: str) -> str:
        try:
            parsed = urlsplit(source_url.strip())
        except ValueError as error:
            raise SourceNotSupportedError("Greenhouse 来源 URL 格式无效") from error
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() not in {"http", "https"} or host not in cls.supported_hosts:
            raise SourceNotSupportedError("当前只支持 Greenhouse 官方岗位入口")
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", segments[0]):
            raise SourceNotSupportedError(
                "Greenhouse URL 应为 https://boards.greenhouse.io/{board_token}"
            )
        return segments[0]


def _empty_document() -> ParsedHTMLDocument:
    return ParsedHTMLDocument(
        text="",
        title=None,
        company=None,
        locations=[],
        job_type=None,
        published_at=None,
        json_ld=[],
    )


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _location_names(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    locations: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = _clean_text(item.get("name"))
        else:
            name = _clean_text(item)
        if name and name not in locations:
            locations.append(name)
    return locations


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned.casefold() not in seen:
            result.append(cleaned)
            seen.add(cleaned.casefold())
    return result


def _job_type(parsed_type: str | None, title: str | None, content: str) -> str:
    text = " ".join(item for item in [parsed_type, title, content] if item).casefold()
    if any(keyword in text for keyword in ("intern", "实习")):
        return "internship"
    if any(keyword in text for keyword in ("campus", "校招", "应届")):
        return "campus"
    if any(keyword in text for keyword in ("part-time", "part time", "兼职")):
        return "part_time"
    if any(keyword in text for keyword in ("full-time", "full time", "全职")):
        return "full_time"
    return "unknown"


def _parse_datetime(value: object) -> datetime | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _fallback_content(
    title: str | None,
    locations: list[str],
    item: dict[str, object],
) -> str:
    company = _clean_text(item.get("company_name")) or "目标公司"
    location_text = "、".join(locations) or "地点待确认"
    title_text = title or "岗位待确认"
    return (
        f"{company}招聘{title_text}。工作地点：{location_text}。"
        "岗位详情请以来源页面为准。"
    )

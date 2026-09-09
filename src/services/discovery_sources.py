from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import ClassVar, Protocol
from urllib.parse import urlencode, urljoin, urlsplit

from src.domain.discovery import (
    DiscoveryPlanBudget,
    DiscoveryPlanRoute,
    DiscoverySearchPlan,
)
from src.services.company_registry import CompanySource
from src.services.url_reader import (
    HTMLLink,
    ParsedHTMLDocument,
    SafeHTTPReader,
    URLReaderError,
    extract_html_links,
    parse_html_document,
)


class SourceNotSupportedError(ValueError):
    code = "source_not_supported"


class SourcePayloadError(ValueError):
    code = "source_payload_invalid"


_NON_JOB_PATH_SEGMENTS = frozenset(
    {
        "about",
        "activity",
        "application",
        "benefits",
        "contact",
        "culture",
        "events",
        "faq",
        "faqs",
        "guide",
        "guideline",
        "help",
        "home",
        "index",
        "news",
        "privacy",
        "process",
        "procedure",
        "terms",
    }
)
_NON_JOB_TITLE_PHRASES = (
    "关于我们",
    "人才理念",
    "企业文化",
    "员工故事",
    "成长体验",
    "校园活动",
    "招聘指南",
    "应聘指南",
    "投递指南",
    "招聘流程",
    "应聘流程",
    "投递流程",
    "常见问题",
    "联系我们",
    "我的投递",
    "职位列表",
    "岗位列表",
    "搜索职位",
)


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


@dataclass(frozen=True)
class DiscoveryAgentTraceStep:
    """One bounded tool decision made while discovering official jobs."""

    phase: str
    tool: str
    outcome: str
    observation: str
    decision: str
    source_id: str | None = None
    company: str | None = None
    url: str | None = None
    occurred_at: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "tool": self.tool,
            "outcome": self.outcome,
            "observation": self.observation,
            "decision": self.decision,
            "source_id": self.source_id,
            "company": self.company,
            "url": self.url,
            "occurred_at": self.occurred_at,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "details": self.details,
        }


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

    def build_search_plan(
        self,
        *,
        query: str | None,
        max_results: int,
    ) -> DiscoverySearchPlan:
        return DiscoverySearchPlan(
            query=query,
            allowed_source_ids=[self.source_id],
            routes=[
                DiscoveryPlanRoute(
                    source_id=self.source_id,
                    company=self.company_override,
                    source_url=self.source_url,
                    tool_sequence=["greenhouse_public_job_api"],
                )
            ],
            budget=DiscoveryPlanBudget(
                max_results=min(max_results, 20),
                max_analysis=0,
                max_concurrency=1,
                request_timeout_seconds=_reader_timeout(self.reader),
            ),
            stop_conditions=[
                "max_results_reached",
                "source_route_exhausted",
            ],
        )

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


class ByteDanceAdapter:
    """Adapter for ByteDance's public supplier job-search API."""

    source_id = "bytedance:public-supplier"
    source_url = "https://joinbytedance.com/search"
    api_base_url = "https://jobs.bytedance.com/api/v1/public/supplier"
    search_url = f"{api_base_url}/search/job/posts"
    filter_url = f"{api_base_url}/config/job/filters"
    request_headers: ClassVar[dict[str, str]] = {
        "accept-language": "zh-CN",
        "website-path": "en",
        "x-tt-env": "boe_epam_api",
        "origin": "https://joinbytedance.com",
    }

    def __init__(
        self,
        *,
        query: str,
        reader: SafeHTTPReader | None = None,
        max_jobs: int = 20,
        company: str = "字节跳动",
    ) -> None:
        self.query = query.strip()
        self.reader = reader or SafeHTTPReader(timeout_seconds=8, max_retries=0)
        self.max_jobs = max(1, min(max_jobs, 20))
        self.company = company
        self.search_terms = _bytedance_search_terms(self.query)[:3]
        self.used_location_fallback = False
        self.location_codes: list[str] = []
        self.warnings: list[str] = []

    async def list_jobs(self) -> list[JobStub]:
        self.used_location_fallback = False
        self.warnings = []
        self.location_codes = await self._requested_location_codes()
        jobs = await self._search(location_codes=self.location_codes)
        if not jobs and self.location_codes:
            self.used_location_fallback = True
            jobs = await self._search(location_codes=[])
        return _rank_official_jobs(jobs, query=self.query)[: self.max_jobs]

    async def fetch_job(self, source_job_id: str) -> JobStub:
        if not re.fullmatch(r"\d+", source_job_id):
            raise SourcePayloadError("字节岗位 ID 无效")
        _, payload = await self.reader.fetch_json(
            f"https://jobs.bytedance.com/api/v1/job/posts/{source_job_id}"
            "?portal_type=3"
        )
        if not isinstance(payload, dict):
            raise SourcePayloadError("字节岗位详情格式无效")
        data = payload.get("data")
        item = data.get("job_post_detail") if isinstance(data, dict) else None
        if not isinstance(item, dict):
            raise SourcePayloadError("字节岗位详情缺少 job_post_detail")
        return self._to_stub(item)

    async def _search(self, *, location_codes: list[str]) -> list[JobStub]:
        jobs: list[JobStub] = []
        for term in self.search_terms:
            _, payload = await self.reader.post_json(
                self.search_url,
                {
                    "limit": 10,
                    "offset": 0,
                    "keyword": term,
                    "job_category_id_list": [],
                    "recruitment_id_list": [],
                    "subject_id_list": [],
                    "location_code_list": location_codes,
                    "tag_id_list": [],
                },
                headers=self.request_headers,
            )
            jobs.extend(self._payload_jobs(payload))
        return _dedupe_stubs(jobs)

    async def _requested_location_codes(self) -> list[str]:
        try:
            _, payload = await self.reader.post_json(
                self.filter_url,
                {},
                headers=self.request_headers,
            )
        except URLReaderError as error:
            self.warnings.append(f"字节地点筛选读取失败：{str(error)[:180]}")
            return []
        return _matching_location_codes(payload, query=self.query)

    def _payload_jobs(self, payload: object) -> list[JobStub]:
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise SourcePayloadError("字节岗位搜索返回失败")
        data = payload.get("data")
        items = data.get("job_post_list") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourcePayloadError("字节岗位搜索缺少 job_post_list")
        jobs: list[JobStub] = []
        for item in items:
            if not isinstance(item, dict):
                raise SourcePayloadError("字节岗位记录格式无效")
            if _bytedance_item_matches_role(item, query=self.query):
                jobs.append(self._to_stub(item))
        return jobs

    def _to_stub(self, item: dict[str, object]) -> JobStub:
        source_job_id = _clean_text(item.get("id"))
        title = _clean_text(item.get("title"))
        if not source_job_id or not re.fullmatch(r"\d+", source_job_id):
            raise SourcePayloadError("字节岗位缺少有效 ID")
        if not title:
            raise SourcePayloadError("字节岗位缺少标题")

        description = _clean_text(item.get("description")) or ""
        requirement = _clean_text(item.get("requirement")) or ""
        raw_content = "\n\n".join(
            part
            for part in (
                f"岗位名称：{title}",
                f"岗位职责：\n{description}" if description else "",
                f"任职要求：\n{requirement}" if requirement else "",
            )
            if part
        )
        if len(raw_content) < 20:
            raise SourcePayloadError("字节岗位正文过短")

        locations = _location_names(item.get("city_list"))
        if not locations:
            locations = _location_names(item.get("city_info"))
        recruit_type = item.get("recruit_type")
        recruit_id = (
            _clean_text(recruit_type.get("id"))
            if isinstance(recruit_type, dict)
            else None
        )
        recruit_name = (
            _clean_text(recruit_type.get("i18n_name"))
            or _clean_text(recruit_type.get("en_name"))
            or _clean_text(recruit_type.get("name"))
            if isinstance(recruit_type, dict)
            else None
        )
        if recruit_id in {"202", "301"}:
            job_type = "internship"
        elif recruit_id == "201":
            job_type = "campus"
        elif recruit_id == "101":
            job_type = "full_time"
        else:
            job_type = _job_type(recruit_name, title, raw_content)
        job_type_fact = {
            "campus": "校园招聘",
            "internship": "实习",
            "full_time": "全职",
            "part_time": "兼职",
        }.get(job_type, recruit_name or "待确认")
        raw_content = "\n".join(
            (
                f"公司名称：{self.company}",
                f"官方职位 ID：{source_job_id}",
                f"工作地点：{'、'.join(locations) if locations else '待确认'}",
                f"招聘类型：{job_type_fact}",
                "",
                raw_content,
            )
        )
        return JobStub(
            source_id=self.source_id,
            source_job_id=source_job_id,
            company=self.company,
            title=title,
            locations=locations,
            job_type=job_type,
            published_at=_parse_datetime(item.get("publish_time")),
            detail_url=f"https://joinbytedance.com/search/{source_job_id}",
            raw_content=raw_content,
        )


class TencentAdapter:
    """Adapter for Tencent Careers' public, read-only position API."""

    source_id = "tencent:public-careers"
    source_url = "https://careers.tencent.com/search.html"
    api_base_url = "https://careers.tencent.com/tencentcareer/api/post"
    search_url = f"{api_base_url}/Query"
    detail_url = f"{api_base_url}/ByPostId"

    def __init__(
        self,
        *,
        query: str,
        reader: SafeHTTPReader | None = None,
        max_jobs: int = 20,
        company: str = "腾讯",
    ) -> None:
        self.query = query.strip()
        self.reader = reader or SafeHTTPReader(timeout_seconds=8, max_retries=0)
        self.max_jobs = max(1, min(max_jobs, 20))
        self.company = company
        self.search_terms = _bytedance_search_terms(self.query)[:3]
        self.recruitment_type_ids = _tencent_recruitment_type_ids(self.query)
        self.warnings: list[str] = []

    async def list_jobs(self) -> list[JobStub]:
        self.warnings = []
        candidates: list[JobStub] = []
        for recruitment_type_id in self.recruitment_type_ids:
            for term in self.search_terms:
                _, payload = await self.reader.fetch_json(
                    self._query_url(term, recruitment_type_id)
                )
                candidates.extend(
                    self._payload_jobs(
                        payload,
                        job_type=_tencent_job_type(recruitment_type_id),
                    )
                )

        ranked = _rank_official_jobs(
            _dedupe_stubs(candidates),
            query=self.query,
        )[: self.max_jobs]
        return list(await asyncio.gather(*(self._hydrate(job) for job in ranked)))

    async def fetch_job(self, source_job_id: str) -> JobStub:
        if not re.fullmatch(r"\d+", source_job_id):
            raise SourcePayloadError("腾讯岗位 ID 无效")
        _, payload = await self.reader.fetch_json(self._detail_url(source_job_id))
        item = self._payload_data(payload)
        return self._to_stub(item, job_type=None)

    async def _hydrate(self, job: JobStub) -> JobStub:
        try:
            _, payload = await self.reader.fetch_json(
                self._detail_url(job.source_job_id)
            )
            item = self._payload_data(payload)
            return self._to_stub(item, job_type=job.job_type)
        except (URLReaderError, SourcePayloadError) as error:
            self.warnings.append(
                f"腾讯岗位 {job.source_job_id} 详情读取失败：{str(error)[:180]}"
            )
            return job

    def _query_url(self, term: str, recruitment_type_id: int) -> str:
        query = urlencode(
            {
                "timestamp": "0",
                "countryId": "",
                "cityId": "",
                "bgIds": "",
                "productId": "",
                "categoryId": "",
                "parentCategoryId": "",
                "attrId": str(recruitment_type_id),
                "keyword": term,
                "pageIndex": "1",
                "pageSize": str(min(self.max_jobs, 20)),
                "language": "zh-cn",
                "area": "cn",
            }
        )
        return f"{self.search_url}?{query}"

    def _detail_url(self, source_job_id: str) -> str:
        query = urlencode(
            {
                "timestamp": "0",
                "postId": source_job_id,
                "language": "zh-cn",
            }
        )
        return f"{self.detail_url}?{query}"

    def _payload_jobs(self, payload: object, *, job_type: str) -> list[JobStub]:
        data = self._payload_data(payload)
        items = data.get("Posts")
        if not isinstance(items, list):
            raise SourcePayloadError("腾讯岗位搜索缺少 Posts")
        jobs: list[JobStub] = []
        for item in items:
            if not isinstance(item, dict):
                raise SourcePayloadError("腾讯岗位记录格式无效")
            jobs.append(self._to_stub(item, job_type=job_type))
        return jobs

    @staticmethod
    def _payload_data(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or payload.get("Code") != 200:
            raise SourcePayloadError("腾讯岗位接口返回失败")
        data = payload.get("Data")
        if not isinstance(data, dict):
            raise SourcePayloadError("腾讯岗位接口缺少 Data")
        return data

    def _to_stub(
        self,
        item: dict[str, object],
        *,
        job_type: str | None,
    ) -> JobStub:
        source_job_id = _clean_text(item.get("PostId"))
        title = _clean_text(item.get("RecruitPostName"))
        if not source_job_id or not re.fullmatch(r"\d+", source_job_id):
            raise SourcePayloadError("腾讯岗位缺少有效 ID")
        if not title:
            raise SourcePayloadError("腾讯岗位缺少标题")

        responsibility = _clean_text(item.get("Responsibility")) or ""
        requirement = _clean_text(item.get("Requirement")) or ""
        preferred = _clean_text(item.get("ImportantItem")) or ""
        work_years = _clean_text(item.get("RequireWorkYearsName")) or ""
        locations = _tencent_locations(item.get("LocationName"))
        resolved_job_type = job_type or _job_type(None, title, responsibility)
        job_type_fact = {
            "campus": "校园招聘",
            "internship": "实习",
            "full_time": "社会招聘",
        }.get(resolved_job_type, "待确认")
        raw_content = "\n".join(
            part
            for part in (
                f"公司名称：{self.company}",
                f"官方职位 ID：{source_job_id}",
                f"岗位名称：{title}",
                f"工作地点：{'、'.join(locations) if locations else '待确认'}",
                f"招聘类型：{job_type_fact}",
                f"工作经验：{work_years}" if work_years else "",
                "",
                f"岗位职责：\n{responsibility}" if responsibility else "",
                f"任职要求：\n{requirement}" if requirement else "",
                f"加分项：\n{preferred}" if preferred else "",
            )
            if part
        )
        if len(raw_content) < 20:
            raise SourcePayloadError("腾讯岗位正文过短")
        return JobStub(
            source_id=self.source_id,
            source_job_id=source_job_id,
            company=self.company,
            title=title,
            locations=locations,
            job_type=resolved_job_type,
            published_at=_parse_tencent_date(item.get("LastUpdateTime")),
            detail_url=(
                "https://careers.tencent.com/jobdesc.html?"
                f"postId={source_job_id}"
            ),
            raw_content=raw_content,
        )


class OfficialCompanyRegistryAdapter:
    """Discover public job detail pages from the registered company websites.

    The adapter deliberately stays shallow: it reads an official entry page,
    follows a small number of visible job-like links, and never submits forms
    or executes page JavaScript. This keeps a search run explainable and
    bounded while still supporting both JSON-LD job pages and ordinary HTML.
    """

    source_id = "official-registry:ai-campus-40"
    source_url = "registry://ai-campus-target-companies-40"
    auto_analyze_top = True

    def __init__(
        self,
        *,
        sources: list[CompanySource],
        query: str,
        reader: SafeHTTPReader | None = None,
        max_jobs: int = 20,
        max_detail_links_per_source: int = 4,
        max_concurrency: int = 6,
    ) -> None:
        self.sources = sources
        self.query = query.strip()
        self.reader = reader or SafeHTTPReader(timeout_seconds=8, max_retries=0)
        self.max_jobs = max(1, min(max_jobs, 20))
        self.max_detail_links_per_source = max(1, max_detail_links_per_source)
        self.max_concurrency = max(1, max_concurrency)
        self.failures: list[str] = []
        self.trace_steps: list[DiscoveryAgentTraceStep] = []
        self._source_steps: dict[str, list[DiscoveryAgentTraceStep]] = {}

    def build_search_plan(
        self,
        *,
        query: str | None,
        max_results: int,
    ) -> DiscoverySearchPlan:
        sources = [source for source in self.sources if source.enabled]
        return DiscoverySearchPlan(
            query=query,
            allowed_source_ids=[source.id for source in sources],
            routes=[
                DiscoveryPlanRoute(
                    source_id=source.id,
                    company=source.company,
                    source_url=source.career_url,
                    tool_sequence=self._tool_sequence(source),
                )
                for source in sources
            ],
            budget=DiscoveryPlanBudget(
                max_results=min(max_results, self.max_jobs),
                max_analysis=5,
                max_detail_links_per_source=self.max_detail_links_per_source,
                max_concurrency=self.max_concurrency,
                request_timeout_seconds=_reader_timeout(self.reader),
            ),
            stop_conditions=[
                "max_results_reached",
                "source_route_exhausted",
                "no_verified_jobs_requires_human_input",
            ],
        )

    @staticmethod
    def _tool_sequence(source: CompanySource) -> list[str]:
        static_tools = [
            "json_ld_job_parser",
            "static_job_page_validator",
            "visible_job_link_reader",
        ]
        if source.id == "bytedance":
            return ["bytedance_public_job_adapter", *static_tools]
        if source.id == "tencent":
            return ["tencent_public_job_adapter", *static_tools]
        return static_tools

    async def list_jobs(self) -> list[JobStub]:
        self.failures = []
        self.trace_steps = []
        self._source_steps = {}
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def collect(source: CompanySource) -> list[JobStub] | Exception:
            async with semaphore:
                occurred_at = datetime.now(UTC).isoformat()
                started = perf_counter()
                try:
                    return await self._list_source(source)
                except Exception as error:  # noqa: BLE001 - isolate source failures
                    self._set_source_step(
                        source,
                        phase="observe",
                        tool="safe_http_reader",
                        outcome="failed",
                        observation=str(error)[:240],
                        decision="停止当前来源，继续检查其他官方来源。",
                        error_code=_error_code(error),
                        occurred_at=occurred_at,
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    )
                    return error

        results = await asyncio.gather(
            *(collect(source) for source in self.sources if source.enabled),
        )
        candidates: list[JobStub] = []
        source_list = [source for source in self.sources if source.enabled]
        for source, result in zip(source_list, results, strict=True):
            if isinstance(result, Exception):
                self.failures.append(
                    f"{source.company}（{source.career_url}）：{str(result)[:240]}"
                )
                continue
            candidates.extend(result)

        self.trace_steps = [
            step
            for source in source_list
            for step in self._source_steps.get(source.id, [])
        ]
        return _rank_official_jobs(candidates, query=self.query)[: self.max_jobs]

    async def fetch_job(self, source_job_id: str) -> JobStub:
        raise SourcePayloadError(
            f"官网聚合来源不支持按内部 ID 单独读取岗位：{source_job_id}"
        )

    def _set_source_step(
        self,
        source: CompanySource,
        *,
        phase: str,
        tool: str,
        outcome: str,
        observation: str,
        decision: str,
        url: str | None = None,
        occurred_at: str | None = None,
        duration_ms: int | None = None,
        error_code: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        step = DiscoveryAgentTraceStep(
            phase=phase,
            tool=tool,
            outcome=outcome,
            observation=observation,
            decision=decision,
            source_id=source.id,
            company=source.company,
            url=url or source.career_url,
            occurred_at=occurred_at or datetime.now(UTC).isoformat(),
            duration_ms=duration_ms,
            error_code=error_code,
            details=details or {},
        )
        self._source_steps.setdefault(source.id, []).append(step)

    async def _list_source(self, source: CompanySource) -> list[JobStub]:
        if source.id == "bytedance":
            adapter = ByteDanceAdapter(
                query=self.query,
                reader=self.reader,
                max_jobs=self.max_jobs,
                company=source.company,
            )
            occurred_at = datetime.now(UTC).isoformat()
            started = perf_counter()
            try:
                jobs = await adapter.list_jobs()
            except (URLReaderError, SourcePayloadError) as error:
                self.failures.append(
                    f"{source.company} 专用 Adapter：{str(error)[:180]}；回退静态读取"
                )
                self._set_source_step(
                    source,
                    phase="fallback",
                    tool="bytedance_public_job_adapter",
                    outcome="failed",
                    observation=str(error)[:240],
                    decision="专用 Adapter 失败，按计划回退受控静态页面验证。",
                    url=ByteDanceAdapter.search_url,
                    occurred_at=occurred_at,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    error_code=_error_code(error),
                    details={"output_count": 0},
                )
            else:
                self.failures.extend(adapter.warnings)
                if jobs:
                    location_note = (
                        "；目标地点无结果后已放宽地点"
                        if adapter.used_location_fallback
                        else ""
                    )
                    self._set_source_step(
                        source,
                        phase="act",
                        tool="bytedance_public_job_adapter",
                        outcome="succeeded",
                        observation=(
                            f"使用 {len(adapter.search_terms)} 个关键词探针，"
                            f"验证出 {len(jobs)} 条带官方 ID 的岗位{location_note}。"
                        ),
                        decision="保留真实地点与正文，进入统一排序、去重和分析。",
                        url=ByteDanceAdapter.search_url,
                        occurred_at=occurred_at,
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                        details={
                            "output_count": len(jobs),
                            "keyword_probe_count": len(adapter.search_terms),
                            "used_location_fallback": adapter.used_location_fallback,
                        },
                    )
                    return jobs
                self.failures.append(
                    f"{source.company} 专用 Adapter：官方接口未返回匹配岗位；回退静态读取"
                )
                self._set_source_step(
                    source,
                    phase="fallback",
                    tool="bytedance_public_job_adapter",
                    outcome="empty",
                    observation="官方接口未返回可验证的匹配岗位。",
                    decision="按计划回退受控静态页面验证。",
                    url=ByteDanceAdapter.search_url,
                    occurred_at=occurred_at,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    details={
                        "output_count": 0,
                        "keyword_probe_count": len(adapter.search_terms),
                    },
                )
        elif source.id == "tencent":
            adapter = TencentAdapter(
                query=self.query,
                reader=self.reader,
                max_jobs=self.max_jobs,
                company=source.company,
            )
            occurred_at = datetime.now(UTC).isoformat()
            started = perf_counter()
            try:
                jobs = await adapter.list_jobs()
            except (URLReaderError, SourcePayloadError) as error:
                self.failures.append(
                    f"{source.company} 专用 Adapter：{str(error)[:180]}；回退静态读取"
                )
                self._set_source_step(
                    source,
                    phase="fallback",
                    tool="tencent_public_job_adapter",
                    outcome="failed",
                    observation=str(error)[:240],
                    decision="专用 Adapter 失败，按计划回退受控静态页面验证。",
                    url=TencentAdapter.search_url,
                    occurred_at=occurred_at,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    error_code=_error_code(error),
                    details={"output_count": 0},
                )
            else:
                self.failures.extend(adapter.warnings)
                if jobs:
                    self._set_source_step(
                        source,
                        phase="act",
                        tool="tencent_public_job_adapter",
                        outcome="succeeded",
                        observation=(
                            f"使用 {len(adapter.search_terms)} 个关键词探针和"
                            f" {len(adapter.recruitment_type_ids)} 类招聘入口，"
                            f"验证出 {len(jobs)} 条带官方 ID 的岗位。"
                        ),
                        decision="保留真实岗位字段，进入统一分层、去重和分析门控。",
                        url=TencentAdapter.search_url,
                        occurred_at=occurred_at,
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                        details={
                            "output_count": len(jobs),
                            "keyword_probe_count": len(adapter.search_terms),
                            "recruitment_type_count": len(
                                adapter.recruitment_type_ids
                            ),
                        },
                    )
                    return jobs
                self.failures.append(
                    f"{source.company} 专用 Adapter：官方接口未返回匹配岗位；回退静态读取"
                )
                self._set_source_step(
                    source,
                    phase="fallback",
                    tool="tencent_public_job_adapter",
                    outcome="empty",
                    observation="官方接口未返回可验证的匹配岗位。",
                    decision="按计划回退受控静态页面验证。",
                    url=TencentAdapter.search_url,
                    occurred_at=occurred_at,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    details={
                        "output_count": 0,
                        "keyword_probe_count": len(adapter.search_terms),
                    },
                )
        return await self._list_static_source(source)

    async def _list_static_source(self, source: CompanySource) -> list[JobStub]:
        occurred_at = datetime.now(UTC).isoformat()
        started = perf_counter()
        response = await self.reader.fetch(source.career_url)
        html = response.body.decode("utf-8", errors="replace")
        document = parse_html_document(html)
        jobs = self._jsonld_jobs(source, response.final_url, document)
        successful_tools: list[str] = []
        if jobs:
            successful_tools.append("json_ld_job_parser")

        if not jobs and _looks_like_job_page(
            document,
            url=response.final_url,
            link_text="",
        ):
            jobs.append(self._to_stub(source, response.final_url, document))
            successful_tools.append("static_job_page_validator")

        links = _rank_job_links(extract_html_links(html, base_url=response.final_url))
        followed_links = links[: self.max_detail_links_per_source]
        for link in followed_links:
            try:
                detail_response = await self.reader.fetch(link.url)
            except URLReaderError as error:
                self.failures.append(
                    f"{source.company} 子页面（{link.url}）：{str(error)[:180]}"
                )
                continue
            detail_html = detail_response.body.decode("utf-8", errors="replace")
            detail_document = parse_html_document(detail_html)
            jsonld_jobs = self._jsonld_jobs(
                source,
                detail_response.final_url,
                detail_document,
            )
            if jsonld_jobs:
                jobs.extend(jsonld_jobs)
                successful_tools.append("json_ld_job_parser")
            elif _looks_like_job_page(
                detail_document,
                url=detail_response.final_url,
                link_text=link.text,
            ):
                jobs.append(
                    self._to_stub(
                        source,
                        detail_response.final_url,
                        detail_document,
                        link_text=link.text,
                    )
                )
                successful_tools.append("visible_job_link_reader")

        jobs = _dedupe_stubs(jobs)
        if jobs:
            tools = " + ".join(dict.fromkeys(successful_tools))
            self._set_source_step(
                source,
                phase="act",
                tool=tools or "candidate_page_validator",
                outcome="succeeded",
                observation=(
                    f"验证出 {len(jobs)} 条具体岗位；检查了 "
                    f"{len(followed_links)} 个可见岗位链接。"
                ),
                decision="进入标准化、去重和相关性排序。",
                url=response.final_url,
                occurred_at=occurred_at,
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
                details={
                    "output_count": len(jobs),
                    "checked_link_count": len(followed_links),
                },
            )
        elif _looks_like_dynamic_shell(html):
            self.failures.append(
                f"{source.company}（{source.career_url}）："
                "页面依赖 JavaScript，静态读取未发现具体岗位；需要专用 Adapter"
            )
            self._set_source_step(
                source,
                phase="fallback",
                tool="json_ld_job_parser → static_job_page_validator → visible_job_link_reader",
                outcome=(
                    "route_exhausted"
                    if source.id in {"bytedance", "tencent"}
                    else "needs_adapter"
                ),
                observation=(
                    f"入口最终到达 {response.final_url}；未发现 JobPosting，"
                    "页面依赖 JavaScript。"
                ),
                decision=(
                    "不创建候选岗位；当前工具路线已耗尽，由用户粘贴 JD。"
                    if source.id in {"bytedance", "tencent"}
                    else "不创建候选岗位；等待专用 Adapter 或由用户粘贴 JD。"
                ),
                url=response.final_url,
                occurred_at=occurred_at,
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
                details={
                    "output_count": 0,
                    "checked_link_count": len(followed_links),
                },
            )
        else:
            self._set_source_step(
                source,
                phase="stop",
                tool="structured_data → static_html",
                outcome="empty",
                observation=(
                    f"未验证出具体岗位；检查了 {len(followed_links)} 个可见岗位链接。"
                ),
                decision="停止当前来源，避免把招聘说明页或首页当作岗位。",
                url=response.final_url,
                occurred_at=occurred_at,
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
                details={
                    "output_count": 0,
                    "checked_link_count": len(followed_links),
                },
            )
        return jobs

    def _jsonld_jobs(
        self,
        source: CompanySource,
        page_url: str,
        document: ParsedHTMLDocument,
    ) -> list[JobStub]:
        jobs: list[JobStub] = []
        for item in _job_posting_objects(document.json_ld):
            description = _clean_html_text(str(item.get("description", "")))
            raw_content = description or document.text
            if len(raw_content) < 20:
                continue
            title = _clean_text(item.get("title")) or document.title
            item_url = urljoin(
                page_url,
                _clean_text(item.get("url")) or page_url,
            )
            locations = _jsonld_locations(item.get("jobLocation")) or document.locations
            company = _jsonld_company(item.get("hiringOrganization"))
            jobs.append(
                self._to_stub(
                    source,
                    item_url,
                    document,
                    title=title,
                    company=company,
                    locations=locations,
                    raw_content=raw_content,
                    published_at=_parse_datetime(item.get("datePosted"))
                    or document.published_at,
                    job_type=_clean_text(item.get("employmentType")),
                )
            )
        return jobs

    def _to_stub(
        self,
        source: CompanySource,
        detail_url: str,
        document: ParsedHTMLDocument,
        *,
        link_text: str = "",
        title: str | None = None,
        company: str | None = None,
        locations: list[str] | None = None,
        raw_content: str | None = None,
        published_at: datetime | None = None,
        job_type: str | None = None,
    ) -> JobStub:
        cleaned_url = _clean_text(detail_url) or source.career_url
        cleaned_title = _clean_text(title) or document.title or _clean_text(link_text)
        content = _clean_text(raw_content) or document.text
        if len(content) < 20:
            raise SourcePayloadError("官网岗位正文过短")
        stable_key = "|".join(
            [source.id, cleaned_url, cleaned_title or "", content[:120]]
        )
        source_job_id = f"page-{hashlib.sha256(stable_key.encode()).hexdigest()[:24]}"
        return JobStub(
            source_id=f"official:{source.id}",
            source_job_id=source_job_id,
            company=company or document.company or source.company,
            title=cleaned_title,
            locations=_unique(locations or document.locations),
            job_type=_job_type(job_type or document.job_type, cleaned_title, content),
            published_at=published_at or document.published_at,
            detail_url=cleaned_url,
            raw_content=content,
        )


def _job_posting_objects(items: list[dict[str, object]]) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    for item in items:
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if any(str(value).casefold() == "jobposting" for value in types):
            jobs.append(item)
    return jobs


def _jsonld_company(value: object) -> str | None:
    if isinstance(value, dict):
        return _clean_text(value.get("name"))
    return _clean_text(value)


def _jsonld_locations(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    locations: list[str] = []
    for item in values:
        if isinstance(item, dict):
            address = item.get("address")
            if isinstance(address, dict):
                text = ", ".join(
                    part
                    for part in (
                        _clean_text(address.get("addressLocality")),
                        _clean_text(address.get("addressRegion")),
                        _clean_text(address.get("addressCountry")),
                    )
                    if part
                )
            else:
                text = _clean_text(address or item.get("name"))
        else:
            text = _clean_text(item)
        if text and text not in locations:
            locations.append(text)
    return locations


def _rank_job_links(links: list[HTMLLink]) -> list[HTMLLink]:
    def score(link: HTMLLink) -> tuple[int, int]:
        value = f"{link.url} {link.text}".casefold()
        positive = sum(
            1
            for keyword in (
                "job",
                "jobs",
                "position",
                "招聘",
                "岗位",
                "职位",
                "应届",
                "实习",
                "post/",
                "detail",
            )
            if keyword in value
        )
        negative = sum(
            1
            for keyword in (
                "login",
                "privacy",
                "terms",
                "contact",
                "about",
                "news",
                "guide",
                "guideline",
                "faq",
                "process",
                "application",
            )
            if keyword in value
        )
        return positive - negative, len(link.text)

    candidates = [
        link
        for link in links
        if not _is_non_job_page(url=link.url, title=link.text)
        and score(link)[0] > 0
    ]
    return sorted(candidates, key=score, reverse=True)


def _looks_like_job_page(
    document: ParsedHTMLDocument,
    *,
    url: str,
    link_text: str,
) -> bool:
    if _is_non_job_page(
        url=url,
        title=f"{link_text} {document.title or ''}",
    ):
        return False
    if _job_posting_objects(document.json_ld):
        return True
    if len(document.text) < 80:
        return False
    signal_text = f"{url} {link_text} {document.title or ''}".casefold()
    specific_page_signal = any(
        keyword in signal_text
        for keyword in (
            "job",
            "position",
            "post/",
            "detail",
            "岗位",
            "职位",
            "实习",
        )
    )
    content_signal_count = sum(
        1
        for keyword in (
            "岗位职责",
            "任职要求",
            "工作职责",
            "职位描述",
            "qualification",
            "responsibilities",
            "requirements",
            "技能要求",
            "岗位要求",
        )
        if keyword.casefold() in document.text.casefold()
    )
    generic_title = (document.title or "").casefold() in {
        "首页",
        "home",
        "校园招聘",
        "招聘首页",
        "careers",
        "career",
        "职位列表",
        "岗位列表",
        "搜索职位",
    }
    return (
        specific_page_signal and content_signal_count >= 1
        or content_signal_count >= 2
    ) and not generic_title


def looks_like_job_page(
    document: ParsedHTMLDocument,
    *,
    url: str,
    link_text: str = "",
) -> bool:
    """Public verification boundary shared by discovery and submitted leads."""

    return _looks_like_job_page(document, url=url, link_text=link_text)


def _is_non_job_page(*, url: str, title: str) -> bool:
    parsed = urlsplit(url)
    # A recruiting-site root is a landing or listing page unless the adapter
    # extracted an explicit JobPosting object before reaching this classifier.
    # Treating generic root copy as one job caused slogans such as ByteDance's
    # careers homepage headline to enter the candidate pool.
    if parsed.path in {"", "/"} and not parsed.query:
        return True

    path_segments = {
        segment.casefold()
        for segment in parsed.path.split("/")
        if segment.strip()
    }
    if path_segments & _NON_JOB_PATH_SEGMENTS:
        return True

    normalized_title = re.sub(r"\s+", "", title).casefold()
    return any(
        phrase.casefold() in normalized_title for phrase in _NON_JOB_TITLE_PHRASES
    )


def _looks_like_dynamic_shell(raw_html: str) -> bool:
    return len(re.findall(r"<script\b", raw_html, flags=re.IGNORECASE)) >= 5


def looks_like_dynamic_shell(raw_html: str) -> bool:
    return _looks_like_dynamic_shell(raw_html)


def _rank_official_jobs(jobs: list[JobStub], *, query: str) -> list[JobStub]:
    unique_jobs = _dedupe_stubs(jobs)
    terms = _search_terms(query)
    ranked: list[tuple[int, int, JobStub]] = []
    for index, job in enumerate(unique_jobs):
        title_text = f"{job.title or ''} {job.company or ''}".casefold()
        body_text = f"{title_text} {job.raw_content}".casefold()
        title_hits = sum(term in title_text for term in terms)
        body_hits = sum(term in body_text for term in terms)
        explicit_job_bonus = 2 if job.job_type not in {None, "unknown"} else 0
        score = title_hits * 8 + body_hits + explicit_job_bonus
        ranked.append((score, -index, job))
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [job for _, _, job in ranked]


def _dedupe_stubs(jobs: list[JobStub]) -> list[JobStub]:
    result: list[JobStub] = []
    seen: set[str] = set()
    for job in jobs:
        normalized_url = urlsplit(job.detail_url)._replace(fragment="").geturl().rstrip("/")
        key = normalized_url.casefold() or f"{job.source_id}:{job.source_job_id}"
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result


def _search_terms(query: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-/]*|[\u4e00-\u9fff]{2,}", query):
        normalized = token.casefold()
        if normalized not in terms:
            terms.append(normalized)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            for index in range(len(token) - 1):
                pair = token[index : index + 2].casefold()
                if pair not in terms:
                    terms.append(pair)
    return terms


def _bytedance_search_terms(query: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(
        r"[A-Za-z][A-Za-z0-9+.#-]*(?:\s+[A-Za-z][A-Za-z0-9+.#-]*)*",
        query,
    ):
        term = re.sub(r"\s+", " ", match.group()).strip()
        if term and term.casefold() not in {item.casefold() for item in terms}:
            terms.append(term)
    for term in (
        "大模型",
        "算法",
        "后端",
        "前端",
        "客户端",
        "数据",
        "测试",
        "产品",
        "运营",
        "安全",
    ):
        if term in query and term not in terms:
            terms.append(term)
    if terms:
        return terms
    fallback = re.sub(
        r"(校招|校园招聘|社招|社会招聘|实习岗位|招聘岗位|岗位|职位)",
        " ",
        query,
    )
    fallback = re.sub(r"\s+", " ", fallback).strip(" /,，、")
    return [fallback[:80] or query[:80]]


def _tencent_recruitment_type_ids(query: str) -> list[int]:
    normalized = query.casefold()
    campus = any(term in normalized for term in ("校招", "校园招聘", "应届"))
    internship = any(term in normalized for term in ("实习", "internship", "intern"))
    social = any(term in normalized for term in ("社招", "社会招聘", "正式岗", "全职"))
    if campus or internship or social:
        result: list[int] = []
        if campus:
            result.append(2)
        if internship:
            result.append(3)
        if social:
            result.append(1)
        return result
    return [2, 3, 1]


def _tencent_job_type(recruitment_type_id: int) -> str:
    return {1: "full_time", 2: "campus", 3: "internship"}.get(
        recruitment_type_id,
        "unknown",
    )


def _tencent_locations(value: object) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    return _unique(re.split(r"\s*[/,，、|]\s*", text))


def _matching_location_codes(payload: object, *, query: str) -> list[str]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return []
    data = payload.get("data")
    city_list = data.get("city_list") if isinstance(data, dict) else None
    if not isinstance(city_list, list):
        return []

    normalized_query = query.casefold()
    codes: list[str] = []
    for item in city_list:
        if not isinstance(item, dict):
            continue
        code = _clean_text(item.get("code"))
        labels = [
            label
            for label in (
                _clean_text(item.get("i18n_name")),
                _clean_text(item.get("name")),
                _clean_text(item.get("en_name")),
            )
            if label and len(label) >= 2
        ]
        if code and any(label.casefold() in normalized_query for label in labels):
            codes.append(code)
    return _unique(codes)


def _bytedance_item_matches_role(item: dict[str, object], *, query: str) -> bool:
    technical_signals = (
        "ai",
        "agent",
        "llm",
        "大模型",
        "算法",
        "后端",
        "前端",
        "客户端",
        "开发",
        "工程",
        "研发",
        "测试",
        "安全",
    )
    normalized_query = query.casefold()
    if not any(signal in normalized_query for signal in technical_signals):
        return True
    if any(signal in normalized_query for signal in ("产品", "运营", "人力", "hr")):
        return True

    title = (_clean_text(item.get("title")) or "").casefold()
    category = item.get("job_category")
    category_parts: list[str] = []
    while isinstance(category, dict):
        for key in ("i18n_name", "en_name", "name"):
            value = _clean_text(category.get(key))
            if value:
                category_parts.append(value.casefold())
        category = category.get("parent")
    category_text = " ".join(category_parts)
    if any(signal in category_text for signal in ("研发", "r&d", "engineering")):
        return True
    return any(
        signal in title
        for signal in (
            "工程师",
            "研究员",
            "开发",
            "scientist",
            "engineer",
            "developer",
            "research",
        )
    )


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


def _clean_html_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", without_tags).strip()


def _location_names(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    locations: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = (
                _clean_text(item.get("i18n_name"))
                or _clean_text(item.get("en_name"))
                or _clean_text(item.get("name"))
            )
        else:
            name = _clean_text(item)
        if name and name not in locations:
            locations.append(name)
    return locations


def _reader_timeout(reader: object) -> float | None:
    timeout = getattr(reader, "timeout_seconds", None)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return None
    return min(float(timeout), 60)


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code[:100]
    return error.__class__.__name__[:100]


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
    if isinstance(value, (int, float)) and value > 0:
        timestamp = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_tencent_date(value: object) -> datetime | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%Y年%m月%d日").replace(tzinfo=UTC)
    except ValueError:
        return _parse_datetime(cleaned)


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

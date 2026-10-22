from __future__ import annotations

import asyncio
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from html.parser import HTMLParser
from time import perf_counter
from urllib.parse import urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.discovery import (
    DiscoveryPlanBudget,
    DiscoveryPlanRoute,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoverySearchPlan,
    LeadProvider,
)
from src.infrastructure.database import SessionLocal
from src.services.company_registry import (
    company_source_hosts,
    enabled_company_source_hosts,
    enabled_company_sources,
    provider_source_options,
)
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_service import DiscoveryFailure, DiscoveryService
from src.services.discovery_sources import (
    GreenhouseAdapter,
    JobStub,
    OfficialCompanyRegistryAdapter,
)
from src.services.job_lead_service import (
    JobLeadService,
    LeadVerificationFailure,
)
from src.services.job_url import route_fragment
from src.services.lead_providers import LeadCandidate
from src.services.official_search_service import analyze_discovery_jobs
from src.services.responses_search import ResponsesSearchProvider
from src.services.url_reader import SafeHTTPReader

WEB_SEARCH_MAX_RESULTS = 20
WEB_SEARCH_ANALYSIS_LIMIT = 0
WEB_SEARCH_SOURCE_ID = "web-search:bing-rss"
WEB_SEARCH_SOURCE_URL = "https://www.bing.com/search?format=rss"
WEB_SEARCH_RUN_SOURCE_ID = "web-search-agent:v1"
TAVILY_SEARCH_SOURCE_ID = "web-search:tavily"
TAVILY_SEARCH_SOURCE_URL = "https://api.tavily.com/search"
OFFICIAL_SEARCH_SOURCE_ID = "official-registry:ai-campus-40"
OFFICIAL_SEARCH_SOURCE_URL = "registry://ai-campus-target-companies-40"


class WebSearchPayloadError(ValueError):
    code = "web_search_payload_invalid"


class WebSearchConfigurationError(ValueError):
    code = "web_search_configuration_invalid"


class _SnippetTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class BingRSSSearchProvider:
    """Use Bing's public RSS endpoint as a bounded web-search tool."""

    source_id = WEB_SEARCH_SOURCE_ID
    source_url = WEB_SEARCH_SOURCE_URL
    search_purpose = "jobs"

    def __init__(
        self,
        *,
        query: str,
        reader: SafeHTTPReader,
        company_names: list[str] | None = None,
        max_results: int = WEB_SEARCH_MAX_RESULTS,
    ) -> None:
        self.query = " ".join(query.split()).strip()
        self.reader = reader
        self.company_names = list(dict.fromkeys(company_names or []))[:10]
        self.max_results = max(1, min(max_results, WEB_SEARCH_MAX_RESULTS))

    @property
    def effective_query(self) -> str:
        if self.search_purpose == "companies":
            return self.query
        scope = ""
        if self.company_names:
            company_terms = " OR ".join(f'"{name}"' for name in self.company_names)
            scope = f" ({company_terms})"
        return f"{self.query}{scope} (招聘 OR 职位 OR careers OR jobs)"

    @property
    def request_url(self) -> str:
        return f"https://www.bing.com/search?{urlencode({'format': 'rss', 'q': self.effective_query})}"

    def build_search_plan(self) -> DiscoverySearchPlan:
        return _build_agent_search_plan(
            query=self.query,
            source_id=self.source_id,
            source_url=self.source_url,
            max_results=self.max_results,
            timeout_seconds=self.reader.timeout_seconds,
        )

    async def discover(self) -> list[LeadCandidate]:
        self.last_evidence = {"actual_queries": [self.effective_query]}
        response = await self.reader.fetch(self.request_url)
        self.last_evidence["raw_response"] = response.body.decode("utf-8", errors="replace")
        return [
            candidate
            for candidate in parse_bing_rss(
                response.body,
                max_results=self.max_results,
            )
            if self.search_purpose == "companies" or _looks_like_job_search_result(candidate)
        ]


class TavilySearchProvider:
    """Use Tavily as the preferred search API while retaining the lead boundary."""

    source_id = TAVILY_SEARCH_SOURCE_ID
    source_url = TAVILY_SEARCH_SOURCE_URL
    search_purpose = "jobs"

    def __init__(
        self,
        *,
        query: str,
        api_key: str,
        reader: SafeHTTPReader,
        company_names: list[str] | None = None,
        max_results: int = WEB_SEARCH_MAX_RESULTS,
    ) -> None:
        self.query = " ".join(query.split()).strip()
        self.api_key = api_key.strip()
        self.reader = reader
        self.company_names = list(dict.fromkeys(company_names or []))[:10]
        self.max_results = max(1, min(max_results, WEB_SEARCH_MAX_RESULTS))

    @property
    def effective_query(self) -> str:
        if self.search_purpose == "companies":
            return self.query
        company_scope = (
            f"，优先公司：{'、'.join(self.company_names)}" if self.company_names else ""
        )
        return f"{self.query}{company_scope}。只返回仍可申请的具体招聘岗位详情页。"

    def build_search_plan(self) -> DiscoverySearchPlan:
        return _build_agent_search_plan(
            query=self.query,
            source_id=self.source_id,
            source_url=self.source_url,
            max_results=self.max_results,
            timeout_seconds=self.reader.timeout_seconds,
        )

    async def discover(self) -> list[LeadCandidate]:
        self.last_evidence = {"actual_queries": [self.effective_query]}
        response, payload = await self.reader.post_json(
            self.source_url,
            {
                "api_key": self.api_key,
                "query": self.effective_query,
                "search_depth": "advanced",
                "max_results": self.max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        self.last_evidence["raw_response"] = response.body.decode("utf-8", errors="replace") if hasattr(response, "body") else json.dumps(payload, ensure_ascii=False)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("results"), list
        ):
            raise WebSearchPayloadError("Tavily 搜索返回中缺少 results 列表")

        discovered_at = datetime.now(UTC)
        candidates: list[LeadCandidate] = []
        seen_urls: set[str] = set()
        for item in payload["results"]:
            if not isinstance(item, dict):
                continue
            source_url = _normalize_result_url(str(item.get("url", "")))
            if source_url is None or source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            candidate = LeadCandidate(
                provider=LeadProvider.EXTERNAL_AGENT,
                source_url=source_url,
                source_id=self.source_id,
                source_job_id=hashlib.sha256(source_url.encode("utf-8")).hexdigest()[
                    :24
                ],
                title_hint=_clean_snippet_text(str(item.get("title", ""))),
                search_snippet=_clean_snippet_text(str(item.get("content", ""))),
                discovered_at=discovered_at,
            )
            if self.search_purpose == "companies" or _looks_like_job_search_result(candidate):
                candidates.append(candidate)
            if len(candidates) >= self.max_results:
                break
        return candidates


def _build_agent_search_plan(
    *,
    query: str,
    source_id: str,
    source_url: str,
    max_results: int,
    timeout_seconds: float,
) -> DiscoverySearchPlan:
    return DiscoverySearchPlan(
        version="web-search-v1",
        planner="bounded_web_search_agent",
        query=query,
        allowed_source_ids=[OFFICIAL_SEARCH_SOURCE_ID, source_id],
        routes=[
            DiscoveryPlanRoute(
                source_id=OFFICIAL_SEARCH_SOURCE_ID,
                company=None,
                source_url=OFFICIAL_SEARCH_SOURCE_URL,
                tool_sequence=["source_adapter", "static_job_page_validator"],
            ),
            DiscoveryPlanRoute(
                source_id=source_id,
                company=None,
                source_url=source_url,
                tool_sequence=["web_search", "static_job_page_validator"],
            ),
        ],
        budget=DiscoveryPlanBudget(
            max_results=max_results,
            max_analysis=WEB_SEARCH_ANALYSIS_LIMIT,
            max_concurrency=6,
            request_timeout_seconds=timeout_seconds,
        ),
        stop_conditions=[
            "max_results_reached",
            "source_route_exhausted",
        ],
    )


def parse_bing_rss(raw_xml: bytes, *, max_results: int = 20) -> list[LeadCandidate]:
    """Parse web results as untrusted leads; snippets never become job facts."""

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as error:
        raise WebSearchPayloadError("联网搜索返回的 RSS 内容无效") from error

    discovered_at = datetime.now(UTC)
    candidates: list[LeadCandidate] = []
    seen_urls: set[str] = set()
    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        fields = {
            _local_name(child.tag): "".join(child.itertext()).strip() for child in item
        }
        source_url = _normalize_result_url(fields.get("link", ""))
        if source_url is None or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        candidates.append(
            LeadCandidate(
                provider=LeadProvider.EXTERNAL_AGENT,
                source_url=source_url,
                source_id=WEB_SEARCH_SOURCE_ID,
                source_job_id=hashlib.sha256(source_url.encode("utf-8")).hexdigest()[
                    :24
                ],
                title_hint=_clean_snippet_text(fields.get("title")),
                search_snippet=_clean_snippet_text(fields.get("description")),
                discovered_at=discovered_at,
            )
        )
        if len(candidates) >= max(1, min(max_results, WEB_SEARCH_MAX_RESULTS)):
            break
    return candidates


def create_web_search_provider(
    query: str,
    company_ids: list[str] | None = None,
    *, sources=None,
) -> BingRSSSearchProvider | TavilySearchProvider | ResponsesSearchProvider:
    settings = get_settings()
    company_names = (
        [source.company for source in (sources if sources is not None else enabled_company_sources(company_ids)) if source.id in company_ids]
        if company_ids
        else []
    )
    provider_name = settings.web_search_provider.strip().casefold().replace("-", "_")
    if provider_name == "responses":
        if not settings.llm_base_url or not settings.llm_api_key:
            raise WebSearchConfigurationError(
                "Responses 搜索需要配置 LLM_BASE_URL 和 LLM_API_KEY"
            )
        return ResponsesSearchProvider(
            query=query,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            company_names=company_names,
            timeout_seconds=min(settings.llm_timeout_seconds, settings.web_search_request_timeout_seconds),
        )
    if provider_name == "auto" and settings.tavily_api_key:
        provider_name = "tavily"
    elif provider_name == "auto":
        provider_name = "bing_rss"

    if provider_name == "tavily":
        if not settings.tavily_api_key:
            raise WebSearchConfigurationError(
                "WEB_SEARCH_PROVIDER=tavily 时需要配置 TAVILY_API_KEY"
            )
        return TavilySearchProvider(
            query=query,
            api_key=settings.tavily_api_key,
            company_names=company_names,
            reader=SafeHTTPReader(
                timeout_seconds=15,
                max_bytes=500_000,
                max_retries=1,
                proxy=settings.url_fetch_proxy,
                proxy_allowed_hosts={"api.tavily.com"},
                proxy_allow_unlisted_hosts=(
                    settings.url_fetch_proxy_allow_unlisted_hosts
                ),
            ),
        )
    if provider_name != "bing_rss":
        raise WebSearchConfigurationError(
            "WEB_SEARCH_PROVIDER 只能是 auto、responses、tavily 或 bing_rss"
        )

    return BingRSSSearchProvider(
        query=query,
        company_names=company_names,
        reader=SafeHTTPReader(
            timeout_seconds=8,
            max_bytes=500_000,
            max_retries=0,
            proxy=settings.url_fetch_proxy,
            proxy_allowed_hosts={"bing.com", "www.bing.com"},
            proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        ),
    )


def execute_web_search_in_worker(
    *,
    run_id: str,
    user_id: str,
    query: str,
    company_ids: list[str] | None = None,
) -> None:
    """Keep web search, source verification, and model work off the API loop."""

    asyncio.run(
        execute_web_search(
            run_id=run_id,
            user_id=user_id,
            query=query,
            company_ids=company_ids,
        )
    )
    from src.services.body_review_queue import enqueue_run_reviews

    enqueue_run_reviews(run_id, user_id)


async def execute_web_search(
    *,
    run_id: str,
    user_id: str,
    query: str,
    company_ids: list[str] | None = None,
) -> None:
    runtime_settings = get_settings()
    with SessionLocal() as lookup_session:
        saved_run = lookup_session.get(DiscoveryRun, run_id)
        has_saved_goal = bool(saved_run and saved_run.user_id == user_id and saved_run.search_goal_id)
    if (
        runtime_settings.web_search_provider.strip().casefold() == "responses"
        or runtime_settings.web_search_decision_mode == "agent"
        or runtime_settings.web_search_direct_sources_enabled
        or has_saved_goal
    ):
        from src.services.multiround_search import execute_multiround_search

        await execute_multiround_search(
            run_id=run_id, user_id=user_id, query=query, company_ids=company_ids
        )
        return
    with SessionLocal() as session:
        run = session.get(DiscoveryRun, run_id)
        if run is None or run.user_id != user_id:
            return

        settings = get_settings()
        sources = enabled_company_sources(company_ids, session=session, user_id=user_id)
        # Hosted search discovers links directly; do not fill its budget with
        # unrelated adapter fallback results before verification starts.
        if settings.web_search_provider.strip().casefold() == "responses":
            sources = []
        official_adapter = OfficialCompanyRegistryAdapter(
            sources=sources,
            query=query,
            reader=SafeHTTPReader(
                timeout_seconds=8,
                max_retries=0,
                proxy=settings.url_fetch_proxy,
                proxy_allowed_hosts=company_source_hosts(sources),
                proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
            ),
            max_jobs=10,
        )
        official_result = None
        try:
            if sources:
                official_result = await DiscoveryService(
                    session,
                    official_adapter,
                ).run(user_id=user_id, run=run, finalize=False)
        except DiscoveryFailure:
            session.rollback()
            run = session.get(DiscoveryRun, run_id)
            if run is None:
                return
            run.status = DiscoveryRunStatus.RUNNING.value
            run.finished_at = None
            session.commit()

        provider = create_web_search_provider(query, company_ids, **provider_source_options(company_ids, sources))
        started = perf_counter()
        web_search_error: Exception | None = None
        try:
            candidates = await provider.discover()
        except Exception as error:  # noqa: BLE001 - persist an actionable run failure
            session.rollback()
            run = session.get(DiscoveryRun, run_id)
            if run is None or run.discovered_count == 0:
                _finish_web_search_failure(session, run_id, error, provider=provider)
                return
            web_search_error = error
            candidates = []
            run.failure_summary = "\n".join(
                item
                for item in (
                    run.failure_summary,
                    f"网页搜索补充失败：{str(error)[:500]}",
                )
                if item
            )[:4000]
            session.commit()

        official_hosts = enabled_company_source_hosts(session=session, user_id=user_id)
        official_hosts.update(GreenhouseAdapter.supported_hosts)
        lead_reader = SafeHTTPReader(
            timeout_seconds=8,
            max_retries=0,
            proxy=settings.url_fetch_proxy,
            proxy_allowed_hosts=official_hosts,
            proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        )
        run = session.get(DiscoveryRun, run_id)
        if run is None:
            return
        official_count = run.discovered_count
        candidates = candidates[: max(0, WEB_SEARCH_MAX_RESULTS - official_count)]
        leads = JobLeadService(session)
        result_matches = list(run.result_matches or [])
        matched_job_ids = {
            str(item["job_posting_id"])
            for item in result_matches
            if item.get("job_posting_id")
        }
        strict_job_ids = (
            list(official_result.analysis_job_posting_ids)
            if official_result is not None
            else []
        )
        new_count = run.new_count
        duplicate_count = run.duplicate_count
        status_counts: dict[str, int] = {}
        unexpected_failures: list[str] = []

        for index, candidate in enumerate(candidates, start=1):
            try:
                lead = leads.capture_candidate(
                    user_id=user_id,
                    discovery_run_id=run_id,
                    candidate=candidate,
                )
                verified = await leads.verify_url(
                    user_id=user_id,
                    lead_id=lead.id,
                    reader=lead_reader,
                    official_hosts=official_hosts,
                )
            except LeadVerificationFailure as error:
                checked_lead = leads.get_lead(user_id=user_id, lead_id=error.lead_id)
                status_counts[checked_lead.status] = (
                    status_counts.get(checked_lead.status, 0) + 1
                )
                continue
            except Exception as error:  # noqa: BLE001 - preserve other leads
                session.rollback()
                unexpected_failures.append(f"#{index}: {str(error)[:300]}")
                continue

            posting = verified.posting
            if posting.id in matched_job_ids:
                duplicate_count += 1
                status_counts[verified.lead.status] = (
                    status_counts.get(verified.lead.status, 0) + 1
                )
                continue
            matched_job_ids.add(posting.id)
            stub = JobStub(
                source_id=posting.source_id
                or candidate.source_id
                or WEB_SEARCH_SOURCE_ID,
                source_job_id=(
                    posting.source_job_id
                    or candidate.source_job_id
                    or hashlib.sha256(candidate.source_url.encode("utf-8")).hexdigest()[
                        :24
                    ]
                ),
                company=posting.company,
                title=posting.title,
                locations=posting.locations or [],
                job_type=posting.job_type,
                published_at=posting.published_at,
                detail_url=posting.source_url or candidate.source_url,
                raw_content=posting.raw_content,
                recruitment_context=posting.recruitment_context or {},
            )
            match = classify_discovery_job(stub, query=query, conditions=run.goal_conditions)
            result_matches.append(match.as_dict(job_posting_id=posting.id))
            run.result_matches = list(result_matches)
            session.commit()
            if match.match_tier == "strict":
                strict_job_ids.append(posting.id)
            if verified.posting_created:
                new_count += 1
            else:
                duplicate_count += 1
            status_counts[verified.lead.status] = (
                status_counts.get(verified.lead.status, 0) + 1
            )

        run = session.get(DiscoveryRun, run_id)
        if run is None:
            return
        run.discovered_count = official_count + len(candidates)
        run.new_count = new_count
        run.duplicate_count = duplicate_count
        run.result_matches = result_matches
        run.failure_summary = (
            "\n".join(
                item for item in (run.failure_summary, *unexpected_failures) if item
            )[:4000]
            or None
        )
        run.agent_trace = [
            *(run.agent_trace or []),
            {
                "phase": "act",
                "tool": provider.source_id,
                "outcome": (
                    "failed"
                    if web_search_error is not None
                    else "succeeded"
                    if candidates
                    else "empty"
                ),
                "observation": (
                    f"网页搜索补充失败：{str(web_search_error)[:300]}"
                    if web_search_error is not None
                    else f"网页搜索补充 {len(candidates)} 条岗位线索。"
                ),
                "decision": (
                    "保留已经核验的官网岗位和筛选结果。"
                    if web_search_error is not None
                    else "所有结果先保存为线索，不采用搜索摘要作为岗位事实。"
                ),
                "source_id": provider.source_id,
                "company": None,
                "url": provider.source_url,
                "occurred_at": datetime.now(UTC).isoformat(),
                "duration_ms": max(0, round((perf_counter() - started) * 1000)),
                "error_code": (
                    getattr(web_search_error, "code", "web_search_failed")
                    if web_search_error is not None
                    else None
                ),
                "details": {
                    "output_count": len(candidates),
                    "official_output_count": official_count,
                },
            },
            {
                "phase": "observe",
                "tool": "original_job_page_verifier",
                "outcome": "succeeded" if result_matches else "empty",
                "observation": (
                    f"已从原始页面核验 {len(result_matches)} 条岗位；"
                    f"严格匹配 {len(strict_job_ids)} 条。"
                ),
                "decision": ("依据原始页面事实筛选岗位；其余线索保留待核验。"),
                "source_id": None,
                "company": None,
                "url": None,
                "occurred_at": datetime.now(UTC).isoformat(),
                "duration_ms": None,
                "error_code": None,
                "details": {
                    "verified_count": len(result_matches),
                    "strict_count": len(strict_job_ids),
                    "expanded_count": len(result_matches) - len(strict_job_ids),
                    "lead_status_counts": status_counts,
                    "unexpected_failure_count": len(unexpected_failures),
                },
            },
        ][-60:]
        if not result_matches:
            run.agent_trace = [
                *(run.agent_trace or []),
                {
                    "phase": "stop",
                    "tool": "pending_verification",
                    "outcome": "recommended",
                    "observation": "本次没有自动核验成功的具体岗位页。",
                    "decision": "保留搜索线索，可继续核验或调整条件搜索。",
                    "source_id": None,
                    "company": None,
                    "url": None,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "duration_ms": None,
                    "error_code": None,
                    "details": {"requires_human_input": False},
                },
            ][-60:]
        session.commit()

        await analyze_discovery_jobs(
            session,
            run_id=run_id,
            user_id=user_id,
            job_ids=list(
                dict.fromkeys(
                    [
                        *strict_job_ids,
                        *(
                            str(item["job_posting_id"])
                            for item in result_matches
                            if item.get("mismatch_labels")
                            and all(
                                "待确认" in label for label in item["mismatch_labels"]
                            )
                        ),
                    ]
                )
            ),
            analysis_limit=WEB_SEARCH_ANALYSIS_LIMIT,
        )


def _finish_web_search_failure(
    session: Session, run_id: str, error: Exception, *, provider=None
) -> None:
    run = session.get(DiscoveryRun, run_id)
    if run is None:
        return
    detail = f"全网搜索失败：{str(error)[:500]}"
    run.status = DiscoveryRunStatus.FAILED.value
    run.analysis_status = "FAILED"
    run.failure_summary = detail
    run.agent_trace = [
        *(run.agent_trace or []),
        {
            "phase": "stop",
            "tool": provider.source_id if provider else "bing_web_search",
            "outcome": "failed",
            "observation": detail,
            "decision": "停止本次运行，不把未核验的搜索摘要当作岗位。",
            "source_id": provider.source_id if provider else WEB_SEARCH_SOURCE_ID,
            "company": None,
            "url": provider.source_url if provider else WEB_SEARCH_SOURCE_URL,
            "occurred_at": datetime.now(UTC).isoformat(),
            "duration_ms": None,
            "error_code": getattr(error, "code", "web_search_failed"),
            "details": {},
        },
    ][-60:]
    run.finished_at = datetime.now(UTC)
    session.commit()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _normalize_result_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path or "/",
            parsed.query,
            route_fragment(parsed.fragment),
        )
    )


def _clean_snippet_text(value: str | None) -> str | None:
    parser = _SnippetTextParser()
    parser.feed(value or "")
    parser.close()
    cleaned = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
    return cleaned[:2000] or None


def _looks_like_job_search_result(candidate: LeadCandidate) -> bool:
    text = f"{candidate.title_hint or ''} {candidate.search_snippet or ''}".casefold()
    return any(
        term in text
        for term in (
            "招聘",
            "职位",
            "岗位",
            "校招",
            "实习",
            "career",
            "job",
            "intern",
            "engineer",
            "developer",
            "scientist",
            "工程师",
            "产品经理",
            "研究员",
        )
    )

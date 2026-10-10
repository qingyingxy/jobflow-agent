"""Read current ATS search results through the public site's own browser UI.

Tenant ownership comes from the
official homepage, IDs from current filter responses, and facts from full public
job payloads. None of these facts are inferred from search-engine snippets.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urlencode, urlsplit, urlunsplit

from src.domain.discovery import LeadProvider
from src.services.discovery_matching import (
    _LOCATION_GROUPS,
    _ROLE_GROUPS,
    search_filter_conditions,
)
from src.services.discovery_sources import ByteDanceAdapter, JobStub, SourcePayloadError
from src.services.lead_providers import LeadCandidate
from src.services.official_hiring_resolver import OfficialHiringResolver
from src.services.recruitment_trust import hiring_scope, within_scope
from src.services.search_constraints import select_term_groups
from src.services.url_reader import _HTMLTextParser, extract_html_links


@dataclass(frozen=True)
class DirectJobEvidence:
    stub: JobStub
    official_url: str
    official_html: str
    listing_url: str
    api_record: dict
    full_body: bool
    official_proof_url: str | None = None


def search_keywords(query):
    positive, _ = select_term_groups(query, [g[0] for g in _ROLE_GROUPS])
    positions = []
    for aliases in positive:
        matches = [(query.casefold().find(alias), alias) for alias in aliases if alias in query.casefold()]
        if matches:
            positions.append(min(matches))
    return list(dict.fromkeys(term for _, term in sorted(positions)))[:3]


def listing_filters(data, query):
    """Use positive location choices; leave unsupported/ambiguous filters open."""
    wanted, _ = select_term_groups(query, _LOCATION_GROUPS)
    locations = [
        item["code"] for item in data.get("city_list") or []
        if item.get("code") and any(
            str(item.get("name", "")).casefold() in group
            or str(item.get("en_name", "")).casefold() in group for group in wanted
        )
    ]
    years = search_filter_conditions(query)["graduation_years"]
    internship = search_filter_conditions(query)["job_types"] == ["实习"]
    subjects = []
    for item in data.get("job_subject_list") or []:
        name = item.get("name") or {}
        name = name.get("zh_cn") or name.get("i18n") or "" if isinstance(name, dict) else str(name)
        group = item.get("subject_group_info") or {}
        group_name = group.get("name") or ""
        if isinstance(group_name, dict):
            group_name = group_name.get("zh_cn") or group_name.get("i18n") or ""
        matches_year = not years or any(f"{year}届" in name for year in years)
        matches_type = "实习" in (name + group_name) if internship else bool(years and re.search(r"校招|校园招聘", name) and "实习" not in (name + group_name))
        if item.get("id") and matches_year and matches_type:
            subjects.append(item["id"])
    return {"location": ",".join(locations), "project": ",".join(subjects)}


def payload_stub(item, *, company, listing_url):
    # Reuse the existing payload normalizer, with the current campus detail URL.
    # A list card without full requirements must go through normal page reading.
    if not isinstance(item, dict):
        raise SourcePayloadError("官网岗位格式无效")
    stub = ByteDanceAdapter(query="", company=company)._to_stub(item)
    parsed = urlsplit(listing_url)
    prefix = "/campus" if parsed.hostname == "jobs.bytedance.com" else "/" + parsed.path.strip("/").split("/")[0]
    detail = urlunsplit((parsed.scheme, parsed.netloc, f"{prefix}/position/{stub.source_job_id}/detail", "", ""))
    subject = (item.get("job_subject") or {}).get("name") or {}
    subject = subject.get("zh_cn") or subject.get("i18n") or "" if isinstance(subject, dict) else str(subject)
    # The shared normalizer collapses whitespace for card metadata. Full ATS
    # sections need their original paragraph boundaries for duty evidence.
    header = stub.raw_content.split("岗位职责：", 1)[0].split("任职要求：", 1)[0].strip()
    sections = [header]
    for field, heading in (("description", "岗位职责"), ("requirement", "任职要求")):
        if isinstance(item.get(field), str) and item[field].strip():
            parser = _HTMLTextParser()
            parser.feed(item[field])
            parser.close()
            text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
            sections.append(heading + "：\n" + text)
    return replace(
        stub, source_id=f"official-ats:{parsed.hostname}:{prefix}", detail_url=detail,
        raw_content=(subject + "\n" + "\n".join(sections)).strip(),
    )


class DirectRecruitmentSearch:
    def __init__(self, *, sources, query, reader, browser, on_event, max_jobs=20):
        self.sources = [s for s in sources if s.id in {"bytedance", "minimax", "xiaomi", "nio"}]
        self.query, self.reader, self.browser = query, reader, browser
        self.on_event = on_event
        self.max_jobs = max_jobs
        self.evidence = {}
        self.resolver = OfficialHiringResolver(sources=self.sources, reader=reader, browser=browser)

    @property
    def supported(self):
        types = search_filter_conditions(self.query)["job_types"]
        return bool(self.sources and search_keywords(self.query) and types in (["校招"], ["实习"]) and hasattr(self.browser, "read_search_listing"))

    async def discover(self, publish):
        semaphore = asyncio.Semaphore(2)
        async def source_jobs(source):
            started = monotonic()
            count = 0
            try:
                async with semaphore:
                    async for candidate in self._source(source):
                        count += 1
                        publish([candidate])
            except asyncio.CancelledError:
                self.on_event("direct_search", {"company": source.company, "error_code": "direct_search_cancelled", "output_count": count, "duration_ms": int((monotonic()-started)*1000)})
                raise
            except Exception as error:  # noqa: BLE001 - normal web search remains available
                self.on_event("direct_search", {"company": source.company, "error_code": getattr(error, "code", type(error).__name__), "output_count": count, "duration_ms": int((monotonic()-started)*1000)})
            else:
                self.on_event("direct_search", {"company": source.company, "output_count": count, "duration_ms": int((monotonic()-started)*1000), "summary": f"{source.company}官网定向检索发现 {count} 个岗位"})
        await asyncio.gather(*(source_jobs(source) for source in self.sources))

    async def _source(self, source):
        official_html = ""
        proof_url = source.career_url
        if source.id == "bytedance":
            if source.career_url != "https://jobs.bytedance.com/campus/":
                return
            entry = source.career_url + "position"
        else:
            pages = {}
            def remember(url, html):
                pages[url] = html
                return url
            records = await self.resolver._read_source(source, remember)
            internship = search_filter_conditions(self.query)["job_types"] == ["实习"]
            entries = []
            for record in records:
                path = urlsplit(record.scope_url).path
                host = urlsplit(record.scope_url).hostname or ""
                if not host.endswith((".jobs.feishu.cn", ".jobs.f.mioffice.cn")):
                    continue
                links = extract_html_links(pages[record.from_url], base_url=record.from_url)
                label = next((link.text for link in links if link.url == record.scope_url), "")
                is_intern = bool(re.search(r"/internship/?$", path) or "实习" in label)
                is_campus = bool(re.search(r"/campus/?$", path) or (re.fullmatch(r"/\d+/?", path) and re.search(r"应届|校招|校园", label)))
                if (internship and is_intern) or is_campus:
                    entries.append((0 if internship and is_intern else 1, record))
            if not entries:
                raise SourcePayloadError("官网没有可追溯的校园招聘入口")
            record = min(entries, key=lambda value: value[0])[1]
            entry, proof_url = record.scope_url, record.from_url
            official_html = pages[proof_url]
            scope = hiring_scope(entry)
            if not scope:
                raise SourcePayloadError("招聘入口缺少企业作用域")
            self.browser.safety_checker.proxy_allowed_hosts |= {scope[0]}
        parsed = urlsplit(entry)
        base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        initial = await self.browser.read_search_listing(base)
        if not same_origin(initial.final_url, base):
            raise SourcePayloadError("招聘站发生跨站跳转")
        configs = [r["payload"].get("data") for r in initial.recruitment_api if same_origin(r["url"], base) and re.fullmatch(r"/api/v1/config/job/filters/\d+", urlsplit(r["url"]).path) and r["payload"].get("code") == 0]
        if not configs or not isinstance(configs[-1], dict):
            raise SourcePayloadError("未读取到站内筛选配置")
        filters = listing_filters(configs[-1], self.query)
        wanted, _ = select_term_groups(self.query, _LOCATION_GROUPS)
        if wanted and configs[-1].get("city_list") and not filters["location"]:
            return  # The current listing has no requested city; web fallback remains.
        found = set()
        exhausted = set()
        # First page of every direction before the next page; cap total jobs per employer.
        for current, keyword in ((page, term) for page in (1, 2) for term in search_keywords(self.query)):
            if keyword in exhausted:
                continue
            parameters = {"keywords": keyword, "category": "", **filters, "type": "", "current": str(current), "limit": "10", "functionCategory": "", "tag": ""}
            listing_url = base + "?" + urlencode(parameters)
            page = await self.browser.read_search_listing(listing_url)
            if not same_origin(page.final_url, base) or (hiring_scope(base) and not within_scope(page.final_url, hiring_scope(base))):
                raise SourcePayloadError("招聘结果发生跨站跳转")
            observed_urls = {urlsplit(link.url).path for link in extract_html_links(page.raw_html, base_url=page.final_url) if urlsplit(link.url).hostname == parsed.hostname}
            before = len(found)
            for record in page.recruitment_api:
                if not same_origin(record["url"], base) or urlsplit(record["url"]).path != "/api/v1/search/job/posts" or record["payload"].get("code") != 0:
                    continue
                # Ignore startup/unfiltered responses and retain the actual query.
                request = record["request"]
                if request.get("keyword", "").casefold() != keyword.casefold():
                    continue
                if request.get("offset") != (current - 1) * 10 or request.get("limit") != 10:
                    continue
                expected_cities = set(filter(None, filters["location"].split(",")))
                expected_subjects = set(filter(None, filters["project"].split(",")))
                if set(request.get("location_code_list") or []) != expected_cities or set(request.get("subject_id_list") or []) != expected_subjects:
                    continue
                data = record["payload"].get("data") or {}
                items = data.get("job_post_list") or []
                if not isinstance(items, list):
                    raise SourcePayloadError("官网岗位列表格式变化")
                for item in items:
                    try:
                        stub = payload_stub(item, company=source.company, listing_url=base)
                    except SourcePayloadError:
                        continue
                    if stub.detail_url in found:
                        continue
                    if urlsplit(stub.detail_url).path not in observed_urls:
                        continue
                    found.add(stub.detail_url)
                    full_body = all(isinstance(item.get(k), str) and len(item[k].strip()) >= 8 for k in ("description", "requirement"))
                    self.evidence[stub.detail_url] = DirectJobEvidence(stub, source.career_url, official_html, listing_url, record, full_body, proof_url)
                    yield LeadCandidate(
                        provider=LeadProvider.OFFICIAL_ADAPTER, source_url=stub.detail_url,
                        source_id=stub.source_id, source_job_id=stub.source_job_id,
                        company_hint=source.company, title_hint=stub.title,
                        discovered_at=datetime.now(UTC), official_entry_url=source.career_url,
                    )
                    if len(found) >= self.max_jobs:
                        return
            if len(found) == before:
                exhausted.add(keyword)


def same_origin(url, expected):
    left, right = urlsplit(url), urlsplit(expected)
    return (left.scheme, left.netloc) == (right.scheme, right.netloc)

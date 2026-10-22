"""Collect Chinese public campus JDs with employer quotas and source evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from scripts.collect_product_jd_unseen import (
    digest,
    previous_ids,
    requirement_fingerprint,
)
from scripts.run_product_jd_unseen_acceptance import write
from src.config import Settings
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.company_registry import company_source_hosts, enabled_company_sources
from src.services.direct_recruitment_search import payload_stub
from src.services.discovery_sources import TencentAdapter
from src.services.official_hiring_resolver import OfficialHiringResolver
from src.services.recruitment_trust import hiring_scope
from src.services.url_reader import SafeHTTPReader, extract_html_links

COMPANIES = ("bytedance", "tencent", "minimax", "xiaomi", "nio")
TERMS = ("大模型", "算法", "软件", "后端", "数据", "开发", "")


def chinese_requirements(text):
    body = text.split("任职要求：", 1)[-1]
    chinese = len(re.findall(r"[\u4e00-\u9fff]", body))
    letters = len(re.findall(r"[a-zA-Z]", body))
    return chinese >= 20 and chinese / max(1, chinese + letters) >= 0.35


async def collect(root, *, per_company):
    seen_ids, seen_texts, prior_files = previous_ids()
    # Unselected listing cards have not been parsed or labeled. Keep excluding
    # actual historical cases; do not treat a failed collection's entire list
    # snapshot as a model evaluation set.
    prior_files = {
        p: h for p, h in prior_files.items() if Path(p).name != "listing_snapshots.json"
    }
    seen_ids = set()
    for path in prior_files:
        seen_ids.update(
            re.findall(r"\b\d{16,20}\b", Path(path).read_text(encoding="utf-8-sig"))
        )
    root.mkdir(parents=True)
    settings = Settings()
    sources = enabled_company_sources(COMPANIES)
    hosts = company_source_hosts(sources)
    reader = SafeHTTPReader(
        proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts=hosts,
        timeout_seconds=20,
        max_retries=0,
    )
    browser = PlaywrightBrowserJobReader(timeout_seconds=25)
    resolver = OfficialHiringResolver(sources=sources, reader=reader, browser=browser)
    candidates, errors, snapshots, evidence = [], [], [], []
    semaphore = asyncio.Semaphore(2)

    def save():
        write(
            root / "sources.json",
            {
                "created_at": datetime.now(UTC).isoformat(),
                "requested_per_company": per_company,
                "companies_requested": list(COMPANIES),
                "collected": len(candidates),
                "cases": candidates,
                "errors": errors,
                "official_evidence": evidence,
                "exclusion_files": prior_files,
                "live_model_calls": 0,
                "limitations": [
                    "Fresh relative to local evaluation IDs and normalized requirements, not proof of pretraining independence.",
                    "Employer quotas and Chinese requirements improve coverage; the sample is not random or representative of all employers.",
                    "Education/qualification labels must be fixed separately before any model parsing.",
                ],
            },
        )
        write(root / "listing_snapshots.json", snapshots)

    def add(stub, source, proof):
        if stub.source_job_id in seen_ids or stub.job_type not in {
            "campus",
            "internship",
        }:
            return False
        if not chinese_requirements(stub.raw_content):
            return False
        if not re.search(
            r"算法|开发|软件|工程师|数据|模型|技术|研发|智能", stub.title or ""
        ):
            return False
        fingerprint = requirement_fingerprint(stub.raw_content)
        if fingerprint in seen_texts:
            return False
        # Keep an explicit education gate so positive/negative candidates can
        # be checked against the same JD without inventing missing requirements.
        body = stub.raw_content.split("任职要求：", 1)[-1]
        if not re.search(r"本科|硕士|博士|学历不限|不限学历", body):
            return False
        seen_ids.add(stub.source_job_id)
        seen_texts.add(fingerprint)
        candidates.append(
            {
                "id": f"zh-{source.id}-{sum(c['company_id'] == source.id for c in candidates) + 1:02d}",
                "company_id": source.id,
                "company": stub.company,
                "title": stub.title,
                "source_job_id": stub.source_job_id,
                "source_url": stub.detail_url,
                "raw_content": stub.raw_content,
                "content_sha256": digest(stub.raw_content),
                "requirement_sha256": fingerprint,
                "official_job_type": stub.job_type,
                "evidence": proof,
            }
        )
        save()
        print(
            json.dumps(
                {
                    "company": source.company,
                    "collected": len(candidates),
                    "title": stub.title,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return True

    async def ats(source):
        if source.id == "bytedance":
            entry = source.career_url + "position"
            proof = {"official_entry": source.career_url, "listing_url": entry}
        else:
            pages = {}

            def remember(url, html):
                pages[url] = html
                path = root / f"{source.id}-official-{len(pages)}.html"
                path.write_text(html, encoding="utf-8")
                return path.as_posix()

            records = await resolver._read_source(source, remember)
            eligible = []
            for record in records:
                parsed = urlsplit(record.scope_url)
                if not parsed.hostname or not parsed.hostname.endswith(
                    (".jobs.feishu.cn", ".jobs.f.mioffice.cn")
                ):
                    continue
                links = extract_html_links(
                    pages[record.from_url], base_url=record.from_url
                )
                label = next(
                    (link.text for link in links if link.url == record.scope_url), ""
                )
                if "/campus" in parsed.path or re.search(r"应届|校招|校园", label):
                    eligible.append(record)
            if not eligible:
                raise ValueError("No current official campus entry")
            record = eligible[0]
            entry = record.scope_url
            proof = asdict(record)
        host = urlsplit(entry).hostname
        if not host or (source.id != "bytedance" and not hiring_scope(entry)):
            raise ValueError("Invalid official tenant scope")
        browser.safety_checker.proxy_allowed_hosts |= {host}
        reader.safety_checker.proxy_allowed_hosts |= {host}
        page = await browser.read_search_listing(entry)
        if urlsplit(page.final_url).hostname != host:
            raise ValueError("Cross-site listing redirect")
        (root / f"{source.id}-listing.html").write_text(page.raw_html, encoding="utf-8")
        snapshots.append(
            {"company": source.id, "entry": entry, "captured_api": page.recruitment_api}
        )
        configs = [
            r["payload"].get("data")
            for r in page.recruitment_api
            if re.fullmatch(r"/api/v1/config/job/filters/\d+", urlsplit(r["url"]).path)
            and r["payload"].get("code") == 0
        ]
        requests = [
            r
            for r in page.recruitment_api
            if urlsplit(r["url"]).path == "/api/v1/search/job/posts"
            and r["payload"].get("code") == 0
        ]
        if not configs or not requests:
            raise ValueError("No observed public search/filter request")
        subjects = []
        for item in configs[-1].get("job_subject_list") or []:
            name = json.dumps(item.get("name"), ensure_ascii=False)
            if re.search(r"校招|校园招聘|应届", name) and "实习" not in name:
                subjects.append(item["id"])
        chosen = parse_qs(urlsplit(entry).query).get("project", [""])[0]
        subjects = [s for s in chosen.split(",") if s] or subjects
        record = requests[-1]
        proof.update(observed_api=record["url"], subject_ids=subjects)
        evidence.append({"company": source.id, **proof})
        save()
        count = 0
        parsed_entry = urlsplit(entry)
        base = urlunsplit(
            (parsed_entry.scheme, parsed_entry.netloc, parsed_entry.path, "", "")
        )
        for current in (1, 2, 3):
            for term in TERMS:
                query = {
                    "keywords": term,
                    "category": "",
                    "location": "",
                    "project": ",".join(subjects),
                    "type": "",
                    "current": str(current),
                    "limit": "10",
                    "functionCategory": "",
                    "tag": "",
                }
                listing_url = base + "?" + urlencode(query)
                listing = await browser.read_search_listing(listing_url)
                if urlsplit(listing.final_url).hostname != host:
                    raise ValueError("Cross-site listing redirect")
                matching = [
                    r
                    for r in listing.recruitment_api
                    if urlsplit(r["url"]).path == "/api/v1/search/job/posts"
                    and r["request"].get("keyword", "") == term
                    and r["request"].get("offset") == (current - 1) * 10
                    and set(r["request"].get("subject_id_list") or []) == set(subjects)
                    and r["payload"].get("code") == 0
                ]
                if not matching:
                    errors.append(
                        {
                            "company": source.id,
                            "term": term,
                            "page": current,
                            "error": "ObservedListingUnavailable",
                        }
                    )
                    save()
                    continue
                payload, response = matching[-1]["request"], matching[-1]["payload"]
                snapshots.append(
                    {
                        "company": source.id,
                        "url": matching[-1]["url"],
                        "listing_url": listing_url,
                        "request": payload,
                        "response": response,
                    }
                )
                if response.get("code") != 0:
                    raise ValueError("Public listing response failed")
                items = sorted(
                    response.get("data", {}).get("job_post_list") or [],
                    key=lambda item: digest("zh-20261010:" + str(item.get("id"))),
                )
                for item in items:
                    if not item.get("description") or not item.get("requirement"):
                        continue
                    stub = payload_stub(item, company=source.company, listing_url=entry)
                    if add(stub, source, proof):
                        count += 1
                    if count >= per_company:
                        return
                save()

    async def tencent(source):
        adapter = TencentAdapter(query="校招", reader=reader)
        proof = {"official_entry": source.career_url, "list_recruitment_type": 2}
        evidence.append({"company": source.id, **proof})
        count = 0
        for term in TERMS[:-1]:
            url = adapter._query_url(term, 2)
            _, response = await reader.fetch_json(url)
            snapshots.append({"company": source.id, "url": url, "response": response})
            for listed in adapter._payload_jobs(response, job_type="campus"):
                if listed.source_job_id in seen_ids:
                    continue
                _, detail = await reader.fetch_json(
                    adapter._detail_url(listed.source_job_id)
                )
                snapshots.append(
                    {"company": source.id, "id": listed.source_job_id, "detail": detail}
                )
                stub = adapter._to_stub(
                    adapter._payload_data(detail), job_type=listed.job_type
                )
                if add(stub, source, proof):
                    count += 1
                if count >= per_company:
                    return
            save()

    async def employer(source):
        async with semaphore:
            try:
                await (tencent(source) if source.id == "tencent" else ats(source))
            except Exception as error:  # noqa: BLE001 - retain employer failures
                errors.append(
                    {
                        "company": source.id,
                        "error": type(error).__name__,
                        "code": getattr(error, "code", None),
                    }
                )
                print(json.dumps(errors[-1]), flush=True)
            save()

    async with browser.reuse():
        await asyncio.gather(*(employer(source) for source in sources))
    save()
    print(
        json.dumps(
            {
                "collected": len(candidates),
                "counts": {
                    s.id: sum(c["company_id"] == s.id for c in candidates)
                    for s in sources
                },
                "errors": errors,
            }
        ),
        flush=True,
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--per-company", type=int, choices=range(1, 11), default=6)
    args = cli.parse_args()
    if args.output_dir.exists():
        cli.error("Use a new source directory")
    asyncio.run(collect(args.output_dir, per_company=args.per_company))


if __name__ == "__main__":
    main()

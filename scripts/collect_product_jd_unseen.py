"""Collect public JDs with IDs absent from local evaluation materials; no model calls."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from src.config import Settings
from src.services.discovery_sources import (
    ByteDanceAdapter,
    SourcePayloadError,
    TencentAdapter,
)
from src.services.url_reader import SafeHTTPReader, URLReaderError


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def requirement_fingerprint(text):
    requirements = text.split("任职要求：", 1)[-1]
    return digest(
        re.sub(r"\s+", "", unicodedata.normalize("NFKC", requirements)).casefold()
    )


def previous_ids():
    ids, fingerprints, files = set(), set(), {}
    for directory in (Path("datasets"), Path("artifacts/evaluation")):
        for path in sorted(directory.rglob("*.json")):
            text = path.read_text(encoding="utf-8-sig")
            found = set(re.findall(r"\b\d{16,20}\b", text))
            if found:
                ids.update(found)
                files[path.as_posix()] = digest(text)
            for raw in re.findall(r'"raw_content"\s*:\s*("(?:\\.|[^"\\])*")', text):
                body = json.loads(raw)
                if "任职要求：" in body:
                    fingerprints.add(requirement_fingerprint(body))
    return ids, fingerprints, files


async def collect(output, count):
    seen, seen_fingerprints, prior_files = previous_ids()
    settings = Settings()
    reader = SafeHTTPReader(
        proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts={"jobs.bytedance.com", "careers.tencent.com"},
        proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        timeout_seconds=20,
        max_retries=0,
    )
    byte = ByteDanceAdapter(query="AI 校招", reader=reader)
    tencent = TencentAdapter(query="AI 校招", reader=reader, max_jobs=20)
    candidates, errors, snapshots = {}, [], []
    semaphore = asyncio.Semaphore(3)

    async def listing(company, term):
        async with semaphore:
            try:
                if company == "bytedance":
                    _, payload = await reader.post_json(
                        byte.search_url,
                        {
                            "limit": 100,
                            "offset": 0,
                            "keyword": term,
                            "job_category_id_list": [],
                            "recruitment_id_list": [],
                            "subject_id_list": [],
                            "location_code_list": [],
                            "tag_id_list": [],
                        },
                        headers=byte.request_headers,
                    )
                    items = payload["data"]["job_post_list"]
                    stubs = [byte._to_stub(item) for item in items]
                else:
                    _, payload = await reader.fetch_json(tencent._query_url(term, 2))
                    stubs = tencent._payload_jobs(payload, job_type="campus")
                snapshots.append({"company": company, "term": term, "payload": payload})
                for stub in stubs:
                    if stub.source_job_id in seen or stub.job_type != "campus":
                        continue
                    if not re.search(
                        r"AI|LLM|大模型|算法|机器学习|智能|软件|开发|数据",
                        stub.title or "",
                        re.IGNORECASE,
                    ):
                        continue
                    candidates[(company, stub.source_job_id)] = stub
            except (
                URLReaderError,
                SourcePayloadError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                errors.append(
                    {"company": company, "term": term, "error": type(error).__name__}
                )

    await asyncio.gather(
        *(
            listing(company, term)
            for company in ("bytedance", "tencent")
            for term in (
                "AI",
                "大模型",
                "算法",
                "软件",
                "数据",
                "Java",
                "Python",
                "后端",
                "C++",
                "Machine Learning",
            )
        )
    )
    groups = {
        company: sorted(
            [s for (c, _), s in candidates.items() if c == company],
            key=lambda s: digest("product-unseen-20261010:" + s.source_job_id),
        )
        for company in ("bytedance", "tencent")
    }
    ordered = []
    while any(groups.values()):
        for group in groups.values():
            if group:
                ordered.append(group.pop(0))
    cases = []
    for stub in ordered:
        if len(cases) >= count:
            break
        try:
            adapter = byte if stub.source_id == byte.source_id else tencent
            if adapter is tencent:
                _, payload = await reader.fetch_json(
                    tencent._detail_url(stub.source_job_id)
                )
                detail = tencent._to_stub(
                    tencent._payload_data(payload), job_type=stub.job_type
                )
            else:
                detail = await adapter.fetch_job(stub.source_job_id)
            if "任职要求：" not in detail.raw_content:
                continue
            fingerprint = requirement_fingerprint(detail.raw_content)
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            cases.append(
                {
                    "id": f"unseen-{len(cases) + 1:02d}",
                    "company": detail.company,
                    "title": detail.title,
                    "source_job_id": detail.source_job_id,
                    "source_url": detail.detail_url,
                    "raw_content": detail.raw_content,
                    "content_sha256": digest(detail.raw_content),
                    "official_job_type": stub.job_type,
                }
            )
        except (
            URLReaderError,
            SourcePayloadError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            errors.append({"id": stub.source_job_id, "error": type(error).__name__})
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "requested": count,
        "collected": len(cases),
        "previous_ids": len(seen),
        "exclusion_files": prior_files,
        "cases": cases,
        "errors": errors,
        "live_model_calls": 0,
        "limitations": [
            "Unseen means official job IDs absent from local datasets/evaluation JSON, not absence from model pretraining.",
            "Two public sources and first-page listings are a convenience sample, not representative of all employers.",
            "No model parsing or label drafting occurred during collection.",
        ],
    }
    output.mkdir(parents=True)
    (output / "sources.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "listing_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"collected": len(cases), "candidates": len(candidates), "errors": errors},
            ensure_ascii=False,
        )
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--count", type=int, choices=range(1, 31), default=30)
    args = cli.parse_args()
    if args.output_dir.exists():
        cli.error("Use a fresh output directory")
    asyncio.run(collect(args.output_dir, args.count))


if __name__ == "__main__":
    main()

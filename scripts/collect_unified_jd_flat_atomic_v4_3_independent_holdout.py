from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_independent_holdout_selection_v1_2026-09-06.json"
)

CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "case_id": "independent-lever-collate-ai-engineer",
        "company": "Collate",
        "title": "AI Engineer",
        "location": "San Francisco",
        "ats": "Lever",
        "source_url": (
            "https://jobs.lever.co/collate/"
            "377f2cf3-6285-42c1-8130-dd3dd2c866cb"
        ),
        "retrieval_url": (
            "https://api.lever.co/v0/postings/collate/"
            "377f2cf3-6285-42c1-8130-dd3dd2c866cb"
        ),
        "parser": "lever",
    },
    {
        "case_id": "independent-lever-field-ai-robotics-ai-engineer",
        "company": "FieldAI",
        "title": "Robotics AI Engineer",
        "location": "Singapore",
        "ats": "Lever",
        "source_url": (
            "https://jobs.lever.co/field-ai/"
            "f326c7a0-84ee-4f91-aa16-80281203e8d3"
        ),
        "retrieval_url": (
            "https://api.lever.co/v0/postings/field-ai/"
            "f326c7a0-84ee-4f91-aa16-80281203e8d3"
        ),
        "parser": "lever",
    },
    {
        "case_id": "independent-greenhouse-simplifynext-ai-engineer-graduate",
        "company": "SimplifyNext",
        "title": "AI Engineer (Graduate)",
        "location": "Singapore",
        "ats": "Greenhouse",
        "source_url": (
            "https://job-boards.greenhouse.io/simplifynext/jobs/4996764007"
        ),
        "retrieval_url": (
            "https://boards-api.greenhouse.io/v1/boards/simplifynext/"
            "jobs/4996764007"
        ),
        "parser": "greenhouse",
    },
    {
        "case_id": "independent-greenhouse-optiver-ai-engineer",
        "company": "Optiver",
        "title": "AI Engineer",
        "location": "Amsterdam",
        "ats": "Greenhouse-backed employer page",
        "source_url": (
            "https://www.optiver.com/join-us/jobs/technology/amsterdam/"
            "ai-engineer/?gh_jid=8313105002"
        ),
        "retrieval_url": (
            "https://boards-api.greenhouse.io/v1/boards/optiverus/"
            "jobs/8313105002"
        ),
        "parser": "greenhouse",
    },
    {
        "case_id": "independent-smartrecruiters-bluescope-ai-engineer",
        "company": "BlueScope",
        "title": "AI Engineer",
        "location": "Melbourne or Sydney, Australia",
        "ats": "SmartRecruiters",
        "source_url": (
            "https://jobs.smartrecruiters.com/BlueScope/"
            "744000146609569-ai-engineer"
        ),
        "retrieval_url": (
            "https://api.smartrecruiters.com/v1/companies/BlueScope/"
            "postings/29efee61-1ff5-40c4-9510-5644ebcf8fe0"
        ),
        "parser": "smartrecruiters",
    },
)


class _VisibleTextParser(HTMLParser):
    BLOCK_TAGS: ClassVar[set[str]] = {
        "address",
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        return _clean_text("".join(self.parts))


def _html_to_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(unescape(value))
    parser.close()
    return parser.text()


def _clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in value.split("\n")]
    output: list[str] = []
    for line in lines:
        if line:
            output.append(line)
        elif output and output[-1] != "":
            output.append("")
    return "\n".join(output).strip()


def _normalized_body(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    lines = [" ".join(line.split()) for line in value.split("\n")]
    return "\n".join(lines).strip()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_object(response: httpx.Response, spec: dict[str, Any]) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise TypeError(f"expected object response: {spec['case_id']}")
    return value


def _parse_lever(value: dict[str, Any]) -> str:
    categories = value.get("categories")
    if not isinstance(categories, dict):
        raise TypeError("Lever categories must be an object")
    sections = [str(value["text"]), f"Location: {categories['location']}"]
    for label, key in (
        ("Department", "department"),
        ("Team", "team"),
        ("Employment type", "commitment"),
    ):
        item = categories.get(key)
        if isinstance(item, str) and item.strip():
            sections.append(f"{label}: {item.strip()}")
    workplace = value.get("workplaceType")
    if isinstance(workplace, str) and workplace.strip():
        sections.append(f"Workplace type: {workplace.strip()}")
    description = value.get("descriptionPlain")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Lever descriptionPlain is empty")
    sections.append(_clean_text(description))
    lists = value.get("lists")
    if not isinstance(lists, list):
        raise TypeError("Lever lists must be a list")
    for item in lists:
        if not isinstance(item, dict):
            raise TypeError("Lever list entry must be an object")
        heading = item.get("text")
        content = item.get("content")
        if not isinstance(heading, str) or not isinstance(content, str):
            raise TypeError("Lever list entry is incomplete")
        sections.extend((heading.strip(), _html_to_text(content)))
    additional = value.get("additionalPlain")
    if isinstance(additional, str) and additional.strip():
        sections.append(_clean_text(additional))
    return "\n\n".join(section for section in sections if section).strip()


def _parse_greenhouse(value: dict[str, Any]) -> str:
    title = value.get("title")
    location = value.get("location")
    content = value.get("content")
    if (
        not isinstance(title, str)
        or not isinstance(location, dict)
        or not isinstance(location.get("name"), str)
        or not isinstance(content, str)
    ):
        raise TypeError("Greenhouse job response is incomplete")
    return "\n\n".join(
        (title.strip(), f"Location: {location['name'].strip()}", _html_to_text(content))
    ).strip()


def _parse_smartrecruiters(value: dict[str, Any]) -> str:
    title = value.get("name")
    location = value.get("location")
    employment = value.get("typeOfEmployment")
    sections = value.get("jobAd", {}).get("sections")
    if (
        not isinstance(title, str)
        or not isinstance(location, dict)
        or not isinstance(location.get("fullLocation"), str)
        or not isinstance(employment, dict)
        or not isinstance(employment.get("label"), str)
        or not isinstance(sections, dict)
    ):
        raise TypeError("SmartRecruiters job response is incomplete")
    output = [
        title.strip(),
        f"Location: {location['fullLocation'].strip()}",
        f"Employment type: {employment['label'].strip()}",
        "Workplace type: hybrid" if location.get("hybrid") is True else "",
    ]
    for section in sections.values():
        if not isinstance(section, dict):
            raise TypeError("SmartRecruiters section must be an object")
        heading = section.get("title")
        content = section.get("text")
        if not isinstance(heading, str) or not isinstance(content, str):
            raise TypeError("SmartRecruiters section is incomplete")
        output.extend((heading.strip(), _html_to_text(content)))
    return "\n\n".join(item for item in output if item).strip()


PARSERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "lever": _parse_lever,
    "greenhouse": _parse_greenhouse,
    "smartrecruiters": _parse_smartrecruiters,
}


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"selection already exists: {OUTPUT}")
    cases: list[dict[str, Any]] = []
    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "jobflow-agent-holdout-collector/1.0"},
    ) as client:
        for spec in CASE_SPECS:
            response = client.get(spec["retrieval_url"])
            value = _require_object(response, spec)
            if spec["parser"] == "smartrecruiters" and value.get("active") is not True:
                raise ValueError(f"inactive job: {spec['case_id']}")
            raw_content = PARSERS[spec["parser"]](value)
            normalized_content = _normalized_body(raw_content)
            public_fields = {
                key: spec[key]
                for key in (
                    "case_id",
                    "company",
                    "title",
                    "location",
                    "ats",
                    "source_url",
                    "retrieval_url",
                )
            }
            cases.append(
                {
                    **public_fields,
                    "source_content_sha256": _sha256_text(raw_content),
                    "normalized_content_sha256": _sha256_text(normalized_content),
                    "character_count": len(raw_content),
                    "raw_content": raw_content,
                }
            )

    selection = {
        "selection_version": (
            "unified-jd-flat-atomic-v4.3-independent-holdout-selection-v1"
        ),
        "collected_at": datetime.now(UTC).isoformat(),
        "status": "selected_before_preregistration_and_model_calls",
        "objective": (
            "Provide a genuinely new five-job public holdout for one-time "
            "generalization testing of the frozen v4.3 compatibility layer."
        ),
        "independence_scope": (
            "Collected after the v4.3 source and formal development gates were "
            "frozen. Selection used only public source availability, ATS/surface "
            "diversity, geography, seniority, and domain coverage; no labels, "
            "predictions, or model responses were available or used."
        ),
        "collection_protocol": {
            "source_type": "public employer job detail pages and public ATS APIs",
            "discovery_method": "browser search and rendered-page inspection",
            "retrieval_method": "one public read-only API GET per selected job",
            "retrieval_request_count": len(CASE_SPECS),
            "ats_or_delivery_surfaces": [
                "Lever",
                "Greenhouse",
                "Greenhouse-backed employer page",
                "SmartRecruiters",
            ],
            "body_boundary": (
                "Retain title, location/employment metadata, company description, "
                "role description, responsibilities, qualifications, benefits, "
                "compensation, employer-authored equal-opportunity text, and source "
                "safety notices. Exclude cookie banners, navigation, apply buttons/"
                "forms, job-alert forms, footers, and platform-generated boilerplate "
                "or disclosures outside the canonical ATS job-content fields."
            ),
            "labels_used_for_selection": False,
            "prior_model_outputs_used_for_selection": False,
            "full_clean_body_preserved": True,
            "external_model_transmission_performed": False,
        },
        "selected_case_count": len(cases),
        "selected_case_ids": [case["case_id"] for case in cases],
        "cases": cases,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(selection, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "path": OUTPUT.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                "case_count": len(cases),
                "character_counts": {
                    case["case_id"]: case["character_count"] for case in cases
                },
                "model_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

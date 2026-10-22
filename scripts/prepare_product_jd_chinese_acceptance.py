"""Freeze source-reviewed education probes before live Chinese-JD parsing."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from scripts.collect_product_jd_chinese import chinese_requirements
from scripts.collect_product_jd_unseen import requirement_fingerprint
from scripts.run_product_jd_unseen_acceptance import write
from src.domain.eligibility import CandidateProfileInput

# These annotations were chosen from the source requirements, not model outputs.
MASTER_MINIMUM = {
    "zh-minimax-03",
    "zh-xiaomi-01",
    "zh-xiaomi-03",
    "zh-xiaomi-06",
    "zh-xiaomi-07",
    "zh-nio-01",
    "zh-nio-04",
    "zh-nio-05",
}
OPEN_MAJOR = "zh-bytedance-05"
CONFLICTING_COHORT = "zh-minimax-01"
LEVEL_LABELS = {
    "associate": "专科",
    "bachelor": "本科",
    "master": "硕士",
    "doctor": "博士",
}
LANGUAGE_PROBES = {
    "zh-bytedance-02": ("掌握Golang/Java/C++/Python中任意一门语言", ["Java", "Python"]),
    "zh-bytedance-03": ("熟练C/C++或Python", ["C++", "Python"]),
    "zh-bytedance-07": ("熟练掌握C/C++或Python编程语言", ["C++", "Python"]),
    "zh-bytedance-08": ("熟练C/C++或Python", ["C++", "Python"]),
    "zh-minimax-03": ("熟练掌握 C/C++、Rust 或 Go", ["Rust", "Go"]),
    "zh-minimax-05": ("熟练掌握 Go / Python / C++ 中至少一门语言", ["Go", "Python"]),
    "zh-minimax-06": ("熟练掌握 Go 或 Python", ["Go", "Python"]),
    "zh-minimax-07": ("熟练掌握 Go 或 Python", ["Go", "Python"]),
    "zh-xiaomi-01": ("熟练掌握Python或C++等至少一门编程语言", ["Python", "C++"]),
    "zh-xiaomi-03": ("熟练掌握Python/C++等主流语言一种或多种", ["Python", "C++"]),
    "zh-nio-02": ("至少熟练掌握一门主流编程语言（C / C++ 等）", ["C", "C++"]),
    "zh-nio-03": ("至少熟练掌握一门主流编程语言（C / C++ 等）", ["C", "C++"]),
    "zh-nio-07": (
        "至少熟练掌握一门主流编程语言（Python / C++ / Java 等）",
        ["Python", "Java"],
    ),
}


def record(level, major, year, *, graduated=False):
    status = "graduated" if graduated else "enrolled"
    date = f"已毕业于{year}年" if graduated else f"预计{year}年毕业"
    return {
        "level": level,
        "major_raw": major,
        "graduation_year": year,
        "graduation_source_text": date,
        "graduation_year_kind": "actual" if graduated else "expected",
        "graduation_year_confirmed": True,
        "status": status,
        "reviewed": True,
        "source": "evaluation_synthetic",
        "source_text": f"{LEVEL_LABELS[level]}，{major}专业，{date}，{'已毕业' if graduated else '在读'}",
    }


def candidate(level, major="计算机", year=2027, *, complete=True, graduated=False):
    records = [record(level, major, year, graduated=graduated)]
    if level in {"master", "doctor"}:
        records.insert(
            0,
            record(
                "bachelor",
                "计算机",
                2023 if level == "doctor" else 2025,
                graduated=True,
            ),
        )
    if level == "doctor":
        records.insert(1, record("master", "计算机", 2025, graduated=True))
    return CandidateProfileInput(
        graduation_year=year, educations=records, education_history_complete=complete
    ).model_dump(mode="json")


def labels_for(case):
    case_id = case["id"]
    body = case["raw_content"].split("任职要求：", 1)[-1]
    gate = next(
        line.strip()
        for line in body.splitlines()
        if re.search(r"本科|硕士|学历不限", line)
    )
    minimum = "master" if case_id in MASTER_MINIMUM else "bachelor"
    if case_id != CONFLICTING_COHORT:
        assert LEVEL_LABELS[minimum] in gate and "以上" in gate
    else:
        assert "学历不限" in gate and "在读" in gate
    open_scope = case_id == OPEN_MAJOR
    education = "unknown" if open_scope else "pass"
    eligibility = "unknown" if open_scope or case_id == CONFLICTING_COHORT else "pass"
    major = "政治学" if open_scope else "计算机"
    year = 2028 if case_id == CONFLICTING_COHORT else 2027
    checks = [
        {
            "id": "positive_minimum" if not open_scope else "open_major_minimum",
            "profile": candidate(minimum, major, year),
            "education": education,
            "eligibility": eligibility,
        },
        {
            "id": "positive_higher" if not open_scope else "open_major_higher",
            "profile": candidate(
                "doctor" if minimum == "master" else "master", major, year
            ),
            "education": education,
            "eligibility": eligibility,
        },
        {
            "id": "missing_history",
            "profile": {},
            "education": "unknown",
            "eligibility": "unknown",
        },
    ]
    if case_id == CONFLICTING_COHORT:
        checks.append(
            {
                "id": "not_enrolled",
                "profile": candidate("bachelor", year=2025, graduated=True),
                "education": "fail",
                "eligibility": "fail",
            }
        )
    else:
        checks.extend(
            [
                {
                    "id": "below_degree",
                    "profile": candidate(
                        "bachelor" if minimum == "master" else "associate"
                    ),
                    "education": "fail",
                    "eligibility": "fail",
                },
                {
                    "id": "incomplete_history",
                    "profile": candidate(
                        "bachelor" if minimum == "master" else "associate",
                        complete=False,
                    ),
                    "education": "unknown",
                    "eligibility": "unknown",
                },
                {
                    "id": "wrong_cohort",
                    "profile": candidate(minimum, major, year=2028),
                    "eligibility": "fail",
                },
            ]
        )
    # Wrong cohort is scored only as overall education/cohort qualification:
    # the implementation can enforce it as a global check or in an education branch.
    # A later project/research preference must not soften the major requirement.
    if re.search(r"专业(?:的|背景)?(?:者)?优先", gate) and not open_scope:
        checks.append(
            {
                "id": "positive_other_major",
                "profile": candidate(minimum, "金融"),
                "education": "pass",
                "eligibility": "pass",
            }
        )
    probes = []
    if case_id in LANGUAGE_PROBES:
        quote, options = LANGUAGE_PROBES[case_id]
        assert quote in body
        probes.append(
            {
                "source_text": quote,
                "relation": "any_of",
                "level": "required",
                "options": options,
            }
        )
    if case_id == "zh-minimax-04":
        for quote in ("精通 C/C++", "熟练掌握 Python"):
            assert quote in body
            probes.append(
                {
                    "source_text": quote,
                    "relation": "all_of",
                    "level": "required",
                    "options": [],
                }
            )
    return (
        checks,
        probes,
        {
            "education_gate_quote": gate,
            "cohort_quote": case["raw_content"].splitlines()[0],
            "minimum_degree": "any" if case_id == CONFLICTING_COHORT else minimum,
            "rationale": (
                "开放学科类别超出当前有界专业政策，保持待确认；学历不足仍可排除。"
                if open_scope
                else "官方项目标2027、标题标2028实习，教育可满足但整体届别待确认；在读是明确硬条件。"
                if case_id == CONFLICTING_COHORT
                else "最低学历和对应专业来自任职要求；专业优先不设硬门槛。2027届项目约束申请用学历，历史学历不能替代。"
            ),
        },
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source_dir", type=Path)
    cli.add_argument("--output-dir", type=Path, required=True)
    args = cli.parse_args()
    if args.output_dir.exists():
        cli.error("Preserve previous frozen input")
    source_path = args.source_dir / "sources.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    grouped = defaultdict(list)
    for case in source["cases"]:
        grouped[case["company_id"]].append(case)
    selected = []
    while len(selected) < 30 and any(grouped.values()):
        for company in ("bytedance", "minimax", "xiaomi", "nio"):
            if grouped[company] and len(selected) < 30:
                selected.append(grouped[company].pop(0))
    if len(selected) != 30 or len({c["company_id"] for c in selected}) < 3:
        cli.error("Require 30 cases and at least three employers")
    fingerprints = [requirement_fingerprint(c["raw_content"]) for c in selected]
    assert len(set(fingerprints)) == len(selected)
    assert all(chinese_requirements(c["raw_content"]) for c in selected)
    cases = []
    for case in selected:
        checks, probes, reference = labels_for(case)
        for label in checks:
            CandidateProfileInput.model_validate(label["profile"])
        cases.append(
            {
                **case,
                "qualification_labels": checks,
                "relation_probes": probes,
                "reference": reference,
            }
        )
    counts = {
        field: dict(
            Counter(
                label[field]
                for c in cases
                for label in c["qualification_labels"]
                if field in label
            )
        )
        for field in ("education", "eligibility")
    }
    limitations = [
        "30 Chinese JDs from four employers, quotas 8/8/7/7; convenience sample of technical campus roles, not a random holdout.",
        "Assistant-reviewed source annotations frozen before model calls; no independent human review. Candidate profiles are synthetic, not real applicants.",
        "Qualification labels cover education, major, study status and cohort only; no claim of full skill suitability or employer acceptance.",
        "Open major categories and conflicting project/title cohorts retain unknown under the existing conservative policy.",
        "Wrong-cohort cases score overall qualification only because the cohort can be enforced globally or inside an education branch.",
        "Selected relation probes are not full-JD semantic F1; candidate item granularity and open examples can affect agreement.",
    ]
    args.output_dir.mkdir(parents=True)
    write(
        args.output_dir / "sources.json",
        {
            "source_file": source_path.as_posix(),
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "selected_ids": [c["id"] for c in cases],
            "company_counts": dict(Counter(c["company_id"] for c in cases)),
            "cases": [
                {
                    k: v
                    for k, v in c.items()
                    if k not in {"qualification_labels", "relation_probes", "reference"}
                }
                for c in cases
            ],
        },
    )
    write(
        args.output_dir / "labels.json",
        {
            "label_origin": "assistant_source_review_before_calls",
            "counts": counts,
            "limitations": limitations,
            "cases": cases,
        },
    )
    print(
        json.dumps(
            {
                "cases": len(cases),
                "label_counts": counts,
                "probes": sum(len(c["relation_probes"]) for c in cases),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

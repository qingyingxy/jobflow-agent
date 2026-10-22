from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from pathlib import Path

from src.evaluation.unified_models import (
    UnifiedEvaluationCase,
    UnifiedEvaluationManifest,
)

DEFAULT_DRAFT = Path(
    "artifacts/evaluation/unified-jd-dev50-draft-v1-2026-09-03.json"
)
DEFAULT_OUTPUT = Path("docs/UNIFIED_JD_DEV50_HUMAN_REVIEW_CHECKLIST_V1.md")
HIGH_PRIORITY_MARKERS = (
    "冲突",
    "必须人工",
    "需人工",
    "近似",
    "无法结构化",
    "作用域",
    "开放年份",
    "当前契约",
)
MEDIUM_PRIORITY_TAGS = {
    "mixed_strength",
    "fact_preferred",
    "any_of",
    "open_group",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _markdown_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def review_priority(case: UnifiedEvaluationCase) -> str:
    notes = " ".join(case.review_notes)
    if any(marker in notes for marker in HIGH_PRIORITY_MARKERS):
        return "high"
    if set(case.coverage_tags) & MEDIUM_PRIORITY_TAGS:
        return "medium"
    return "routine"


def render_review_checklist(
    manifest: UnifiedEvaluationManifest,
    *,
    source_path: str,
    source_sha256: str,
) -> str:
    if manifest.label_status != "draft":
        raise ValueError("人工复核清单只能从 draft manifest 生成")
    if any(case.annotation_status != "draft" for case in manifest.cases):
        raise ValueError("人工复核清单只能包含 draft case")

    grouped: dict[str, list[UnifiedEvaluationCase]] = {
        "high": [],
        "medium": [],
        "routine": [],
    }
    for case in manifest.cases:
        if case.expected is None:
            raise ValueError(f"draft case 缺少 expected: {case.id}")
        grouped[review_priority(case)].append(case)

    lines = [
        "# Unified JD dev-50 人工复核清单 v1",
        "",
        "- [ ] 第一轮人工逐条复核完成",
        "- [ ] 所有修改已写入新的 reviewed 标签版本",
        "- [ ] 第二轮独立复核完成",
        "- [ ] 冻结版本及哈希已生成",
        "",
        f"> 草稿来源：`{source_path}`  ",
        f"> 草稿 SHA-256：`{source_sha256}`  ",
        (
            "> 本清单只记录复核进度。勾选清单本身不会把 draft 自动升级为 "
            "human_reviewed。"
        ),
        "",
        (
            "每个岗位必须同时确认 facts、强度、逻辑组、经验限定和逐字证据。"
            "修改时新建标签版本，不覆盖原 draft。"
        ),
        "",
    ]

    section_titles = {
        "high": "高优先级：已知争议",
        "medium": "中优先级：复杂语义",
        "routine": "常规复核",
    }
    fact_fields = (
        "job_type",
        "locations",
        "graduation_years",
        "education_requirements",
        "major_requirements",
        "internship_duration_months",
        "weekly_days",
        "earliest_start_date",
        "deadline",
    )
    for priority in ("high", "medium", "routine"):
        cases = grouped[priority]
        lines.extend([f"## {section_titles[priority]}（{len(cases)}）", ""])
        if not cases:
            lines.extend(["无。", ""])
            continue
        for case in cases:
            expected = case.expected
            populated_facts = [
                field for field in fact_fields if getattr(expected.facts, field) is not None
            ]
            levels = Counter(clause.level for clause in expected.clauses)
            notes = "；".join(case.review_notes) if case.review_notes else "无"
            lines.extend(
                [
                    (
                        f"### [ ] `{case.id}` "
                        f"{_markdown_text(case.source.company)} - "
                        f"{_markdown_text(case.source.title)}"
                    ),
                    "",
                    f"- 官方岗位：[打开原文]({case.source.source_url})",
                    f"- 非空 facts：`{', '.join(populated_facts)}`",
                    (
                        "- clauses："
                        f"`required={levels['required']}`、"
                        f"`preferred={levels['preferred']}`、"
                        f"`mention={levels['mention']}`"
                    ),
                    f"- 已知问题：{_markdown_text(notes)}",
                    "- [ ] 九个 facts 的值、空值和事实强度正确",
                    "- [ ] required / preferred / mention 没有混淆",
                    "- [ ] all_of / any_of / allow_other 的作用域正确",
                    "- [ ] experience qualifier 没有错误传播或丢失",
                    "- [ ] 每段 source_text 连续、逐字一致且足以支持结论",
                    "- 复核结论：`保持 / 修改 / 待讨论`",
                    "- 修改或讨论说明：",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def write_review_checklist(*, draft_path: Path, output_path: Path) -> str:
    manifest = UnifiedEvaluationManifest.model_validate_json(
        draft_path.read_text(encoding="utf-8")
    )
    rendered = render_review_checklist(
        manifest,
        source_path=draft_path.as_posix(),
        source_sha256=_sha256(draft_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite changed file: {output_path}")
    output_path.write_text(rendered, encoding="utf-8")
    return rendered


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Unified dev-50 human review checklist"
    )
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    rendered = write_review_checklist(
        draft_path=arguments.draft,
        output_path=arguments.output,
    )
    print(
        "unified dev-50 review checklist built "
        f"cases={rendered.count('### [ ] `')} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

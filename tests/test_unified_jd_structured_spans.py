from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.domain.unified_jd_structured_spans import (
    ParsedClause,
    SourceSpan,
    extract_surface_items,
    parse_clause,
    project_surface_items,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_FIXTURES = (
    PROJECT_ROOT / "datasets" / "unified_jd_canonical_items_contract_v1.json",
    PROJECT_ROOT / "datasets" / "unified_jd_surface_holdout_labels_v1_2026-09-04.json",
    PROJECT_ROOT / "datasets" / "unified_jd_surface_holdout_labels_v2_2026-09-04.json",
)


def _development_items() -> list[dict[str, Any]]:
    return [
        item
        for path in DEVELOPMENT_FIXTURES
        for item in json.loads(path.read_text(encoding="utf-8"))["fixtures"]
    ]


@pytest.mark.parametrize("item", _development_items(), ids=lambda item: item["id"])
def test_v3_projection_fits_sixty_revealed_development_fixtures(
    item: dict[str, Any],
) -> None:
    extraction = extract_surface_items(item["source_text"], item["category"])

    assert list(extraction.items) == item["surface_items"]
    assert list(extraction.examples) == (item["examples"] or [])
    assert extraction.rule_ids


@pytest.mark.parametrize("item", _development_items(), ids=lambda item: item["id"])
def test_every_v3_structure_span_is_source_anchored(item: dict[str, Any]) -> None:
    parsed = parse_clause(item["source_text"], item["category"])

    # Re-instantiation runs the aggregate invariant checks in __post_init__.
    ParsedClause(
        **{name: getattr(parsed, name) for name in parsed.__dataclass_fields__}
    )


def test_participation_is_a_wrapper_not_a_character_coordination() -> None:
    parsed = parse_clause("参与模型调用、运行追踪和成本分析", "responsibility")
    extraction = project_surface_items(parsed)

    assert extraction.items == ("模型调用", "运行追踪", "成本分析")
    assert "参" not in extraction.items
    assert any(wrapper.marker_span.text == "参与" for wrapper in parsed.wrappers)
    assert [span.text for span in parsed.coordinations[0].connector_spans] == [
        "、",
        "和",
    ]


def test_slash_scanner_distinguishes_ab_from_technology_alternatives() -> None:
    parsed = parse_clause(
        "通过快速原型、A/B 实验和数据分析，熟练掌握CUDA/triton",
        "skill",
    )

    members = {
        member.span.text for group in parsed.coordinations for member in group.members
    }
    assert "A/B 实验" in members
    assert "A" not in members
    assert "B 实验" not in members
    assert {"CUDA", "triton"} <= {
        member.span.text for group in parsed.coordinations for member in group.members
    }


def test_shared_suffix_references_all_coordination_members() -> None:
    parsed = parse_clause("具备需求分析、逻辑拆解与文档撰写能力", "capability")
    group = parsed.coordinations[0]
    scope = parsed.shared_scopes[0]

    assert scope.span.text == "能力"
    assert scope.kind == "suffix"
    assert scope.applies_to_member_ids == tuple(member.id for member in group.members)


def test_examples_attach_inside_their_own_segment() -> None:
    parsed = parse_clause(
        "有完整具身 Agent 项目经验，或参与过 LeRobot、GR00T 等开源项目",
        "experience",
    )
    attachment = parsed.example_attachments[0]

    assert attachment.parent_span.text == "开源项目"
    assert [span.text for span in attachment.example_spans] == ["LeRobot", "GR00T"]
    assert attachment.segment_index == 1
    assert all(
        parsed.segments[1].start <= span.start < span.end <= parsed.segments[1].end
        for span in attachment.example_spans
    )


def test_projection_does_not_reparse_source_text() -> None:
    parsed = parse_clause("具备团队合作和沟通能力", "capability")
    altered = ParsedClause(
        source_text=parsed.source_text,
        category=parsed.category,
        protected_spans=parsed.protected_spans,
        segments=parsed.segments,
        wrappers=parsed.wrappers,
        coordinations=(),
        shared_scopes=(),
        example_attachments=parsed.example_attachments,
        item_candidates=(parsed.item_candidates[1],),
        rule_ids=parsed.rule_ids,
    )

    assert project_surface_items(altered).items == ("沟通",)


def test_source_span_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="invalid source span"):
        SourceSpan.from_bounds("abc", 1, 1)


def test_v3_rejects_empty_source() -> None:
    with pytest.raises(ValueError, match="source_text"):
        parse_clause(" ", "skill")

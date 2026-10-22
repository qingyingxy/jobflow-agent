from __future__ import annotations

from dataclasses import replace

import pytest

from src.domain.unified_jd_structured_spans_v5 import (
    _attachment_signature,
    extract_surface_items,
)


def test_v5_explicit_example_cue_does_not_absorb_following_space() -> None:
    extraction = extract_surface_items("掌握基础框架，如 检索系统、排序系统", "skill")

    attachment = extraction.parsed_clause.example_attachments[0]
    assert attachment.cue_span.text == "如"
    assert attachment.parent_span.text == "基础框架"
    assert [span.text for span in attachment.example_spans] == [
        "检索系统",
        "排序系统",
    ]


@pytest.mark.parametrize(
    "category", ("responsibility", "skill", "experience", "capability")
)
def test_v5_terminal_priority_tail_is_a_category_neutral_open_list(
    category: str,
) -> None:
    extraction = extract_surface_items(
        "具备以下能力者优先：方案甲/方案乙/方案丙等优先", category
    )

    assert extraction.items == ("方案甲", "方案乙", "方案丙")
    assert extraction.examples == ()
    assert extraction.parsed_clause.example_attachments == ()
    assert any(
        wrapper.kind == "open_list_suffix" and wrapper.marker_span.text == "等"
        for wrapper in extraction.parsed_clause.wrappers
    )


def test_v5_prepositional_boundary_is_removed_before_example_split() -> None:
    extraction = extract_surface_items(
        "熟悉基础工具，对面对客户、支持团队等领域有深入了解", "skill"
    )

    attachment = extraction.parsed_clause.example_attachments[0]
    assert attachment.parent_span.text == "领域"
    assert [span.text for span in attachment.example_spans] == [
        "面对客户",
        "支持团队",
    ]
    assert all(not span.text.startswith("对面对") for span in attachment.example_spans)


def test_v5_attachment_signature_includes_parent_end_boundary() -> None:
    parsed = extract_surface_items(
        "掌握基础框架，如检索系统、排序系统", "skill"
    ).parsed_clause
    attachment = parsed.example_attachments[0]
    shorter_parent = replace(
        attachment,
        parent_span=replace(
            attachment.parent_span,
            text=attachment.parent_span.text[:-1],
            end=attachment.parent_span.end - 1,
        ),
    )
    changed = replace(parsed, example_attachments=(shorter_parent,))

    assert _attachment_signature(parsed) != _attachment_signature(changed)

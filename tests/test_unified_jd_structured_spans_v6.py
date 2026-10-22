from __future__ import annotations

from src.domain import unified_jd_structured_spans_v4 as v4
from src.domain import unified_jd_structured_spans_v5 as v5
from src.domain import unified_jd_structured_spans_v6 as v6


def _wrapper_keys(parsed: v4.ParsedClause) -> set[tuple[object, ...]]:
    return {
        (
            item.kind,
            item.marker_span.start,
            item.marker_span.end,
            item.content_span.start,
            item.content_span.end,
        )
        for item in parsed.wrappers
    }


def _attachment_keys(parsed: v4.ParsedClause) -> set[tuple[object, ...]]:
    return {
        (
            item.cue_span.start,
            item.parent_span.start,
            item.parent_span.end,
            tuple((span.start, span.end) for span in item.example_spans),
        )
        for item in parsed.example_attachments
    }


def test_v6_keeps_v4_for_ambiguous_no_cue_deng_enumeration() -> None:
    source = "熟悉至少一种组件（Alpha/Beta/Gamma等）"

    base = v4.extract_surface_items(source, "skill")
    fresh = v5.extract_surface_items(source, "skill")
    merged = v6.extract_surface_items(source, "skill")

    assert merged.items == base.items
    assert merged.examples == base.examples
    assert (merged.items, merged.examples) != (fresh.items, fresh.examples)


def test_v6_preserves_singleton_parenthetical_attachment() -> None:
    source = "设计数据框架（FrameX）或规则引擎的解决方案"

    base = v4.extract_surface_items(source, "responsibility")
    fresh = v5.extract_surface_items(source, "responsibility")
    merged = v6.extract_surface_items(source, "responsibility")

    assert base.parsed_clause.example_attachments
    assert not fresh.parsed_clause.example_attachments
    assert _attachment_keys(merged.parsed_clause) == _attachment_keys(
        base.parsed_clause
    )
    assert merged.items == base.items
    assert merged.examples == base.examples


def test_v6_preserves_explicit_ru_colon_attachment_unit() -> None:
    source = "掌握一种分析语言，如：LangA、LangB、LangC"

    base = v4.extract_surface_items(source, "skill")
    merged = v6.extract_surface_items(source, "skill")

    assert merged.items == base.items
    assert merged.examples == base.examples
    assert _attachment_keys(merged.parsed_clause) == _attachment_keys(
        base.parsed_clause
    )


def test_v6_activates_deictic_header_direct_open_list() -> None:
    source = "具备以下工具经验：ToolA/ToolB/ToolC等优先"

    fresh = v5.extract_surface_items(source, "skill")
    merged = v6.extract_surface_items(source, "skill")

    assert merged.items == fresh.items
    assert merged.examples == fresh.examples
    assert _wrapper_keys(merged.parsed_clause) == _wrapper_keys(fresh.parsed_clause)


def test_v6_plain_priority_list_keeps_v4_wrappers_but_v5_projection() -> None:
    source = "具备基础能力，熟悉ToolA、ToolB、ToolC等优先"

    base = v4.extract_surface_items(source, "skill")
    fresh = v5.extract_surface_items(source, "skill")
    merged = v6.extract_surface_items(source, "skill")

    assert _wrapper_keys(merged.parsed_clause) == _wrapper_keys(base.parsed_clause)
    assert merged.items[0] == base.items[0]
    assert merged.items[1:] == fresh.items[1:]
    assert merged.examples == ()


def test_v6_merges_regions_without_whole_clause_dispatch() -> None:
    source = (
        "掌握以下组件：ModuleA/ModuleB/ModuleC等优先，熟悉语言甲、语言乙、语言丙等概念"
    )

    base = v4.extract_surface_items(source, "skill")
    fresh = v5.extract_surface_items(source, "skill")
    merged = v6.extract_surface_items(source, "skill")

    assert merged.items != base.items
    assert merged.items != fresh.items
    assert {"ModuleA", "ModuleB", "ModuleC"} <= set(merged.items)
    assert {"语言甲", "语言乙", "语言丙"} <= set(merged.items)
    assert "概念" not in merged.items
    assert merged.examples == ()


def test_v6_rebuilds_unique_ids_and_valid_scope_references() -> None:
    parsed = v6.parse_clause(
        "具备以下工具经验：ToolA/ToolB/ToolC等优先，拥有分析与建模能力",
        "capability",
    )

    ids = [item.id for item in parsed.item_candidates]
    ids.extend(member.id for group in parsed.coordinations for member in group.members)
    known = set(ids)

    assert len(ids) == len(known)
    assert all(
        set(scope.applies_to_member_ids) <= known for scope in parsed.shared_scopes
    )
    v4.ParsedClause(
        **{name: getattr(parsed, name) for name in parsed.__dataclass_fields__}
    )

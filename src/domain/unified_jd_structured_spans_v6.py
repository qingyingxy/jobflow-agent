from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.domain import unified_jd_structured_spans_v4 as v4
from src.domain import unified_jd_structured_spans_v5 as v5

SurfaceCategory = v4.SurfaceCategory
SourceSpan = v4.SourceSpan
WrapperSpan = v4.WrapperSpan
CoordinationMember = v4.CoordinationMember
CoordinationGroup = v4.CoordinationGroup
SharedScope = v4.SharedScope
ExampleAttachment = v4.ExampleAttachment
ConnectorLabel = v4.ConnectorLabel
ParsedClause = v4.ParsedClause
StructuredSurfaceExtraction = v4.StructuredSurfaceExtraction

STRUCTURED_SPAN_PARSER_VERSION = "unified-jd-structured-span-parser-v6-development"

_Origin = Literal["v4", "v5"]
_BOUNDARIES = "，,；;：:"


@dataclass(frozen=True, slots=True)
class _Region:
    span: SourceSpan
    index: int


@dataclass(frozen=True, slots=True)
class _RegionDecision:
    origin: _Origin
    e6_direct_open_list: bool
    retain_v4_wrappers: bool


@dataclass(frozen=True, slots=True)
class _SelectedMember:
    origin: _Origin
    old_id: str
    value: CoordinationMember


def _inside(index: int, spans: tuple[SourceSpan, ...]) -> bool:
    return any(span.start < index < span.end - 1 for span in spans)


def _trim(source: str, start: int, end: int) -> SourceSpan | None:
    while start < end and (source[start].isspace() or source[start] in _BOUNDARIES):
        start += 1
    while start < end and (source[end - 1].isspace() or source[end - 1] in _BOUNDARIES):
        end -= 1
    return SourceSpan.from_bounds(source, start, end) if start < end else None


def _regions(source: str, protected: tuple[SourceSpan, ...]) -> tuple[_Region, ...]:
    spans: list[SourceSpan] = []
    start = 0
    for index, character in enumerate(source):
        if character not in _BOUNDARIES or _inside(index, protected):
            continue
        region = _trim(source, start, index)
        if region is not None:
            spans.append(region)
        start = index + 1
    final = _trim(source, start, len(source))
    if final is not None:
        spans.append(final)
    return tuple(_Region(span, index) for index, span in enumerate(spans))


def _contains(container: SourceSpan, value: SourceSpan) -> bool:
    return container.start <= value.start and value.end <= container.end


def _owner(regions: tuple[_Region, ...], spans: tuple[SourceSpan, ...]) -> int:
    for region in regions:
        if all(_contains(region.span, span) for span in spans):
            return region.index
    anchor = spans[0]
    for region in regions:
        if region.span.start <= anchor.start < region.span.end:
            return region.index
    raise ValueError(f"structural span has no top-level region: {anchor}")


def _wrapper_region(regions: tuple[_Region, ...], value: WrapperSpan) -> int:
    return _owner(regions, (value.marker_span, value.content_span))


def _group_region(regions: tuple[_Region, ...], value: CoordinationGroup) -> int:
    spans = (*value.connector_spans, *(member.span for member in value.members))
    return _owner(regions, spans)


def _scope_region(regions: tuple[_Region, ...], value: SharedScope) -> int:
    return _owner(regions, (value.span,))


def _attachment_region(regions: tuple[_Region, ...], value: ExampleAttachment) -> int:
    return _owner(regions, (value.cue_span,))


def _candidate_region(regions: tuple[_Region, ...], value: CoordinationMember) -> int:
    return _owner(regions, (value.span,))


def _label_region(regions: tuple[_Region, ...], value: ConnectorLabel) -> int:
    return _owner(regions, (value.span,))


def _member_spans(parsed: ParsedClause) -> dict[str, SourceSpan]:
    result = {item.id: item.span for item in parsed.item_candidates}
    for group in parsed.coordinations:
        result.update({item.id: item.span for item in group.members})
    return result


def _coordination_signature(value: CoordinationGroup) -> tuple[object, ...]:
    return (
        value.role,
        tuple((span.start, span.end) for span in value.connector_spans),
        tuple((member.span.start, member.span.end) for member in value.members),
    )


def _scope_signature(
    value: SharedScope, member_spans: dict[str, SourceSpan]
) -> tuple[object, ...]:
    return (
        value.kind,
        value.span.start,
        value.span.end,
        tuple(
            (member_spans[item_id].start, member_spans[item_id].end)
            for item_id in value.applies_to_member_ids
            if item_id in member_spans
        ),
    )


def _attachment_signature(value: ExampleAttachment) -> tuple[object, ...]:
    return (
        value.cue_span.start,
        value.cue_span.end,
        value.parent_span.start,
        value.parent_span.end,
        tuple((span.start, span.end) for span in value.example_spans),
    )


def _explicit_ru_regions(
    source: str,
    regions: tuple[_Region, ...],
    base: ParsedClause,
    fresh: ParsedClause,
) -> set[int]:
    result = {
        _attachment_region(regions, attachment)
        for parsed in (base, fresh)
        for attachment in parsed.example_attachments
        if attachment.cue_span.text.startswith("如")
    }
    for match in re.finditer(r"如\s*[：:]", source):
        cue = SourceSpan.from_bounds(source, match.start(), match.start() + 1)
        cue_region = _owner(regions, (cue,))
        result.add(cue_region)
        if cue_region + 1 < len(regions):
            between = source[
                regions[cue_region].span.end : regions[cue_region + 1].span.start
            ]
            if re.fullmatch(r"\s*[：:]\s*", between):
                result.add(cue_region + 1)
    return result


def _protected_attachment(
    attachment: ExampleAttachment, protected: tuple[SourceSpan, ...]
) -> SourceSpan | None:
    for enclosure in protected:
        if _contains(enclosure, attachment.cue_span) or (
            attachment.cue_span.start == enclosure.start
            and all(_contains(enclosure, span) for span in attachment.example_spans)
        ):
            return enclosure
    return None


def _source_covering_replacement(
    expected: ExampleAttachment,
    enclosure: SourceSpan,
    replacements: tuple[ExampleAttachment, ...],
) -> bool:
    expected_examples = {(span.start, span.end) for span in expected.example_spans}
    for replacement in replacements:
        replacement_examples = {
            (span.start, span.end) for span in replacement.example_spans
        }
        if not (
            _contains(enclosure, replacement.cue_span)
            or replacement.cue_span.start == enclosure.start
        ):
            continue
        if replacement.parent_span.start > expected.parent_span.start:
            continue
        if replacement.parent_span.end < expected.parent_span.end:
            continue
        if expected_examples <= replacement_examples:
            return True
    return False


def _explicit_attachment_mismatch_regions(
    regions: tuple[_Region, ...], base: ParsedClause, fresh: ParsedClause
) -> set[int]:
    fresh_signatures = {
        _attachment_signature(attachment)
        for attachment in fresh.example_attachments
        if attachment.cue_span.text.startswith("如")
    }
    result: set[int] = set()
    for attachment in base.example_attachments:
        if (
            not attachment.cue_span.text.startswith("如")
            or _attachment_signature(attachment) in fresh_signatures
        ):
            continue
        result.add(_attachment_region(regions, attachment))
        result.update(_owner(regions, (span,)) for span in attachment.example_spans)
    return result


def _e7_region(region: _Region) -> bool:
    return bool(
        re.match(r"对", region.span.text)
        and re.search(
            r"等(?:领域|方面)(?:\b|的|有|具备|进行|者|优先|，|,|$)", region.span.text
        )
    )


def _e6_regions(source: str, regions: tuple[_Region, ...]) -> set[int]:
    result: set[int] = set()
    for region in regions:
        if region.index == 0 or not re.search(r"等\s*优先$", region.span.text):
            continue
        header = regions[region.index - 1]
        between = source[header.span.end : region.span.start]
        if "以下" in header.span.text and re.fullmatch(r"\s*[：:]\s*", between):
            result.update((header.index, region.index))
    return result


def _structure_delta_spans(
    region: _Region, base: ParsedClause, fresh: ParsedClause
) -> tuple[SourceSpan, ...]:
    base_members = _member_spans(base)
    fresh_members = _member_spans(fresh)
    base_signatures: set[tuple[object, ...]] = {
        _coordination_signature(value) for value in base.coordinations
    }
    base_signatures.update(
        _scope_signature(value, base_members) for value in base.shared_scopes
    )
    base_signatures.update(
        _attachment_signature(value) for value in base.example_attachments
    )

    created_spans: list[SourceSpan] = []
    for group in fresh.coordinations:
        if _coordination_signature(group) in base_signatures:
            continue
        envelope = SourceSpan.from_bounds(
            fresh.source_text,
            min(member.span.start for member in group.members),
            max(member.span.end for member in group.members),
        )
        if _contains(region.span, envelope):
            created_spans.append(envelope)
    for scope in fresh.shared_scopes:
        if _scope_signature(scope, fresh_members) not in base_signatures and _contains(
            region.span, scope.span
        ):
            created_spans.append(scope.span)
    for attachment in fresh.example_attachments:
        if _attachment_signature(attachment) in base_signatures:
            continue
        if _contains(region.span, attachment.cue_span):
            starts = [
                attachment.cue_span.start,
                attachment.parent_span.start,
                *(span.start for span in attachment.example_spans),
            ]
            ends = [
                attachment.cue_span.end,
                attachment.parent_span.end,
                *(span.end for span in attachment.example_spans),
            ]
            created_spans.append(
                SourceSpan.from_bounds(fresh.source_text, min(starts), max(ends))
            )

    licensed: list[SourceSpan] = []
    for wrapper in fresh.wrappers:
        if not _contains(region.span, wrapper.content_span):
            continue
        if any(_contains(wrapper.content_span, span) for span in created_spans):
            licensed.append(wrapper.content_span)
    return tuple(licensed)


def _no_cue_surface_example_conflict(
    region: _Region,
    base: ParsedClause,
    fresh: ParsedClause,
    *,
    explicit_ru: bool,
    e6: bool,
    e7: bool,
) -> bool:
    if explicit_ru or e6 or e7 or "等" not in region.span.text:
        return False
    base_surface = {
        (item.span.start, item.span.end)
        for item in base.item_candidates
        if _contains(region.span, item.span)
    }
    fresh_surface = {
        (item.span.start, item.span.end)
        for item in fresh.item_candidates
        if _contains(region.span, item.span)
    }
    fresh_examples = {
        (span.start, span.end)
        for attachment in fresh.example_attachments
        if _contains(region.span, attachment.cue_span)
        for span in attachment.example_spans
    }
    return bool(
        len(fresh_examples) >= 2
        and fresh_examples <= base_surface
        and fresh_examples.isdisjoint(fresh_surface)
    )


def _has_incompatible_v4_projection(
    region: _Region,
    base: ParsedClause,
    fresh: ParsedClause,
    licensed_spans: tuple[SourceSpan, ...],
) -> bool:
    fresh_candidates = {
        (item.span.start, item.span.end)
        for item in fresh.item_candidates
        if _contains(region.span, item.span)
    }
    for candidate in base.item_candidates:
        if not _contains(region.span, candidate.span):
            continue
        bounds = (candidate.span.start, candidate.span.end)
        if bounds in fresh_candidates:
            continue
        if not any(_contains(span, candidate.span) for span in licensed_spans):
            return True
    return False


def _decisions(
    source: str,
    regions: tuple[_Region, ...],
    base: ParsedClause,
    fresh: ParsedClause,
) -> dict[int, _RegionDecision]:
    explicit_ru = _explicit_ru_regions(source, regions, base, fresh)
    explicit_mismatch = _explicit_attachment_mismatch_regions(regions, base, fresh)
    e6 = _e6_regions(source, regions)
    e7 = {region.index for region in regions if _e7_region(region)}
    protected = {
        _attachment_region(regions, attachment)
        for attachment in fresh.example_attachments
        if _protected_attachment(attachment, fresh.protected_spans) is not None
    }

    result: dict[int, _RegionDecision] = {}
    for region in regions:
        structure_spans = _structure_delta_spans(region, base, fresh)
        licensed_spans = list(structure_spans)
        if region.index in explicit_ru or region.index in e6 or region.index in e7:
            licensed_spans.append(region.span)
        for attachment in fresh.example_attachments:
            enclosure = _protected_attachment(attachment, fresh.protected_spans)
            if (
                enclosure is not None
                and _attachment_region(regions, attachment) == region.index
            ):
                licensed_spans.append(enclosure)

        licensed = bool(
            region.index in explicit_ru
            or region.index in protected
            or region.index in e6
            or region.index in e7
            or structure_spans
        )
        conflict = _no_cue_surface_example_conflict(
            region,
            base,
            fresh,
            explicit_ru=region.index in explicit_ru,
            e6=region.index in e6,
            e7=region.index in e7,
        )
        deleted_protected = any(
            _attachment_region(regions, attachment) == region.index
            and (enclosure := _protected_attachment(attachment, base.protected_spans))
            is not None
            and not _source_covering_replacement(
                attachment, enclosure, fresh.example_attachments
            )
            for attachment in base.example_attachments
        )
        incompatible = _has_incompatible_v4_projection(
            region, base, fresh, tuple(licensed_spans)
        )
        use_v5 = bool(
            licensed
            and region.index not in explicit_mismatch
            and not conflict
            and not deleted_protected
            and not incompatible
        )
        plain_open_list = bool(
            re.search(r"等\s*优先$", region.span.text) and region.index not in e6
        )
        result[region.index] = _RegionDecision(
            origin="v5" if use_v5 else "v4",
            e6_direct_open_list=region.index in e6,
            retain_v4_wrappers=plain_open_list,
        )
    return result


def _select_by_region(
    regions: tuple[_Region, ...],
    decisions: dict[int, _RegionDecision],
    base_values: tuple[object, ...],
    fresh_values: tuple[object, ...],
    owner: object,
) -> list[tuple[_Origin, object]]:
    result: list[tuple[_Origin, object]] = []
    for region in regions:
        origin = decisions[region.index].origin
        values = fresh_values if origin == "v5" else base_values
        for value in values:
            if owner(regions, value) == region.index:  # type: ignore[operator]
                result.append((origin, value))
    return result


def _rebuild(
    source: str,
    category: SurfaceCategory,
    regions: tuple[_Region, ...],
    decisions: dict[int, _RegionDecision],
    base: ParsedClause,
    fresh: ParsedClause,
) -> ParsedClause:
    wrappers: list[WrapperSpan] = []
    for region in regions:
        decision = decisions[region.index]
        origin: _Origin = "v4" if decision.retain_v4_wrappers else decision.origin
        parsed = fresh if origin == "v5" else base
        wrappers.extend(
            value
            for value in parsed.wrappers
            if _wrapper_region(regions, value) == region.index
        )

    selected_groups = _select_by_region(
        regions,
        decisions,
        base.coordinations,
        fresh.coordinations,
        _group_region,
    )
    selected_candidates = _select_by_region(
        regions,
        decisions,
        base.item_candidates,
        fresh.item_candidates,
        _candidate_region,
    )
    selected_scopes = _select_by_region(
        regions,
        decisions,
        base.shared_scopes,
        fresh.shared_scopes,
        _scope_region,
    )
    selected_attachments = _select_by_region(
        regions,
        decisions,
        base.example_attachments,
        fresh.example_attachments,
        _attachment_region,
    )
    selected_labels = _select_by_region(
        regions,
        decisions,
        base.connector_labels,
        fresh.connector_labels,
        _label_region,
    )

    next_id = 1

    def new_id(prefix: str) -> str:
        nonlocal next_id
        result = f"{prefix}-{next_id}"
        next_id += 1
        return result

    id_map: dict[tuple[_Origin, str], str] = {}
    span_to_ids: dict[tuple[int, int], list[str]] = {}
    coordinations: list[CoordinationGroup] = []
    for origin, raw_group in selected_groups:
        group = raw_group
        assert isinstance(group, CoordinationGroup)
        members: list[CoordinationMember] = []
        for member in group.members:
            rebuilt = CoordinationMember(
                new_id("member"),
                member.span,
                _owner(regions, (member.span,)),
            )
            id_map[(origin, member.id)] = rebuilt.id
            span_to_ids.setdefault((rebuilt.span.start, rebuilt.span.end), []).append(
                rebuilt.id
            )
            members.append(rebuilt)
        coordinations.append(
            CoordinationGroup(
                new_id("coord"),
                group.role,
                group.kind,
                group.connector_spans,
                tuple(members),
            )
        )

    candidates: list[CoordinationMember] = []
    for origin, raw_candidate in selected_candidates:
        candidate = raw_candidate
        assert isinstance(candidate, CoordinationMember)
        rebuilt = CoordinationMember(
            new_id("candidate"),
            candidate.span,
            _owner(regions, (candidate.span,)),
        )
        id_map[(origin, candidate.id)] = rebuilt.id
        span_to_ids.setdefault((rebuilt.span.start, rebuilt.span.end), []).append(
            rebuilt.id
        )
        candidates.append(rebuilt)

    source_member_spans = {"v4": _member_spans(base), "v5": _member_spans(fresh)}
    scopes: list[SharedScope] = []
    for origin, raw_scope in selected_scopes:
        scope = raw_scope
        assert isinstance(scope, SharedScope)
        references: list[str] = []
        for old_id in scope.applies_to_member_ids:
            replacement = id_map.get((origin, old_id))
            if replacement is None and old_id in source_member_spans[origin]:
                span = source_member_spans[origin][old_id]
                available = span_to_ids.get((span.start, span.end), [])
                replacement = available[0] if available else None
            if replacement is not None and replacement not in references:
                references.append(replacement)
        if references:
            scopes.append(
                SharedScope(
                    new_id("scope"),
                    scope.kind,
                    scope.span,
                    tuple(references),
                )
            )

    attachments: list[ExampleAttachment] = []
    for _, raw_attachment in selected_attachments:
        attachment = raw_attachment
        assert isinstance(attachment, ExampleAttachment)
        attachments.append(
            ExampleAttachment(
                new_id("example"),
                attachment.cue_span,
                attachment.parent_span,
                attachment.example_spans,
                _owner(regions, (attachment.cue_span,)),
            )
        )

    labels: dict[tuple[int, int], ConnectorLabel] = {}
    for _, raw_label in selected_labels:
        label = raw_label
        assert isinstance(label, ConnectorLabel)
        labels[(label.span.start, label.span.end)] = label
    for group in coordinations:
        for connector in group.connector_spans:
            labels[(connector.start, connector.end)] = ConnectorLabel(
                connector, group.role
            )

    adopted = tuple(
        region.index for region in regions if decisions[region.index].origin == "v5"
    )
    rules = (
        "v6.dual_frozen_parse",
        "v6.exact_region_alignment",
        "v6.supported_delta_compatibility",
        f"v6.adopted_regions:{','.join(map(str, adopted))}",
        "v6.graph_projection",
    )
    return ParsedClause(
        source_text=source,
        category=category,
        protected_spans=base.protected_spans,
        segments=tuple(region.span for region in regions),
        wrappers=tuple(
            sorted(
                set(wrappers),
                key=lambda item: (
                    item.marker_span.start,
                    item.marker_span.end,
                    item.content_span.start,
                    item.kind,
                ),
            )
        ),
        connector_labels=tuple(labels[key] for key in sorted(labels)),
        coordinations=tuple(coordinations),
        shared_scopes=tuple(scopes),
        example_attachments=tuple(
            sorted(attachments, key=lambda item: (item.cue_span.start, item.id))
        ),
        item_candidates=tuple(
            sorted(
                candidates,
                key=lambda item: (item.span.start, item.span.end, item.id),
            )
        ),
        rule_ids=rules,
    )


def parse_clause(source_text: str, category: SurfaceCategory) -> ParsedClause:
    if not source_text.strip():
        raise ValueError("source_text must not be empty")
    base = v4.parse_clause(source_text, category)
    fresh = v5.parse_clause(source_text, category)
    regions = _regions(source_text, base.protected_spans)
    decisions = _decisions(source_text, regions, base, fresh)
    return _rebuild(source_text, category, regions, decisions, base, fresh)


def project_surface_items(parsed_clause: ParsedClause) -> StructuredSurfaceExtraction:
    projected = v4.project_surface_items(parsed_clause)
    return StructuredSurfaceExtraction(
        category=projected.category,
        source_text=projected.source_text,
        items=projected.items,
        examples=projected.examples,
        rule_ids=parsed_clause.rule_ids,
        parsed_clause=parsed_clause,
    )


def extract_surface_items(
    source_text: str, category: SurfaceCategory
) -> StructuredSurfaceExtraction:
    return project_surface_items(parse_clause(source_text, category))

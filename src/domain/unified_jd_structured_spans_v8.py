from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from src.domain import unified_jd_structured_spans_v4 as v4
from src.domain import unified_jd_structured_spans_v5 as v5
from src.domain import unified_jd_structured_spans_v6 as v6

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

STRUCTURED_SPAN_PARSER_VERSION = "unified-jd-structured-span-parser-v8-frozen"

_Origin = Literal["v4", "v5", "v6"]
_Family = Literal[
    "wrappers",
    "connector_labels",
    "coordinations",
    "shared_scopes",
    "example_attachments",
    "item_candidates",
]
_FAMILIES: tuple[_Family, ...] = (
    "wrappers",
    "connector_labels",
    "coordinations",
    "shared_scopes",
    "example_attachments",
    "item_candidates",
)


@dataclass(frozen=True, slots=True)
class _SignalMatch:
    signal: str
    envelope: SourceSpan | None
    outcome: str


@dataclass(frozen=True, slots=True)
class _DeltaNode:
    id: int
    origin: _Origin
    family: _Family
    signature: tuple[object, ...]
    value: object
    anchors: tuple[SourceSpan, ...]
    producers: tuple[SourceSpan, ...]


@dataclass(frozen=True, slots=True)
class _Component:
    id: int
    node_ids: frozenset[int]
    envelope: SourceSpan


@dataclass(frozen=True, slots=True)
class _Witness:
    mechanism: str
    envelope: SourceSpan
    component_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class _ComponentDecision:
    origins: dict[_Family, _Origin]
    witnesses: tuple[str, ...]
    compatibility: str
    selections: dict[_Family, str]


@dataclass(frozen=True, slots=True)
class _SelectionPlan:
    nodes: tuple[_DeltaNode, ...]
    components: tuple[_Component, ...]
    decisions: dict[int, _ComponentDecision]
    trace: tuple[str, ...]


def _bounds(value: SourceSpan) -> tuple[int, int]:
    return value.start, value.end


def _contains(container: SourceSpan, value: SourceSpan) -> bool:
    return container.start <= value.start and value.end <= container.end


def _overlaps(left: SourceSpan, right: SourceSpan) -> bool:
    return left.start < right.end and right.start < left.end


def _touches(left: SourceSpan, right: SourceSpan) -> bool:
    return left.start <= right.end and right.start <= left.end


def _envelope(source: str, spans: tuple[SourceSpan, ...]) -> SourceSpan:
    if not spans or any(not isinstance(span, SourceSpan) for span in spans):
        raise TypeError("an envelope requires SourceSpan values")
    return SourceSpan.from_bounds(
        source,
        min(span.start for span in spans),
        max(span.end for span in spans),
    )


def _member_spans(parsed: ParsedClause) -> dict[str, SourceSpan]:
    result = {candidate.id: candidate.span for candidate in parsed.item_candidates}
    for group in parsed.coordinations:
        result.update({member.id: member.span for member in group.members})
    return result


def _wrapper_signature(value: WrapperSpan) -> tuple[object, ...]:
    return value.kind, _bounds(value.marker_span), _bounds(value.content_span)


def _label_signature(value: ConnectorLabel) -> tuple[object, ...]:
    return _bounds(value.span), value.role


def _coordination_signature(value: CoordinationGroup) -> tuple[object, ...]:
    return (
        value.role,
        tuple(_bounds(span) for span in value.connector_spans),
        tuple(_bounds(member.span) for member in value.members),
    )


def _scope_signature(
    value: SharedScope, member_spans: dict[str, SourceSpan]
) -> tuple[object, ...]:
    return (
        value.kind,
        _bounds(value.span),
        tuple(
            _bounds(member_spans[member_id])
            for member_id in value.applies_to_member_ids
            if member_id in member_spans
        ),
    )


def _attachment_signature(value: ExampleAttachment) -> tuple[object, ...]:
    return (
        _bounds(value.cue_span),
        _bounds(value.parent_span),
        tuple(_bounds(span) for span in value.example_spans),
    )


def _candidate_signature(value: CoordinationMember) -> tuple[object, ...]:
    return (_bounds(value.span),)


def _family_entries(
    parsed: ParsedClause, family: _Family
) -> dict[
    tuple[object, ...], tuple[object, tuple[SourceSpan, ...], tuple[SourceSpan, ...]]
]:
    if family == "wrappers":
        return {
            _wrapper_signature(value): (
                value,
                (value.marker_span, value.content_span),
                (value.content_span,),
            )
            for value in parsed.wrappers
        }
    if family == "connector_labels":
        return {
            _label_signature(value): (value, (value.span,), ())
            for value in parsed.connector_labels
        }
    if family == "coordinations":
        return {
            _coordination_signature(value): (
                value,
                (*value.connector_spans, *(member.span for member in value.members)),
                tuple(member.span for member in value.members),
            )
            for value in parsed.coordinations
        }
    if family == "shared_scopes":
        members = _member_spans(parsed)
        return {
            _scope_signature(value, members): (
                value,
                (
                    value.span,
                    *(
                        members[member_id]
                        for member_id in value.applies_to_member_ids
                        if member_id in members
                    ),
                ),
                tuple(
                    members[member_id]
                    for member_id in value.applies_to_member_ids
                    if member_id in members
                ),
            )
            for value in parsed.shared_scopes
        }
    if family == "example_attachments":
        return {
            _attachment_signature(value): (
                value,
                (value.cue_span, value.parent_span, *value.example_spans),
                (value.parent_span, *value.example_spans),
            )
            for value in parsed.example_attachments
        }
    return {
        _candidate_signature(value): (value, (value.span,), (value.span,))
        for value in parsed.item_candidates
    }


def _delta_nodes(parses: dict[_Origin, ParsedClause]) -> tuple[_DeltaNode, ...]:
    raw: dict[
        tuple[_Origin, _Family, tuple[object, ...]],
        tuple[object, tuple[SourceSpan, ...], tuple[SourceSpan, ...]],
    ] = {}
    for other in ("v4", "v5"):
        for family in _FAMILIES:
            left = _family_entries(parses[other], family)
            baseline = _family_entries(parses["v6"], family)
            for signature in set(left) ^ set(baseline):
                if signature in left:
                    raw[(other, family, signature)] = left[signature]
                if signature in baseline:
                    raw[("v6", family, signature)] = baseline[signature]
    ordered = sorted(raw, key=lambda item: (item[1], repr(item[2]), item[0]))
    return tuple(
        _DeltaNode(index, origin, family, signature, *raw[(origin, family, signature)])
        for index, (origin, family, signature) in enumerate(ordered, start=1)
    )


def _structurally_linked(left: _DeltaNode, right: _DeltaNode) -> bool:
    left_bounds = {_bounds(span) for span in left.anchors}
    right_bounds = {_bounds(span) for span in right.anchors}
    if left_bounds & right_bounds:
        return True
    left_boundaries = {point for span in left.anchors for point in _bounds(span)}
    right_boundaries = {point for span in right.anchors for point in _bounds(span)}
    if left_boundaries & right_boundaries:
        return True
    left_producers = {_bounds(span) for span in left.producers}
    right_producers = {_bounds(span) for span in right.producers}
    return bool(
        left_producers & right_bounds
        or right_producers & left_bounds
        or left_producers & right_producers
    )


def _components(source: str, nodes: tuple[_DeltaNode, ...]) -> tuple[_Component, ...]:
    adjacency = {node.id: set() for node in nodes}
    for index, left in enumerate(nodes):
        for right in nodes[index + 1 :]:
            if _structurally_linked(left, right):
                adjacency[left.id].add(right.id)
                adjacency[right.id].add(left.id)
    by_id = {node.id: node for node in nodes}
    unseen = set(by_id)
    groups: list[frozenset[int]] = []
    while unseen:
        seed = min(unseen)
        pending = [seed]
        reached: set[int] = set()
        while pending:
            current = pending.pop()
            if current in reached:
                continue
            reached.add(current)
            pending.extend(adjacency[current] - reached)
        unseen -= reached
        groups.append(frozenset(reached))
    groups.sort(
        key=lambda group: (
            min(span.start for node_id in group for span in by_id[node_id].anchors),
            min(group),
        )
    )
    return tuple(
        _Component(
            index,
            group,
            _envelope(
                source,
                tuple(span for node_id in group for span in by_id[node_id].anchors),
            ),
        )
        for index, group in enumerate(groups, start=1)
    )


def _boundary_relation(
    source: str, wrapper: WrapperSpan, narrow: SourceSpan, broad: SourceSpan
) -> bool:
    if not _contains(broad, narrow) or _bounds(broad) == _bounds(narrow):
        return False
    if wrapper.kind.split(".")[-1] == "prefix":
        return (
            broad.start == wrapper.marker_span.start
            and narrow.start == wrapper.content_span.start
            and broad.end == narrow.end
            and not source[wrapper.marker_span.end : wrapper.content_span.start].strip()
        )
    return (
        broad.start == narrow.start
        and narrow.end == wrapper.content_span.end
        and broad.end == wrapper.marker_span.end
        and not source[wrapper.content_span.end : wrapper.marker_span.start].strip()
    )


def _component_index(components: tuple[_Component, ...]) -> dict[int, int]:
    return {
        node_id: component.id
        for component in components
        for node_id in component.node_ids
    }


def _related_components(
    anchors: tuple[SourceSpan, ...],
    nodes: tuple[_DeltaNode, ...],
    components: tuple[_Component, ...],
) -> frozenset[int]:
    exact = {_bounds(span) for span in anchors}
    boundaries = {point for span in anchors for point in _bounds(span)}
    index = _component_index(components)
    return frozenset(
        index[node.id]
        for node in nodes
        if any(
            _bounds(span) in exact or span.start in boundaries or span.end in boundaries
            for span in node.anchors
        )
    )


def _e2_witnesses(
    source: str,
    fresh: ParsedClause,
    baseline: ParsedClause,
    nodes: tuple[_DeltaNode, ...],
    components: tuple[_Component, ...],
) -> tuple[_Witness, ...]:
    baseline_wrappers = {_wrapper_signature(value) for value in baseline.wrappers}
    fresh_producers = tuple(
        span
        for family in (
            "coordinations",
            "shared_scopes",
            "example_attachments",
            "item_candidates",
        )
        for _, _, producers in _family_entries(fresh, family).values()
        for span in producers
    )
    baseline_producers = tuple(
        span
        for family in (
            "coordinations",
            "shared_scopes",
            "example_attachments",
            "item_candidates",
        )
        for _, _, producers in _family_entries(baseline, family).values()
        for span in producers
    )
    result: list[_Witness] = []
    for wrapper in fresh.wrappers:
        signature = _wrapper_signature(wrapper)
        if signature in baseline_wrappers:
            continue
        related = any(
            _boundary_relation(source, wrapper, narrow, broad)
            for narrow in fresh_producers
            for broad in baseline_producers
        )
        if not related:
            related = any(
                value.kind.split(".")[-1] == wrapper.kind.split(".")[-1]
                and _overlaps(value.content_span, wrapper.content_span)
                and (
                    _contains(value.marker_span, wrapper.marker_span)
                    or _contains(wrapper.marker_span, value.marker_span)
                )
                for value in baseline.wrappers
            )
        if not related:
            continue
        anchors = (wrapper.marker_span, wrapper.content_span)
        component_ids = _related_components(anchors, nodes, components)
        if not any(
            node.family != "wrappers"
            and _component_index(components).get(node.id) in component_ids
            for node in nodes
        ):
            continue
        result.append(
            _Witness(
                "E2-wrapper-boundary",
                _envelope(source, anchors),
                component_ids,
            )
        )
    return tuple(result)


def _connector_inside_examples(
    connector: SourceSpan, attachment: ExampleAttachment
) -> bool:
    return any(
        left.end <= connector.start and connector.end <= right.start
        for left, right in zip(
            attachment.example_spans, attachment.example_spans[1:], strict=False
        )
    )


def _e3_witnesses(
    source: str,
    fresh: ParsedClause,
    baseline: ParsedClause,
    nodes: tuple[_DeltaNode, ...],
    components: tuple[_Component, ...],
) -> tuple[_Witness, ...]:
    fresh_roles = {_bounds(value.span): value for value in fresh.connector_labels}
    baseline_roles = {_bounds(value.span): value for value in baseline.connector_labels}
    changed = {
        bounds
        for bounds in set(fresh_roles) | set(baseline_roles)
        if (fresh_roles.get(bounds) is None or fresh_roles[bounds].role)
        != (baseline_roles.get(bounds) is None or baseline_roles[bounds].role)
    }
    fresh_groups = {_coordination_signature(value) for value in fresh.coordinations}
    baseline_groups = {
        _coordination_signature(value) for value in baseline.coordinations
    }
    fresh_attachments = {
        _attachment_signature(value) for value in fresh.example_attachments
    }
    baseline_attachments = {
        _attachment_signature(value) for value in baseline.example_attachments
    }
    result: list[_Witness] = []
    for bounds in sorted(changed):
        connector = (fresh_roles.get(bounds) or baseline_roles[bounds]).span
        groups = tuple(
            group
            for group in (*fresh.coordinations, *baseline.coordinations)
            if any(_bounds(span) == bounds for span in group.connector_spans)
            and _coordination_signature(group) in (fresh_groups ^ baseline_groups)
        )
        attachments = tuple(
            attachment
            for attachment in (
                *fresh.example_attachments,
                *baseline.example_attachments,
            )
            if _connector_inside_examples(connector, attachment)
            and _attachment_signature(attachment)
            in (fresh_attachments ^ baseline_attachments)
        )
        if not groups and not attachments:
            continue
        anchors = (
            connector,
            *(span for group in groups for span in group.connector_spans),
            *(member.span for group in groups for member in group.members),
            *(
                span
                for attachment in attachments
                for span in (
                    attachment.cue_span,
                    attachment.parent_span,
                    *attachment.example_spans,
                )
            ),
        )
        result.append(
            _Witness(
                "E3-region-first-connector-role",
                _envelope(source, anchors),
                _related_components(anchors, nodes, components),
            )
        )
    return tuple(result)


def _e6_witnesses(
    source: str,
    fresh: ParsedClause,
    nodes: tuple[_DeltaNode, ...],
    components: tuple[_Component, ...],
) -> tuple[_Witness, ...]:
    result: list[_Witness] = []
    for wrapper in fresh.wrappers:
        if wrapper.kind != "open_list_suffix" or wrapper.marker_span.text != "等":
            continue
        suffix = next(
            (
                value
                for value in fresh.wrappers
                if value.kind.split(".")[-1] == "suffix"
                and value.marker_span.start >= wrapper.marker_span.end
                and value.marker_span.text in {"优先", "者优先", "的优先"}
            ),
            None,
        )
        if suffix is None:
            continue
        segment = next(
            (
                value
                for value in fresh.segments
                if _contains(value, wrapper.content_span)
            ),
            None,
        )
        if segment is None:
            continue
        position = fresh.segments.index(segment)
        if position == 0:
            continue
        header = fresh.segments[position - 1]
        between = source[header.end : segment.start]
        if "以下" not in header.text or not ({":", "："} & set(between)):
            continue
        anchors = (
            header,
            segment,
            wrapper.marker_span,
            wrapper.content_span,
            suffix.marker_span,
            suffix.content_span,
        )
        result.append(
            _Witness(
                "E6-priority-tail-rejection",
                _envelope(source, anchors),
                _related_components(anchors, nodes, components),
            )
        )
    return tuple(result)


def _e7_witnesses(
    source: str,
    fresh: ParsedClause,
    nodes: tuple[_DeltaNode, ...],
    components: tuple[_Component, ...],
) -> tuple[_Witness, ...]:
    result: list[_Witness] = []
    for attachment in fresh.example_attachments:
        if attachment.cue_span.text != "等" or not attachment.example_spans:
            continue
        first = attachment.example_spans[0]
        wrapper = next(
            (
                value
                for value in fresh.wrappers
                if value.kind.split(".")[-1] == "prefix"
                and value.marker_span.text == "对"
                and value.marker_span.end == first.start
                and _contains(value.content_span, first)
            ),
            None,
        )
        if wrapper is None or not attachment.parent_span.text.startswith(
            ("领域", "方面")
        ):
            continue
        anchors = (
            wrapper.marker_span,
            wrapper.content_span,
            attachment.cue_span,
            attachment.parent_span,
            *attachment.example_spans,
        )
        result.append(
            _Witness(
                "E7-prepositional-wrapper-before-example-split",
                _envelope(source, anchors),
                _related_components(anchors, nodes, components),
            )
        )
    return tuple(result)


def _witnesses(
    source: str,
    fresh: ParsedClause,
    baseline: ParsedClause,
    nodes: tuple[_DeltaNode, ...],
    components: tuple[_Component, ...],
) -> tuple[_Witness, ...]:
    values = (
        *_e2_witnesses(source, fresh, baseline, nodes, components),
        *_e3_witnesses(source, fresh, baseline, nodes, components),
        *_e6_witnesses(source, fresh, nodes, components),
        *_e7_witnesses(source, fresh, nodes, components),
    )
    unique = {
        (value.mechanism, _bounds(value.envelope), value.component_ids): value
        for value in values
    }
    return tuple(
        unique[key] for key in sorted(unique, key=lambda value: (value[1], value[0]))
    )


def _protected_attachment(parsed: ParsedClause, attachment: ExampleAttachment) -> bool:
    return any(
        _contains(enclosure, attachment.cue_span)
        or all(_contains(enclosure, span) for span in attachment.example_spans)
        for enclosure in parsed.protected_spans
    )


def _compatibility(
    component: _Component,
    component_witnesses: tuple[_Witness, ...],
    all_witnesses: tuple[_Witness, ...],
    nodes: tuple[_DeltaNode, ...],
    fresh: ParsedClause,
    baseline: ParsedClause,
) -> str:
    members = tuple(node for node in nodes if node.id in component.node_ids)
    mechanisms = {value.mechanism for value in component_witnesses}
    e2_count = sum(value.mechanism == "E2-wrapper-boundary" for value in all_witnesses)
    if (
        not fresh.example_attachments
        and not baseline.example_attachments
        and "E6-priority-tail-rejection" not in mechanisms
        and e2_count < 2
    ):
        return "veto:uncorroborated-structure"

    fresh_attachments = tuple(
        node.value
        for node in members
        if node.origin == "v5" and node.family == "example_attachments"
    )
    baseline_attachments = tuple(
        node.value
        for node in members
        if node.origin == "v6" and node.family == "example_attachments"
    )
    if any(not isinstance(value, ExampleAttachment) for value in fresh_attachments):
        return "veto:invalid-attachment"
    if any(not isinstance(value, ExampleAttachment) for value in baseline_attachments):
        return "veto:invalid-attachment"

    for raw in baseline_attachments:
        assert isinstance(raw, ExampleAttachment)
        same_cue = [
            value
            for value in fresh_attachments
            if isinstance(value, ExampleAttachment)
            and _bounds(value.cue_span) == _bounds(raw.cue_span)
        ]
        if not same_cue:
            return "veto:attachment-loss"
        same_unit = [
            value
            for value in same_cue
            if tuple(_bounds(span) for span in value.example_spans)
            == tuple(_bounds(span) for span in raw.example_spans)
        ]
        if _protected_attachment(baseline, raw) and not any(
            _contains(raw.parent_span, value.parent_span) for value in same_unit
        ):
            return "veto:protected-attachment-reparent"

    if not baseline.example_attachments and fresh_attachments:
        priority = any(
            node.origin == "v5"
            and node.family == "wrappers"
            and isinstance(node.value, WrapperSpan)
            and "优先" in node.value.marker_span.text
            for node in members
        )
        explicit = all(
            isinstance(value, ExampleAttachment)
            and value.cue_span.text.startswith(("如", "例如"))
            for value in fresh_attachments
        )
        if not priority and not explicit:
            return "veto:unsupported-role-transfer"

    baseline_candidates = tuple(
        node.value
        for node in members
        if node.origin == "v6" and node.family == "item_candidates"
    )
    fresh_candidates = tuple(
        node.value
        for node in members
        if node.origin == "v5" and node.family == "item_candidates"
    )
    if len(baseline_candidates) >= 2 and not fresh_candidates and not fresh_attachments:
        return "veto:surface-partition-deletion"
    for raw in fresh_candidates:
        assert isinstance(raw, CoordinationMember)
        if any(
            isinstance(prior, CoordinationMember)
            and _contains(raw.span, prior.span)
            and _bounds(raw.span) != _bounds(prior.span)
            for prior in baseline_candidates
        ) and any(
            node.origin == "v5"
            and node.family == "wrappers"
            and isinstance(node.value, WrapperSpan)
            and _contains(raw.span, node.value.marker_span)
            for node in members
        ):
            return "veto:atomic-producer-contamination"

    baseline_members = _member_spans(baseline)
    changed_baseline_spans = {
        _bounds(value.span)
        for value in baseline_candidates
        if isinstance(value, CoordinationMember)
    }
    component_scope_ids = {
        node.id for node in members if node.family == "shared_scopes"
    }
    for scope in baseline.shared_scopes:
        targets = {
            _bounds(baseline_members[member_id])
            for member_id in scope.applies_to_member_ids
            if member_id in baseline_members
        }
        if targets & changed_baseline_spans and not component_scope_ids:
            fresh_spans = {_bounds(span) for span in _member_spans(fresh).values()}
            if not targets <= fresh_spans:
                return "veto:scope-outside-closure"

    if "E2-wrapper-boundary" in mechanisms and not any(
        node.family != "wrappers" for node in members
    ):
        return "veto:unrepaired-E2"
    if "E3-region-first-connector-role" in mechanisms and not any(
        node.family in {"coordinations", "example_attachments"} for node in members
    ):
        return "veto:unrepaired-E3"
    return "pass"


def _s1_conflict(
    source: str, base: ParsedClause, baseline: ParsedClause
) -> _SignalMatch:
    baseline_candidates = {_bounds(value.span) for value in baseline.item_candidates}
    for attachment in baseline.example_attachments:
        if attachment.cue_span.text != "等" or len(attachment.example_spans) < 2:
            continue
        envelope = _envelope(source, (*attachment.example_spans, attachment.cue_span))
        if _protected_attachment(baseline, attachment):
            return _SignalMatch("S1", envelope, "veto:protected-attachment")
        cue_context = source[
            max(0, attachment.example_spans[0].start - 2) : attachment.cue_span.end
        ]
        if any(token in cue_context for token in ("如", "例如")):
            return _SignalMatch("S1", envelope, "veto:explicit-cue")
        if source[attachment.example_spans[-1].end : attachment.cue_span.start].strip():
            return _SignalMatch("S1", envelope, "veto:not-terminal")
        atoms = tuple(
            sorted(
                (
                    value.span
                    for value in base.item_candidates
                    if any(
                        _contains(example, value.span)
                        for example in attachment.example_spans
                    )
                ),
                key=lambda span: (span.start, span.end),
            )
        )
        if len(atoms) < 2 or any(
            left.end > right.start for left, right in pairwise(atoms)
        ):
            continue
        if not all(
            any(_contains(example, atom) for atom in atoms)
            for example in attachment.example_spans
        ):
            continue
        if not any(_bounds(atom) not in baseline_candidates for atom in atoms):
            return _SignalMatch("S1", envelope, "veto:additive-or-preserved")
        return _SignalMatch("S1", envelope, "fired")
    return _SignalMatch("S1", None, "veto:coverage-or-partition")


def _explicit_attachment_in(parsed: ParsedClause, envelope: SourceSpan) -> bool:
    for attachment in parsed.example_attachments:
        attachment_envelope = _envelope(
            parsed.source_text,
            (attachment.cue_span, attachment.parent_span, *attachment.example_spans),
        )
        if not _overlaps(attachment_envelope, envelope):
            continue
        if attachment.cue_span.text.startswith("如") or _protected_attachment(
            parsed, attachment
        ):
            return True
    return False


def _attachment_accounts_for(parsed: ParsedClause, span: SourceSpan) -> bool:
    return any(
        any(_contains(example, span) for example in attachment.example_spans)
        or _contains(attachment.parent_span, span)
        for attachment in parsed.example_attachments
    )


def _non_surface_spans(parsed: ParsedClause) -> tuple[SourceSpan, ...]:
    spans: list[SourceSpan] = []
    spans.extend(value.marker_span for value in parsed.wrappers)
    spans.extend(value.span for value in parsed.shared_scopes)
    for group in parsed.coordinations:
        if group.role != "surface":
            spans.extend(member.span for member in group.members)
    for attachment in parsed.example_attachments:
        spans.extend((attachment.parent_span, *attachment.example_spans))
    return tuple(spans)


def _s2_conflict(
    source: str, base: ParsedClause, baseline: ParsedClause
) -> _SignalMatch:
    baseline_candidates = {
        _bounds(value.span): value.span for value in baseline.item_candidates
    }
    surface_connectors = tuple(
        value.span for value in baseline.connector_labels if value.role == "surface"
    )
    wrapper_markers = tuple(
        value.marker_span for parsed in (base, baseline) for value in parsed.wrappers
    )
    hidden = _non_surface_spans(baseline)
    for candidate in base.item_candidates:
        atom = candidate.span
        if _bounds(atom) in baseline_candidates:
            continue
        overlapping = tuple(
            span for span in baseline_candidates.values() if _overlaps(atom, span)
        )
        envelope = _envelope(source, (atom, *overlapping))
        if _explicit_attachment_in(baseline, envelope):
            return _SignalMatch("S2", envelope, "veto:explicit-attachment")
        if _attachment_accounts_for(baseline, atom):
            return _SignalMatch("S2", envelope, "veto:attachment-topology")
        strict_enclosure = any(
            _contains(span, atom) and _bounds(span) != _bounds(atom)
            for span in overlapping
        )
        promoted = len(
            [span for span in overlapping if _contains(atom, span)]
        ) >= 2 and any(
            atom.start < connector.start < connector.end < atom.end
            for connector in surface_connectors
        )
        contaminated = strict_enclosure and any(
            _contains(span, marker) and not _overlaps(atom, marker)
            for span in overlapping
            for marker in wrapper_markers
        )
        deleted = not overlapping and any(
            _contains(span, atom) or _contains(atom, span) for span in hidden
        )
        if strict_enclosure or promoted or contaminated or deleted:
            return _SignalMatch("S2", envelope, "fired")
    return _SignalMatch("S2", None, "veto:atoms-preserved-or-additive")


def _same_attachment_unit(left: ExampleAttachment, right: ExampleAttachment) -> bool:
    return _bounds(left.cue_span) == _bounds(right.cue_span) and tuple(
        _bounds(value) for value in left.example_spans
    ) == tuple(_bounds(value) for value in right.example_spans)


def _scope_targets_available(
    scope: SharedScope, source: ParsedClause, target: ParsedClause
) -> bool:
    source_members = _member_spans(source)
    target_spans = {_bounds(span) for span in _member_spans(target).values()}
    return all(
        member_id in source_members
        and _bounds(source_members[member_id]) in target_spans
        for member_id in scope.applies_to_member_ids
    )


def _s3_conflict(
    source: str, base: ParsedClause, baseline: ParsedClause
) -> _SignalMatch:
    operator_boundaries = {
        value.marker_span.start
        for parsed in (base, baseline)
        for value in parsed.wrappers
    }
    operator_boundaries.update(value.span.start for value in base.shared_scopes)
    operator_boundaries.update(value.span.start for value in baseline.shared_scopes)
    base_candidates = {_bounds(value.span) for value in base.item_candidates}
    for current in baseline.example_attachments:
        prior = next(
            (
                value
                for value in base.example_attachments
                if _same_attachment_unit(value, current)
            ),
            None,
        )
        if prior is None or _bounds(prior.parent_span) == _bounds(current.parent_span):
            continue
        crossing = None
        for group in baseline.coordinations:
            if group.role != "surface":
                continue
            contained_members = [
                member
                for member in group.members
                if _contains(current.parent_span, member.span)
            ]
            if len(contained_members) < 2:
                continue
            for connector in group.connector_spans:
                if not (
                    current.parent_span.start < connector.start
                    and connector.end < current.parent_span.end
                    and prior.parent_span.end <= connector.start
                    and any(
                        member.span.start < prior.parent_span.end <= member.span.end
                        for member in contained_members
                    )
                ):
                    continue
                crossing = connector
                break
            if crossing is not None:
                break
        if crossing is None:
            continue
        residual = next(
            (
                candidate.span
                for candidate in baseline.item_candidates
                if _bounds(candidate.span) not in base_candidates
                and candidate.span.start in operator_boundaries
                and _touches(candidate.span, current.parent_span)
            ),
            None,
        )
        if residual is None:
            envelope = _envelope(
                source, (prior.parent_span, current.parent_span, crossing)
            )
            return _SignalMatch("S3", envelope, "veto:no-residual-operator")
        if not all(
            _scope_targets_available(scope, base, baseline)
            for scope in base.shared_scopes
        ):
            envelope = _envelope(
                source, (prior.parent_span, current.parent_span, crossing, residual)
            )
            return _SignalMatch("S3", envelope, "veto:reference-closure")
        envelope = _envelope(
            source, (prior.parent_span, current.parent_span, crossing, residual)
        )
        return _SignalMatch("S3", envelope, "fired")
    return _SignalMatch("S3", None, "veto:no-cross-coordination-bundle")


def _component_has_family(
    component: _Component, nodes: tuple[_DeltaNode, ...], family: _Family
) -> bool:
    return any(
        node.id in component.node_ids and node.family == family for node in nodes
    )


def _trace_entry(
    component: str,
    envelope: SourceSpan | None,
    witnesses: tuple[str, ...],
    compatibility: str,
    family: str,
    origin: _Origin,
    selection: str,
) -> str:
    bounds = "none" if envelope is None else f"{envelope.start}-{envelope.end}"
    witness = "+".join(witnesses) if witnesses else "none"
    return (
        f"v8.selector:component={component}:envelope={bounds}:witness={witness}:"
        f"compatibility={compatibility}:family={family}:origin={origin}:"
        f"selection={selection}"
    )


def _selection_plan(
    source: str, base: ParsedClause, fresh: ParsedClause, baseline: ParsedClause
) -> _SelectionPlan:
    parses: dict[_Origin, ParsedClause] = {"v4": base, "v5": fresh, "v6": baseline}
    nodes = _delta_nodes(parses)
    components = _components(source, nodes)
    witnesses = _witnesses(source, fresh, baseline, nodes, components)
    by_component = {
        component.id: tuple(
            witness for witness in witnesses if component.id in witness.component_ids
        )
        for component in components
    }
    decisions: dict[int, _ComponentDecision] = {}
    for component in components:
        affected = tuple(
            family
            for family in _FAMILIES
            if _component_has_family(component, nodes, family)
        )
        local = by_component[component.id]
        names = tuple(sorted({value.mechanism for value in local}))
        if not names:
            decisions[component.id] = _ComponentDecision(
                {family: "v6" for family in affected},
                (),
                "not-activated",
                {family: "default-v6" for family in affected},
            )
            continue
        compatibility = _compatibility(
            component, local, witnesses, nodes, fresh, baseline
        )
        origin: _Origin = "v5" if compatibility == "pass" else "v6"
        selection = "supported-v5" if compatibility == "pass" else "compatibility-veto"
        decisions[component.id] = _ComponentDecision(
            {family: origin for family in affected},
            names,
            compatibility,
            {family: selection for family in affected},
        )

    signals = (
        _s3_conflict(source, base, baseline),
        _s1_conflict(source, base, baseline),
        _s2_conflict(source, base, baseline),
    )
    bundles: dict[str, frozenset[_Family]] = {
        "S3": frozenset({"item_candidates", "shared_scopes", "example_attachments"}),
        "S1": frozenset({"item_candidates", "example_attachments"}),
        "S2": frozenset({"item_candidates"}),
    }
    for signal in signals:
        if signal.outcome != "fired" or signal.envelope is None:
            continue
        for component in components:
            if not _overlaps(component.envelope, signal.envelope):
                continue
            if not any(
                _component_has_family(component, nodes, family)
                for family in bundles[signal.signal]
            ):
                continue
            current = decisions[component.id]
            routed = tuple(
                family
                for family in bundles[signal.signal]
                if _component_has_family(component, nodes, family)
            )
            if signal.signal == "S2" and any(
                current.origins[family] == "v5" for family in routed
            ):
                continue
            origins = dict(current.origins)
            selections = dict(current.selections)
            for family in routed:
                if signal.signal == "S1" and selections[family] == "S3":
                    continue
                origins[family] = "v4"
                selections[family] = signal.signal
            decisions[component.id] = _ComponentDecision(
                origins,
                current.witnesses,
                current.compatibility,
                selections,
            )

    trace: list[str] = []
    for component in components:
        decision = decisions[component.id]
        affected = tuple(
            family
            for family in _FAMILIES
            if _component_has_family(component, nodes, family)
        )
        for family in affected:
            trace.append(
                _trace_entry(
                    str(component.id),
                    component.envelope,
                    decision.witnesses,
                    decision.compatibility,
                    family,
                    decision.origins[family],
                    decision.selections[family],
                )
            )
    touched = {
        family
        for component in components
        for family in _FAMILIES
        if _component_has_family(component, nodes, family)
    }
    for family in _FAMILIES:
        if family not in touched:
            trace.append(
                _trace_entry(
                    "none", None, (), "not-applicable", family, "v6", "default-v6"
                )
            )
    for witness in witnesses:
        if witness.component_ids:
            continue
        trace.append(
            _trace_entry(
                "witness-only",
                witness.envelope,
                (witness.mechanism,),
                "pass",
                "none",
                "v6",
                "no-delta",
            )
        )
    return _SelectionPlan(nodes, components, decisions, tuple(trace))


def _selected_values(
    parses: dict[_Origin, ParsedClause], plan: _SelectionPlan
) -> dict[_Family, tuple[tuple[_Origin, object], ...]]:
    node_by_id = {node.id: node for node in plan.nodes}
    selected: dict[_Family, dict[tuple[object, ...], tuple[_Origin, object]]] = {}
    for family in _FAMILIES:
        baseline = _family_entries(parses["v6"], family)
        selected[family] = {
            signature: ("v6", value[0]) for signature, value in baseline.items()
        }
    for component in plan.components:
        decision = plan.decisions[component.id]
        component_nodes = [node_by_id[node_id] for node_id in component.node_ids]
        for family in _FAMILIES:
            family_nodes = [node for node in component_nodes if node.family == family]
            if not family_nodes:
                continue
            for node in family_nodes:
                selected[family].pop(node.signature, None)
            origin = decision.origins[family]
            entries = _family_entries(parses[origin], family)
            for signature in {node.signature for node in family_nodes}:
                if signature in entries:
                    selected[family][signature] = (origin, entries[signature][0])
    return {
        family: tuple(
            value
            for _, value in sorted(
                selected[family].items(), key=lambda item: repr(item[0])
            )
        )
        for family in _FAMILIES
    }


def _rebuild(
    source: str,
    category: SurfaceCategory,
    parses: dict[_Origin, ParsedClause],
    plan: _SelectionPlan,
) -> ParsedClause:
    selected = _selected_values(parses, plan)
    next_id = 1

    def new_id(prefix: str) -> str:
        nonlocal next_id
        result = f"{prefix}-{next_id}"
        next_id += 1
        return result

    id_map: dict[tuple[_Origin, str], str] = {}
    span_to_group_ids: dict[tuple[int, int], list[str]] = {}
    span_to_candidate_ids: dict[tuple[int, int], list[str]] = {}
    coordinations: list[CoordinationGroup] = []
    for origin, raw in selected["coordinations"]:
        assert isinstance(raw, CoordinationGroup)
        members: list[CoordinationMember] = []
        for member in raw.members:
            rebuilt = CoordinationMember(
                new_id("member"), member.span, member.segment_index
            )
            id_map[(origin, member.id)] = rebuilt.id
            span_to_group_ids.setdefault(_bounds(member.span), []).append(rebuilt.id)
            members.append(rebuilt)
        coordinations.append(
            CoordinationGroup(
                new_id("coord"),
                raw.role,
                raw.kind,
                raw.connector_spans,
                tuple(members),
            )
        )

    candidates: list[CoordinationMember] = []
    for origin, raw in selected["item_candidates"]:
        assert isinstance(raw, CoordinationMember)
        rebuilt = CoordinationMember(new_id("candidate"), raw.span, raw.segment_index)
        id_map[(origin, raw.id)] = rebuilt.id
        span_to_candidate_ids.setdefault(_bounds(raw.span), []).append(rebuilt.id)
        candidates.append(rebuilt)

    source_members = {
        origin: _member_spans(parsed) for origin, parsed in parses.items()
    }
    scopes: list[SharedScope] = []
    for origin, raw in selected["shared_scopes"]:
        assert isinstance(raw, SharedScope)
        references: list[str] = []
        for old_id in raw.applies_to_member_ids:
            replacement = id_map.get((origin, old_id))
            if replacement is None:
                if old_id not in source_members[origin]:
                    raise ValueError("selected scope has an unknown source member")
                bounds = _bounds(source_members[origin][old_id])
                available = span_to_group_ids.get(bounds) or span_to_candidate_ids.get(
                    bounds
                )
                if not available or len(available) != 1:
                    raise ValueError(
                        "selected scope route is not uniquely reference-closed"
                    )
                replacement = available[0]
            if replacement not in references:
                references.append(replacement)
        scopes.append(
            SharedScope(new_id("scope"), raw.kind, raw.span, tuple(references))
        )

    attachments: list[ExampleAttachment] = []
    for _, raw in selected["example_attachments"]:
        assert isinstance(raw, ExampleAttachment)
        attachments.append(
            ExampleAttachment(
                new_id("example"),
                raw.cue_span,
                raw.parent_span,
                raw.example_spans,
                raw.segment_index,
            )
        )

    labels: dict[tuple[int, int], ConnectorLabel] = {}
    for _, raw in selected["connector_labels"]:
        assert isinstance(raw, ConnectorLabel)
        labels[_bounds(raw.span)] = raw
    for group in coordinations:
        for connector in group.connector_spans:
            existing = labels.get(_bounds(connector))
            if existing is not None and existing.role != group.role:
                raise ValueError(
                    "selected connector and coordination families disagree"
                )
            labels[_bounds(connector)] = ConnectorLabel(connector, group.role)

    wrappers = tuple(
        sorted(
            {
                value
                for _, value in selected["wrappers"]
                if isinstance(value, WrapperSpan)
            },
            key=lambda value: (
                value.marker_span.start,
                value.marker_span.end,
                value.content_span.start,
                value.content_span.end,
                value.kind,
            ),
        )
    )
    baseline = parses["v6"]
    return ParsedClause(
        source_text=source,
        category=category,
        protected_spans=baseline.protected_spans,
        segments=baseline.segments,
        wrappers=wrappers,
        connector_labels=tuple(labels[key] for key in sorted(labels)),
        coordinations=tuple(coordinations),
        shared_scopes=tuple(scopes),
        example_attachments=tuple(
            sorted(attachments, key=lambda value: (value.cue_span.start, value.id))
        ),
        item_candidates=tuple(
            sorted(
                candidates,
                key=lambda value: (value.span.start, value.span.end, value.id),
            )
        ),
        rule_ids=(
            "v8.frozen-candidate-graphs",
            "v8.component-activation-compatibility",
            *plan.trace,
            "v8.reference-closure",
            "v8.graph-projection-once",
        ),
    )


def _fallback_plan(plan: _SelectionPlan) -> _SelectionPlan:
    decisions = {
        component.id: _ComponentDecision(
            {
                family: "v6"
                for family in _FAMILIES
                if _component_has_family(component, plan.nodes, family)
            },
            plan.decisions[component.id].witnesses,
            "veto:graph-validity",
            {
                family: "default-v6"
                for family in _FAMILIES
                if _component_has_family(component, plan.nodes, family)
            },
        )
        for component in plan.components
    }
    trace = tuple(
        _trace_entry(
            str(component.id),
            component.envelope,
            decisions[component.id].witnesses,
            decisions[component.id].compatibility,
            family,
            decisions[component.id].origins[family],
            "default-v6",
        )
        for component in plan.components
        for family in _FAMILIES
        if _component_has_family(component, plan.nodes, family)
    )
    return _SelectionPlan(plan.nodes, plan.components, decisions, trace)


def parse_clause(source_text: str, category: SurfaceCategory) -> ParsedClause:
    if not source_text.strip():
        raise ValueError("source_text must not be empty")
    parses: dict[_Origin, ParsedClause] = {
        "v4": v4.parse_clause(source_text, category),
        "v5": v5.parse_clause(source_text, category),
        "v6": v6.parse_clause(source_text, category),
    }
    plan = _selection_plan(source_text, parses["v4"], parses["v5"], parses["v6"])
    try:
        return _rebuild(source_text, category, parses, plan)
    except ValueError:
        return _rebuild(source_text, category, parses, _fallback_plan(plan))


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

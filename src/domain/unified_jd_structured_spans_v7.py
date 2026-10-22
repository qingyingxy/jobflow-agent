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

STRUCTURED_SPAN_PARSER_VERSION = "unified-jd-structured-span-parser-v7-frozen"

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
class _LicensedEnvelope:
    mechanism: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class _SelectionPlan:
    origins: dict[_Family, _Origin]
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


def _family_nodes(
    parsed: ParsedClause, family: _Family
) -> dict[tuple[object, ...], SourceSpan]:
    if family == "wrappers":
        return {
            _wrapper_signature(value): _envelope(
                parsed.source_text, (value.marker_span, value.content_span)
            )
            for value in parsed.wrappers
        }
    if family == "connector_labels":
        return {_label_signature(value): value.span for value in parsed.connector_labels}
    if family == "coordinations":
        return {
            _coordination_signature(value): _envelope(
                parsed.source_text,
                (*value.connector_spans, *(member.span for member in value.members)),
            )
            for value in parsed.coordinations
        }
    if family == "shared_scopes":
        members = _member_spans(parsed)
        return {
            _scope_signature(value, members): _envelope(
                parsed.source_text,
                (
                    value.span,
                    *(
                        members[member_id]
                        for member_id in value.applies_to_member_ids
                        if member_id in members
                    ),
                ),
            )
            for value in parsed.shared_scopes
        }
    if family == "example_attachments":
        return {
            _attachment_signature(value): _envelope(
                parsed.source_text,
                (value.cue_span, value.parent_span, *value.example_spans),
            )
            for value in parsed.example_attachments
        }
    return {
        _candidate_signature(value): value.span for value in parsed.item_candidates
    }


def _family_delta_spans(
    left: ParsedClause, right: ParsedClause, family: _Family
) -> tuple[SourceSpan, ...]:
    left_nodes = _family_nodes(left, family)
    right_nodes = _family_nodes(right, family)
    keys = set(left_nodes) ^ set(right_nodes)
    return tuple(
        sorted(
            (left_nodes.get(key) or right_nodes[key] for key in keys),
            key=lambda span: (span.start, span.end),
        )
    )


def _all_producer_spans(parsed: ParsedClause) -> tuple[SourceSpan, ...]:
    spans = [candidate.span for candidate in parsed.item_candidates]
    spans.extend(
        member.span for group in parsed.coordinations for member in group.members
    )
    return tuple(spans)


def _boundary_relation(
    source: str,
    wrapper: WrapperSpan,
    narrow: SourceSpan,
    broad: SourceSpan,
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


def _e2_envelopes(
    source: str, fresh: ParsedClause, baseline: ParsedClause
) -> tuple[_LicensedEnvelope, ...]:
    baseline_wrappers = {_wrapper_signature(value) for value in baseline.wrappers}
    fresh_spans = _all_producer_spans(fresh)
    baseline_spans = _all_producer_spans(baseline)
    result: list[_LicensedEnvelope] = []
    for wrapper in fresh.wrappers:
        if _wrapper_signature(wrapper) in baseline_wrappers:
            continue
        related = any(
            _boundary_relation(source, wrapper, narrow, broad)
            for narrow in fresh_spans
            for broad in baseline_spans
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
        if related:
            result.append(
                _LicensedEnvelope(
                    "E2-wrapper-boundary",
                    _envelope(source, (wrapper.marker_span, wrapper.content_span)),
                )
            )
    return tuple(result)


def _group_span(source: str, value: CoordinationGroup) -> SourceSpan:
    return _envelope(
        source, (*value.connector_spans, *(member.span for member in value.members))
    )


def _connector_inside_examples(
    connector: SourceSpan, attachment: ExampleAttachment
) -> bool:
    return any(
        left.end <= connector.start
        and connector.end <= right.start
        and left.start < right.end
        for left, right in zip(
            attachment.example_spans, attachment.example_spans[1:], strict=False
        )
    )


def _e3_envelopes(
    source: str, fresh: ParsedClause, baseline: ParsedClause
) -> tuple[_LicensedEnvelope, ...]:
    fresh_roles = {_bounds(value.span): value.role for value in fresh.connector_labels}
    baseline_roles = {_bounds(value.span): value.role for value in baseline.connector_labels}
    changed = {
        bounds
        for bounds in set(fresh_roles) | set(baseline_roles)
        if fresh_roles.get(bounds) != baseline_roles.get(bounds)
    }
    fresh_groups = {_coordination_signature(value) for value in fresh.coordinations}
    baseline_groups = {_coordination_signature(value) for value in baseline.coordinations}
    result: list[_LicensedEnvelope] = []
    groups = (*fresh.coordinations, *baseline.coordinations)
    for group in groups:
        group_changed = _coordination_signature(group) in (
            fresh_groups ^ baseline_groups
        )
        relevant = tuple(
            connector
            for connector in group.connector_spans
            if _bounds(connector) in changed
        )
        if not group_changed and not relevant:
            continue
        group_envelope = _group_span(source, group)
        result.append(
            _LicensedEnvelope("E3-region-first-connector-role", group_envelope)
        )
        for attachment in (*fresh.example_attachments, *baseline.example_attachments):
            if any(
                _connector_inside_examples(connector, attachment)
                for connector in group.connector_spans
            ):
                result.append(
                    _LicensedEnvelope(
                        "E3-region-first-connector-role",
                        _envelope(
                            source,
                            (
                                attachment.cue_span,
                                attachment.parent_span,
                                *attachment.example_spans,
                            ),
                        ),
                    )
                )
    return tuple(result)


def _e6_envelopes(source: str, fresh: ParsedClause) -> tuple[_LicensedEnvelope, ...]:
    result: list[_LicensedEnvelope] = []
    for wrapper in fresh.wrappers:
        if wrapper.kind != "open_list_suffix" or wrapper.marker_span.text != "等":
            continue
        suffixes = [
            value
            for value in fresh.wrappers
            if value.kind.split(".")[-1] == "suffix"
            and value.marker_span.start >= wrapper.marker_span.end
            and value.marker_span.text in {"优先", "者优先", "的优先"}
        ]
        if not suffixes:
            continue
        containing_segment = next(
            (
                segment
                for segment in fresh.segments
                if _contains(segment, wrapper.content_span)
            ),
            None,
        )
        if containing_segment is None:
            continue
        position = fresh.segments.index(containing_segment)
        if position == 0:
            continue
        header = fresh.segments[position - 1]
        between = source[header.end : containing_segment.start]
        if "以下" not in header.text or ":" not in between and "：" not in between:
            continue
        result.append(
            _LicensedEnvelope(
                "E6-priority-tail-rejection",
                _envelope(source, (header, containing_segment, *suffixes[0:1])),
            )
        )
    return tuple(result)


def _e7_envelopes(source: str, fresh: ParsedClause) -> tuple[_LicensedEnvelope, ...]:
    result: list[_LicensedEnvelope] = []
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
        if wrapper is None or not attachment.parent_span.text.startswith(("领域", "方面")):
            continue
        result.append(
            _LicensedEnvelope(
                "E7-prepositional-wrapper-before-example-split",
                _envelope(
                    source,
                    (
                        wrapper.marker_span,
                        wrapper.content_span,
                        attachment.cue_span,
                        attachment.parent_span,
                        *attachment.example_spans,
                    ),
                ),
            )
        )
    return tuple(result)


def _supported_envelopes(
    source: str, fresh: ParsedClause, baseline: ParsedClause
) -> tuple[_LicensedEnvelope, ...]:
    values = (
        *_e2_envelopes(source, fresh, baseline),
        *_e3_envelopes(source, fresh, baseline),
        *_e6_envelopes(source, fresh),
        *_e7_envelopes(source, fresh),
    )
    unique = {(value.mechanism, _bounds(value.span)): value for value in values}
    return tuple(
        unique[key] for key in sorted(unique, key=lambda item: (item[1], item[0]))
    )


def _licensed_family(
    fresh: ParsedClause,
    baseline: ParsedClause,
    family: _Family,
    envelopes: tuple[_LicensedEnvelope, ...],
) -> tuple[bool, str, SourceSpan | None]:
    delta = _family_delta_spans(fresh, baseline, family)
    if not delta:
        return False, "no-delta", None
    covering = [
        envelope
        for envelope in envelopes
        if any(_contains(envelope.span, span) for span in delta)
    ]
    if not all(any(_contains(value.span, span) for value in envelopes) for span in delta):
        return False, "unlicensed-delta", _envelope(fresh.source_text, delta)
    mechanisms = "+".join(sorted({value.mechanism for value in covering}))
    return True, mechanisms, _envelope(fresh.source_text, delta)


def _protected_attachment(parsed: ParsedClause, attachment: ExampleAttachment) -> bool:
    return any(
        _contains(enclosure, attachment.cue_span)
        or all(_contains(enclosure, span) for span in attachment.example_spans)
        for enclosure in parsed.protected_spans
    )


def _s1_conflict(source: str, base: ParsedClause, baseline: ParsedClause) -> _SignalMatch:
    baseline_candidates = {_bounds(value.span) for value in baseline.item_candidates}
    for attachment in baseline.example_attachments:
        if attachment.cue_span.text != "等" or len(attachment.example_spans) < 2:
            continue
        envelope = _envelope(source, (*attachment.example_spans, attachment.cue_span))
        if _protected_attachment(baseline, attachment):
            return _SignalMatch("S1", envelope, "veto:protected-attachment")
        cue_context = source[max(0, attachment.example_spans[0].start - 2) : attachment.cue_span.end]
        if any(token in cue_context for token in ("如", "例如")):
            return _SignalMatch("S1", envelope, "veto:explicit-cue")
        if source[attachment.example_spans[-1].end : attachment.cue_span.start].strip():
            return _SignalMatch("S1", envelope, "veto:not-terminal")
        atoms = tuple(
            sorted(
                (
                    value.span
                    for value in base.item_candidates
                    if any(_contains(example, value.span) for example in attachment.example_spans)
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


def _explicit_attachment_in(
    parsed: ParsedClause, envelope: SourceSpan
) -> bool:
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


def _s2_conflict(source: str, base: ParsedClause, baseline: ParsedClause) -> _SignalMatch:
    baseline_candidates = {_bounds(value.span): value.span for value in baseline.item_candidates}
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
        strict_enclosure = any(
            _contains(span, atom) and _bounds(span) != _bounds(atom)
            for span in overlapping
        )
        promoted = len([span for span in overlapping if _contains(atom, span)]) >= 2 and any(
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


def _scope_targets_available(scope: SharedScope, source: ParsedClause, target: ParsedClause) -> bool:
    source_members = _member_spans(source)
    target_spans = {_bounds(span) for span in _member_spans(target).values()}
    return all(
        member_id in source_members and _bounds(source_members[member_id]) in target_spans
        for member_id in scope.applies_to_member_ids
    )


def _s3_conflict(source: str, base: ParsedClause, baseline: ParsedClause) -> _SignalMatch:
    operator_boundaries = {
        value.marker_span.start for parsed in (base, baseline) for value in parsed.wrappers
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
                member for member in group.members if _contains(current.parent_span, member.span)
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
            envelope = _envelope(source, (prior.parent_span, current.parent_span, crossing))
            return _SignalMatch("S3", envelope, "veto:no-residual-operator")
        if not all(_scope_targets_available(scope, base, baseline) for scope in base.shared_scopes):
            envelope = _envelope(
                source, (prior.parent_span, current.parent_span, crossing, residual)
            )
            return _SignalMatch("S3", envelope, "veto:reference-closure")
        envelope = _envelope(
            source, (prior.parent_span, current.parent_span, crossing, residual)
        )
        return _SignalMatch("S3", envelope, "fired")
    return _SignalMatch("S3", None, "veto:no-cross-coordination-bundle")


def _trace_entry(
    signal: str,
    family: str,
    envelope: SourceSpan | None,
    origin: _Origin,
    outcome: str,
) -> str:
    bounds = "none" if envelope is None else f"{envelope.start}-{envelope.end}"
    return (
        f"v7.selector:signal={signal}:family={family}:envelope={bounds}:"
        f"origin={origin}:outcome={outcome}"
    )


def _selection_plan(
    source: str, base: ParsedClause, fresh: ParsedClause, baseline: ParsedClause
) -> _SelectionPlan:
    s3 = _s3_conflict(source, base, baseline)
    s1 = _s1_conflict(source, base, baseline)
    s2 = _s2_conflict(source, base, baseline)
    conflicts = tuple(value for value in (s3, s1, s2) if value.outcome == "fired")
    envelopes = _supported_envelopes(source, fresh, baseline)
    origins: dict[_Family, _Origin] = {family: "v6" for family in _FAMILIES}
    trace: list[str] = [
        _trace_entry(value.signal, "predicate", value.envelope, "v6", value.outcome)
        for value in (s3, s1, s2)
    ]

    for family in _FAMILIES:
        licensed, outcome, envelope = _licensed_family(
            fresh, baseline, family, envelopes
        )
        if conflicts:
            trace.append(
                _trace_entry(
                    "supported-v5",
                    family,
                    envelope,
                    "v6",
                    "veto:runtime-conflict" if licensed else outcome,
                )
            )
            continue
        if licensed:
            origins[family] = "v5"
            trace.append(
                _trace_entry("supported-v5", family, envelope, "v5", outcome)
            )
        else:
            trace.append(
                _trace_entry("supported-v5", family, envelope, "v6", outcome)
            )

    if s2.outcome == "fired":
        origins["item_candidates"] = "v4"
    if s1.outcome == "fired":
        origins["item_candidates"] = "v4"
        origins["example_attachments"] = "v4"
    if s3.outcome == "fired":
        origins["item_candidates"] = "v4"
        origins["shared_scopes"] = "v4"
        origins["example_attachments"] = "v4"

    for family in _FAMILIES:
        winning = next(
            (
                value
                for value in (s3, s1, s2)
                if value.outcome == "fired"
                and (
                    value.signal == "S3"
                    and family
                    in {"item_candidates", "shared_scopes", "example_attachments"}
                    or value.signal == "S1"
                    and family in {"item_candidates", "example_attachments"}
                    or value.signal == "S2"
                    and family == "item_candidates"
                )
            ),
            None,
        )
        signal = winning.signal if winning is not None else (
            "supported-v5" if origins[family] == "v5" else "default-v6"
        )
        envelope = winning.envelope if winning is not None else None
        trace.append(
            _trace_entry(signal, family, envelope, origins[family], "selected")
        )
    return _SelectionPlan(origins, tuple(trace))


def _family_values(parsed: ParsedClause, family: _Family) -> tuple[object, ...]:
    if family == "wrappers":
        return parsed.wrappers
    if family == "connector_labels":
        return parsed.connector_labels
    if family == "coordinations":
        return parsed.coordinations
    if family == "shared_scopes":
        return parsed.shared_scopes
    if family == "example_attachments":
        return parsed.example_attachments
    return parsed.item_candidates


def _parsed_for(origin: _Origin, values: dict[_Origin, ParsedClause]) -> ParsedClause:
    return values[origin]


def _rebuild(
    source: str,
    category: SurfaceCategory,
    parses: dict[_Origin, ParsedClause],
    plan: _SelectionPlan,
) -> ParsedClause:
    selected = {
        family: _family_values(_parsed_for(plan.origins[family], parses), family)
        for family in _FAMILIES
    }
    next_id = 1

    def new_id(prefix: str) -> str:
        nonlocal next_id
        result = f"{prefix}-{next_id}"
        next_id += 1
        return result

    span_to_ids: dict[tuple[int, int], list[str]] = {}
    coordinations: list[CoordinationGroup] = []
    for raw in selected["coordinations"]:
        assert isinstance(raw, CoordinationGroup)
        members: list[CoordinationMember] = []
        for member in raw.members:
            rebuilt = CoordinationMember(new_id("member"), member.span, member.segment_index)
            span_to_ids.setdefault(_bounds(member.span), []).append(rebuilt.id)
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
    for raw in selected["item_candidates"]:
        assert isinstance(raw, CoordinationMember)
        rebuilt = CoordinationMember(new_id("candidate"), raw.span, raw.segment_index)
        span_to_ids.setdefault(_bounds(raw.span), []).append(rebuilt.id)
        candidates.append(rebuilt)

    scope_origin = plan.origins["shared_scopes"]
    source_members = _member_spans(parses[scope_origin])
    scopes: list[SharedScope] = []
    for raw in selected["shared_scopes"]:
        assert isinstance(raw, SharedScope)
        references: list[str] = []
        for old_id in raw.applies_to_member_ids:
            if old_id not in source_members:
                raise ValueError("selected scope has an unknown source member")
            available = span_to_ids.get(_bounds(source_members[old_id]), [])
            if not available:
                raise ValueError("selected scope route is not reference-closed")
            if available[0] not in references:
                references.append(available[0])
        scopes.append(SharedScope(new_id("scope"), raw.kind, raw.span, tuple(references)))

    attachments: list[ExampleAttachment] = []
    for raw in selected["example_attachments"]:
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
    for raw in selected["connector_labels"]:
        assert isinstance(raw, ConnectorLabel)
        labels[_bounds(raw.span)] = raw
    for group in coordinations:
        for connector in group.connector_spans:
            existing = labels.get(_bounds(connector))
            if existing is not None and existing.role != group.role:
                raise ValueError("selected connector and coordination families disagree")
            labels[_bounds(connector)] = ConnectorLabel(connector, group.role)

    wrappers = tuple(
        sorted(
            {value for value in selected["wrappers"] if isinstance(value, WrapperSpan)},
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
            sorted(candidates, key=lambda value: (value.span.start, value.span.end, value.id))
        ),
        rule_ids=(
            "v7.frozen-candidate-parses",
            "v7.runtime-observable-family-router",
            *plan.trace,
            "v7.reference-closure",
            "v7.graph-projection-once",
        ),
    )


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
        fallback = _SelectionPlan(
            {family: "v6" for family in _FAMILIES},
            (
                *plan.trace,
                _trace_entry(
                    "graph-validity", "all", None, "v6", "veto:non-closed-route"
                ),
            ),
        )
        return _rebuild(source_text, category, parses, fallback)


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

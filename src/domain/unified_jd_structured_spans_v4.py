from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.domain import unified_jd_structured_spans as v3

SurfaceCategory = v3.SurfaceCategory
SourceSpan = v3.SourceSpan
ScopeKind = Literal[
    "prefix",
    "suffix",
    "predicate",
    "object",
    "domain",
    "result",
    "head",
    "evidence",
]
CoordinationRole = Literal["surface", "embedded", "example"]
ConnectorRole = Literal["surface", "embedded", "example", "quantifier"]

STRUCTURED_SPAN_PARSER_VERSION = "unified-jd-structured-span-parser-v4-development"


@dataclass(frozen=True, slots=True)
class WrapperSpan:
    kind: str
    marker_span: SourceSpan
    content_span: SourceSpan


@dataclass(frozen=True, slots=True)
class CoordinationMember:
    id: str
    span: SourceSpan
    segment_index: int


@dataclass(frozen=True, slots=True)
class CoordinationGroup:
    id: str
    role: CoordinationRole
    kind: str
    connector_spans: tuple[SourceSpan, ...]
    members: tuple[CoordinationMember, ...]


@dataclass(frozen=True, slots=True)
class SharedScope:
    id: str
    kind: ScopeKind
    span: SourceSpan
    applies_to_member_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExampleAttachment:
    id: str
    cue_span: SourceSpan
    parent_span: SourceSpan
    example_spans: tuple[SourceSpan, ...]
    segment_index: int


@dataclass(frozen=True, slots=True)
class ConnectorLabel:
    span: SourceSpan
    role: ConnectorRole


@dataclass(frozen=True, slots=True)
class ParsedClause:
    source_text: str
    category: SurfaceCategory
    protected_spans: tuple[SourceSpan, ...]
    segments: tuple[SourceSpan, ...]
    wrappers: tuple[WrapperSpan, ...]
    connector_labels: tuple[ConnectorLabel, ...]
    coordinations: tuple[CoordinationGroup, ...]
    shared_scopes: tuple[SharedScope, ...]
    example_attachments: tuple[ExampleAttachment, ...]
    item_candidates: tuple[CoordinationMember, ...]
    rule_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_text.strip():
            raise ValueError("source_text must not be empty")
        spans: list[SourceSpan] = [*self.protected_spans, *self.segments]
        spans.extend(item.marker_span for item in self.wrappers)
        spans.extend(item.content_span for item in self.wrappers)
        spans.extend(item.span for item in self.connector_labels)
        spans.extend(item.span for item in self.item_candidates)
        for group in self.coordinations:
            if len(group.members) < 2:
                raise ValueError(f"coordination {group.id} needs at least two members")
            if len(group.connector_spans) != len(group.members) - 1:
                raise ValueError(
                    f"coordination {group.id} must have one connector between members"
                )
            spans.extend(group.connector_spans)
            spans.extend(item.span for item in group.members)
        spans.extend(item.span for item in self.shared_scopes)
        for item in self.example_attachments:
            if not item.example_spans:
                raise ValueError(f"attachment {item.id} needs examples")
            spans.extend((item.cue_span, item.parent_span, *item.example_spans))
        for span in spans:
            span.validate(self.source_text)

        ids = [item.id for item in self.item_candidates]
        ids.extend(
            member.id for group in self.coordinations for member in group.members
        )
        if len(ids) != len(set(ids)):
            raise ValueError("member and candidate ids must be globally unique")
        known_ids = set(ids)
        for scope in self.shared_scopes:
            if not scope.applies_to_member_ids:
                raise ValueError(f"scope {scope.id} needs member references")
            if not set(scope.applies_to_member_ids) <= known_ids:
                raise ValueError(f"scope {scope.id} references unknown members")


@dataclass(frozen=True, slots=True)
class StructuredSurfaceExtraction:
    category: SurfaceCategory
    source_text: str
    items: tuple[str, ...]
    examples: tuple[str, ...]
    rule_ids: tuple[str, ...]
    parsed_clause: ParsedClause


@dataclass(frozen=True, slots=True)
class ConnectorToken:
    span: SourceSpan
    role: Literal["candidate", "quantifier"]


@dataclass(frozen=True, slots=True)
class TopologyAttachment:
    cue_span: SourceSpan
    parent_span: SourceSpan
    parent_region: SourceSpan
    example_spans: tuple[SourceSpan, ...]
    example_connectors: tuple[SourceSpan, ...]
    parent_members: tuple[SourceSpan, ...]
    parent_connectors: tuple[SourceSpan, ...]
    evidence_scope: SourceSpan | None
    evidence_item: SourceSpan | None


def _trim(source: str, start: int, end: int) -> SourceSpan | None:
    while start < end and (source[start].isspace() or source[start] in "，,；;:："):
        start += 1
    while start < end and (source[end - 1].isspace() or source[end - 1] in "，,；;:："):
        end -= 1
    return SourceSpan.from_bounds(source, start, end) if start < end else None


def _span(source: str, start: int, end: int) -> SourceSpan:
    result = _trim(source, start, end)
    if result is None:
        raise ValueError("empty structural span")
    return result


def _is_inside(index: int, spans: tuple[SourceSpan, ...]) -> bool:
    return any(span.start < index < span.end - 1 for span in spans)


_CONNECTORS = ("或者", "以及", "并且", "、", "与", "和", "及", "或", "/", "并")


def _is_quantifier_connector(source: str, start: int, connector: str) -> bool:
    if connector != "或":
        return False
    left = source[max(0, start - 3) : start]
    right = source[start + 1 : start + 4]
    return bool(
        (re.search(r"(?:一|若干)种$", left) and re.match(r"多种", right))
        or (left.endswith("之一") and re.match(r"多个", right))
    )


def scan_connector_tokens(
    source: str,
    *,
    protected_spans: tuple[SourceSpan, ...] = (),
    protect_quantifiers: bool = True,
) -> tuple[ConnectorToken, ...]:
    tokens: list[ConnectorToken] = []
    index = 0
    while index < len(source):
        connector = next(
            (value for value in _CONNECTORS if source.startswith(value, index)),
            None,
        )
        if connector is None:
            index += 1
            continue
        if _is_inside(index, protected_spans):
            index += len(connector)
            continue
        role: Literal["candidate", "quantifier"] = "candidate"
        if protect_quantifiers and _is_quantifier_connector(source, index, connector):
            role = "quantifier"
        tokens.append(
            ConnectorToken(
                SourceSpan.from_bounds(source, index, index + len(connector)),
                role,
            )
        )
        index += len(connector)
    return tuple(tokens)


def _ascii_token_length(source: str, index: int, direction: int) -> int:
    length = 0
    index += direction
    while (
        0 <= index < len(source) and source[index].isascii() and source[index].isalnum()
    ):
        index += direction
        length += 1
    return length


def split_coordination_span(
    source: str,
    span: SourceSpan,
    *,
    separators: tuple[str, ...] = _CONNECTORS,
    protected_spans: tuple[SourceSpan, ...] = (),
    protect_quantifiers: bool = True,
) -> tuple[tuple[SourceSpan, ...], tuple[SourceSpan, ...]]:
    allowed = tuple(sorted(separators, key=len, reverse=True))
    members: list[SourceSpan] = []
    connectors: list[SourceSpan] = []
    member_start = span.start
    index = span.start
    while index < span.end:
        connector = next(
            (
                value
                for value in allowed
                if source.startswith(value, index) and index + len(value) <= span.end
            ),
            None,
        )
        if connector is None:
            index += 1
            continue
        if _is_inside(index, protected_spans):
            index += len(connector)
            continue
        if protect_quantifiers and _is_quantifier_connector(source, index, connector):
            index += len(connector)
            continue
        if connector == "/" and (
            _ascii_token_length(source, index, -1)
            == _ascii_token_length(source, index, 1)
            == 1
        ):
            index += 1
            continue
        member = _trim(source, member_start, index)
        if member is not None:
            members.append(member)
            connectors.append(
                SourceSpan.from_bounds(source, index, index + len(connector))
            )
            member_start = index + len(connector)
        index += len(connector)
    final = _trim(source, member_start, span.end)
    if final is not None:
        members.append(final)
    if len(members) != len(connectors) + 1:
        return (span,), ()
    return tuple(members), tuple(connectors)


class _Builder:
    def __init__(
        self,
        source: str,
        category: SurfaceCategory,
        protected_spans: tuple[SourceSpan, ...],
        segments: tuple[SourceSpan, ...],
    ) -> None:
        self.source = source
        self.category = category
        self.protected_spans = protected_spans
        self.segments = segments
        self.wrappers: list[WrapperSpan] = []
        self.groups: list[CoordinationGroup] = []
        self.scopes: list[SharedScope] = []
        self.attachments: list[ExampleAttachment] = []
        self.candidates: list[CoordinationMember] = []
        self.rules: list[str] = []
        self._candidate_bounds: set[tuple[int, int]] = set()
        self._next_id = 1

    def _id(self, prefix: str) -> str:
        result = f"{prefix}-{self._next_id}"
        self._next_id += 1
        return result

    def rule(self, value: str) -> None:
        if value not in self.rules:
            self.rules.append(value)

    def wrapper(self, kind: str, marker: SourceSpan, content: SourceSpan) -> None:
        value = WrapperSpan(kind, marker, content)
        if value not in self.wrappers:
            self.wrappers.append(value)

    def candidate(self, value: SourceSpan, segment_index: int) -> CoordinationMember:
        bounds = (value.start, value.end)
        for candidate in self.candidates:
            if (candidate.span.start, candidate.span.end) == bounds:
                return candidate
        candidate = CoordinationMember(self._id("candidate"), value, segment_index)
        self.candidates.append(candidate)
        self._candidate_bounds.add(bounds)
        return candidate

    def group(
        self,
        role: CoordinationRole,
        kind: str,
        members: tuple[SourceSpan, ...],
        connectors: tuple[SourceSpan, ...],
        segment_indices: int | tuple[int, ...],
    ) -> tuple[CoordinationMember, ...]:
        if len(members) < 2:
            return ()
        indices = (
            (segment_indices,) * len(members)
            if isinstance(segment_indices, int)
            else segment_indices
        )
        values = tuple(
            CoordinationMember(self._id("member"), span, index)
            for span, index in zip(members, indices, strict=True)
        )
        self.groups.append(
            CoordinationGroup(self._id("coord"), role, kind, connectors, values)
        )
        return values

    def scope(
        self,
        kind: ScopeKind,
        value: SourceSpan,
        members: tuple[CoordinationMember, ...],
    ) -> None:
        if members:
            self.scopes.append(
                SharedScope(
                    self._id("scope"),
                    kind,
                    value,
                    tuple(member.id for member in members),
                )
            )

    def attachment(
        self,
        value: TopologyAttachment,
        segment_index: int,
    ) -> None:
        self.attachments.append(
            ExampleAttachment(
                self._id("example"),
                value.cue_span,
                value.parent_span,
                value.example_spans,
                segment_index,
            )
        )

    def build(self) -> ParsedClause:
        connector_labels: dict[tuple[int, int], ConnectorLabel] = {}
        for group in self.groups:
            for connector in group.connector_spans:
                connector_labels[(connector.start, connector.end)] = ConnectorLabel(
                    connector, group.role
                )
        for token in scan_connector_tokens(
            self.source,
            protected_spans=self.protected_spans,
            protect_quantifiers=True,
        ):
            if token.role == "quantifier":
                connector_labels[(token.span.start, token.span.end)] = ConnectorLabel(
                    token.span, "quantifier"
                )
        return ParsedClause(
            source_text=self.source,
            category=self.category,
            protected_spans=self.protected_spans,
            segments=self.segments,
            wrappers=tuple(self.wrappers),
            connector_labels=tuple(
                connector_labels[key] for key in sorted(connector_labels)
            ),
            coordinations=tuple(self.groups),
            shared_scopes=tuple(self.scopes),
            example_attachments=tuple(self.attachments),
            item_candidates=tuple(self.candidates),
            rule_ids=tuple(self.rules),
        )


def _translate_v3(parsed: v3.ParsedClause) -> ParsedClause:
    builder = _Builder(
        parsed.source_text, parsed.category, parsed.protected_spans, parsed.segments
    )
    for wrapper in parsed.wrappers:
        builder.wrapper(
            wrapper.kind.split(".")[-1], wrapper.marker_span, wrapper.content_span
        )
    old_to_new: dict[str, CoordinationMember] = {}
    for group in parsed.coordinations:
        members = builder.group(
            "surface",
            f"v3.{group.kind}",
            tuple(member.span for member in group.members),
            group.connector_spans,
            tuple(member.segment_index for member in group.members),
        )
        old_to_new.update(
            {old.id: new for old, new in zip(group.members, members, strict=True)}
        )
    for candidate in parsed.item_candidates:
        new = builder.candidate(candidate.span, candidate.segment_index)
        old_to_new.setdefault(candidate.id, new)
    for scope in parsed.shared_scopes:
        members = tuple(
            old_to_new[item_id]
            for item_id in scope.applies_to_member_ids
            if item_id in old_to_new
        )
        kind: ScopeKind = scope.kind
        if parsed.category == "experience" and scope.span.text in {
            "经验",
            "项目经验",
            "研究/项目经历",
        }:
            kind = "evidence"
        builder.scope(kind, scope.span, members)
    for attachment in parsed.example_attachments:
        builder.attachment(
            TopologyAttachment(
                attachment.cue_span,
                attachment.parent_span,
                attachment.parent_span,
                attachment.example_spans,
                (),
                (),
                (),
                None,
                None,
            ),
            attachment.segment_index,
        )
    for rule in parsed.rule_ids:
        builder.rule(f"fallback.{rule}")
    return builder.build()


def _prefix_from_v3(
    parsed: v3.ParsedClause, segment: SourceSpan
) -> tuple[SourceSpan, SourceSpan] | None:
    for wrapper in parsed.wrappers:
        if (
            wrapper.kind.endswith(".prefix")
            and wrapper.marker_span.start == segment.start
        ):
            return wrapper.marker_span, wrapper.content_span
    return None


_POSSESSION_PREFIX = re.compile(
    r"(?P<marker>(?:有|具有|具备)(?:(?:很强|良好|优秀|较强|扎实)的?)?)"
)
_ACTION_PREFIX = re.compile(
    r"(?P<marker>(?:能够(?:独立)?(?:完成)?|能|做过基于|持续优化|精通|建设|"
    r"理解|扎实的|及(?:很强|良好|优秀|较强|扎实)的?|在))"
)


def _infer_prefix(
    source: str, segment: SourceSpan, parsed: v3.ParsedClause
) -> tuple[SourceSpan, SourceSpan] | None:
    existing = _prefix_from_v3(parsed, segment)
    match = _POSSESSION_PREFIX.match(segment.text) or _ACTION_PREFIX.match(segment.text)
    if match is not None and match.end("marker") < len(segment.text):
        marker = SourceSpan.from_bounds(
            source, segment.start, segment.start + match.end("marker")
        )
        if existing is None or marker.end > existing[0].end:
            return marker, _span(source, marker.end, segment.end)
    return existing


def _strip_priority(
    source: str, span: SourceSpan
) -> tuple[SourceSpan, SourceSpan | None]:
    for suffix in ("者优先", "的优先", "优先"):
        if span.text.endswith(suffix) and len(span.text) > len(suffix):
            marker = SourceSpan.from_bounds(source, span.end - len(suffix), span.end)
            return _span(source, span.start, marker.start), marker
    return span, None


def detect_topology_attachment(
    source: str,
    body: SourceSpan,
    category: SurfaceCategory,
    *,
    protected_spans: tuple[SourceSpan, ...] = (),
) -> TopologyAttachment | None:
    if category not in {"responsibility", "experience"}:
        return None
    for cue_start in range(body.start, body.end):
        if source[cue_start] != "等" or _is_inside(cue_start, protected_spans):
            continue
        before = _trim(source, body.start, cue_start)
        tail = _trim(source, cue_start + 1, body.end)
        if before is None or tail is None:
            continue
        if re.match(r"(?:一|若干)种|[^，,；;]*之一", tail.text):
            continue
        examples, example_connectors = split_coordination_span(
            source,
            before,
            separators=("、", ","),
            protected_spans=protected_spans,
        )
        if len(examples) < 2:
            continue
        tail, _ = _strip_priority(source, tail)
        evidence_scope: SourceSpan | None = None
        evidence_item: SourceSpan | None = None
        parent_region = tail
        evidence_match = re.search(r"有(?=.+(?:论文|经验|经历|成果|记录)$)", tail.text)
        if evidence_match and evidence_match.start() > 0:
            boundary = tail.start + evidence_match.start()
            parent_region = _span(source, tail.start, boundary)
            evidence_scope = _span(source, boundary, tail.end)
            evidence_item = _span(source, boundary + 1, tail.end)
        parent_members, parent_connectors = split_coordination_span(
            source,
            parent_region,
            separators=("或者", "以及", "/", "或", "与", "和", "及"),
            protected_spans=protected_spans,
        )
        parent_span = (
            parent_region
            if any(item.text == "/" for item in parent_connectors)
            else parent_members[0]
        )
        return TopologyAttachment(
            cue_span=SourceSpan.from_bounds(source, cue_start, cue_start + 1),
            parent_span=parent_span,
            parent_region=parent_region,
            example_spans=examples,
            example_connectors=example_connectors,
            parent_members=parent_members,
            parent_connectors=parent_connectors,
            evidence_scope=evidence_scope,
            evidence_item=evidence_item,
        )
    return None


def _add_surface_sequence(
    builder: _Builder,
    body: SourceSpan,
    segment_index: int,
    *,
    separators: tuple[str, ...] = (
        "或者",
        "以及",
        "、",
        "与",
        "和",
        "及",
        "或",
        "/",
        "并",
    ),
) -> tuple[CoordinationMember, ...]:
    members, connectors = split_coordination_span(
        builder.source,
        body,
        separators=separators,
        protected_spans=builder.protected_spans,
    )
    if len(members) == 1:
        builder.candidate(body, segment_index)
        return ()
    group = builder.group(
        "surface", "v4.category_neutral_sequence", members, connectors, segment_index
    )
    for member in members:
        builder.candidate(member, segment_index)
    return group


def _add_topology_attachment(
    builder: _Builder,
    attachment: TopologyAttachment,
    segment_index: int,
) -> None:
    builder.group(
        "example",
        "v4.topology_examples",
        attachment.example_spans,
        attachment.example_connectors,
        segment_index,
    )
    parent_group = builder.group(
        "surface",
        "v4.topology_parent_sequence",
        attachment.parent_members,
        attachment.parent_connectors,
        segment_index,
    )
    for parent in attachment.parent_members:
        builder.candidate(parent, segment_index)
    if attachment.evidence_scope is not None:
        builder.scope("evidence", attachment.evidence_scope, parent_group)
    if attachment.evidence_item is not None:
        builder.candidate(attachment.evidence_item, segment_index)
    builder.attachment(attachment, segment_index)
    builder.rule("v4.topology_example_attachment")


def _parse_responsibility_v4(
    source: str, parsed: v3.ParsedClause
) -> ParsedClause | None:
    nested = re.fullmatch(
        r"(?P<left>.+?[与和及或].+?)的(?P<right>.+?[与和及或].+)", source
    )
    if nested is not None and len(parsed.segments) == 1:
        left = _span(source, *nested.span("left"))
        right = _span(source, *nested.span("right"))
        left_members, left_connectors = split_coordination_span(
            source, left, protected_spans=parsed.protected_spans
        )
        right_members, right_connectors = split_coordination_span(
            source, right, protected_spans=parsed.protected_spans
        )
        if len(left_members) > 1 and len(right_members) > 1:
            builder = _Builder(
                source, "responsibility", parsed.protected_spans, parsed.segments
            )
            left_group = builder.group(
                "surface", "v4.parallel_subjects", left_members, left_connectors, 0
            )
            builder.group(
                "surface", "v4.parallel_results", right_members, right_connectors, 0
            )
            for item in (*left_members, *right_members):
                builder.candidate(item, 0)
            builder.scope("result", right, left_group)
            builder.rule("v4.parallel_subject_result")
            return builder.build()

    has_missed_attachment = (
        any(
            detect_topology_attachment(
                source,
                (_infer_prefix(source, segment, parsed) or (None, segment))[1],
                "responsibility",
                protected_spans=parsed.protected_spans,
            )
            is not None
            for segment in parsed.segments
        )
        and not parsed.example_attachments
        and any("等" in candidate.span.text for candidate in parsed.item_candidates)
    )
    wrapper_not_consumed = any(
        any(
            candidate.span.start == wrapper.marker_span.start
            for candidate in parsed.item_candidates
        )
        for wrapper in parsed.wrappers
        if wrapper.kind.endswith(".prefix") and wrapper.marker_span.text == "负责"
    )
    inferred_action_list = any(
        re.match(r"(?:建设|持续优化)", segment.text)
        and any(value in segment.text for value in ("、", "及"))
        for segment in parsed.segments
    )
    if not (has_missed_attachment or wrapper_not_consumed or inferred_action_list):
        return None

    builder = _Builder(
        source, "responsibility", parsed.protected_spans, parsed.segments
    )
    for index, segment in enumerate(parsed.segments):
        prefix = _infer_prefix(source, segment, parsed)
        body = segment
        if prefix is not None:
            marker, body = prefix
            builder.wrapper("prefix", marker, body)
        attachment = detect_topology_attachment(
            source,
            body,
            "responsibility",
            protected_spans=parsed.protected_spans,
        )
        if attachment is not None:
            _add_topology_attachment(builder, attachment, index)
            continue
        if body.text.endswith("等") and len(body.text) > 1:
            marker = SourceSpan.from_bounds(source, body.end - 1, body.end)
            content = _span(source, segment.start, marker.start)
            builder.wrapper("open_list_suffix", marker, content)
            body = _span(source, body.start, marker.start)
        _add_surface_sequence(builder, body, index)
    builder.rule("v4.category_neutral_coordination")
    return builder.build()


def _parse_skill_v4(source: str, parsed: v3.ParsedClause) -> ParsedClause | None:
    needs_upgrade = bool(
        re.search(r"一种或多种|之一或多个|等基础知识", source)
        or re.match(r"扎实的", source)
    )
    if not needs_upgrade:
        return None
    builder = _Builder(source, "skill", parsed.protected_spans, parsed.segments)
    for index, segment in enumerate(parsed.segments):
        prefix = _infer_prefix(source, segment, parsed)
        body = segment
        if prefix is not None:
            marker, body = prefix
            builder.wrapper("prefix", marker, body)

        cue_index = body.text.find("等")
        if cue_index >= 0:
            cue_start = body.start + cue_index
            members_span = _span(source, body.start, cue_start)
            scope = _span(source, cue_start + 1, body.end)
            members, connectors = split_coordination_span(
                source,
                members_span,
                separators=("、", ",", "与", "和", "及", "或", "/"),
                protected_spans=parsed.protected_spans,
            )
            group = builder.group(
                "surface", "v4.explicit_enumeration", members, connectors, index
            )
            for member in members:
                builder.candidate(member, index)
            builder.scope("head", scope, group)
            continue

        domain_match = re.fullmatch(r"(?P<domain>.+?)的(?P<body>.+)", body.text)
        if domain_match:
            domain = _span(
                source,
                body.start + domain_match.start("domain"),
                body.start + domain_match.end("domain"),
            )
            rest = _span(
                source,
                body.start + domain_match.start("body"),
                body.start + domain_match.end("body"),
            )
            members, connectors = split_coordination_span(
                source, rest, protected_spans=parsed.protected_spans
            )
            if len(members) > 1:
                group = builder.group(
                    "surface", "v4.shared_domain", members, connectors, index
                )
                builder.scope("domain", domain, group)
                builder.candidate(
                    SourceSpan.from_bounds(source, domain.start, members[0].end), index
                )
                for member in members[1:]:
                    builder.candidate(member, index)
                continue

        shared_suffix = next(
            (
                value
                for value in ("能力", "基础")
                if body.text.endswith(value)
                and any(
                    connector in body.text for connector in ("、", "和", "与", "及")
                )
            ),
            None,
        )
        if shared_suffix is not None:
            scope = SourceSpan.from_bounds(
                source, body.end - len(shared_suffix), body.end
            )
            member_body = _span(source, body.start, scope.start)
            members, connectors = split_coordination_span(
                source, member_body, protected_spans=parsed.protected_spans
            )
            group = builder.group(
                "surface", "v4.shared_suffix", members, connectors, index
            )
            builder.scope("suffix", scope, group)
            for position, member in enumerate(members):
                if shared_suffix == "基础" and position == len(members) - 1:
                    builder.candidate(
                        SourceSpan.from_bounds(source, member.start, scope.end), index
                    )
                else:
                    builder.candidate(member, index)
            continue
        _add_surface_sequence(builder, body, index)
    builder.rule("v4.category_neutral_coordination")
    builder.rule("v4.quantifier_context_protection")
    return builder.build()


def _parse_experience_v4(source: str, parsed: v3.ParsedClause) -> ParsedClause | None:
    attachment_parts: dict[int, TopologyAttachment] = {}
    for index, segment in enumerate(parsed.segments):
        prefix = _infer_prefix(source, segment, parsed)
        body = prefix[1] if prefix else segment
        attachment = detect_topology_attachment(
            source, body, "experience", protected_spans=parsed.protected_spans
        )
        if attachment is not None:
            attachment_parts[index] = attachment

    atomic_head_was_stripped = (
        len(parsed.item_candidates) == 1
        and source.endswith("项目经验")
        and parsed.item_candidates[0].span.end < len(source)
        and not any(value in source for value in ("、", "与", "和", "或", "/"))
    )
    evidence_sequences = bool(
        re.search(r"有(?:真实的)?(?:动手|实践)经验", source) or "相关的项目" in source
    ) and any(
        candidate.span.text.endswith(("动手", "相关的项目"))
        or "、" in candidate.span.text
        or "/" in candidate.span.text
        for candidate in parsed.item_candidates
    )
    if not (attachment_parts or atomic_head_was_stripped or evidence_sequences):
        return None

    builder = _Builder(source, "experience", parsed.protected_spans, parsed.segments)
    for index, segment in enumerate(parsed.segments):
        prefix = _infer_prefix(source, segment, parsed)
        body = segment
        if prefix is not None:
            marker, body = prefix
            builder.wrapper("prefix", marker, body)
        body, priority = _strip_priority(source, body)
        if priority is not None:
            builder.wrapper(
                "suffix", priority, _span(source, segment.start, priority.start)
            )

        attachment = attachment_parts.get(index)
        if attachment is not None:
            _add_topology_attachment(builder, attachment, index)
            continue

        evidence_match = re.fullmatch(
            r"(?P<members>.+?)(?P<scope>有(?:真实的)?(?:动手|实践)经验|相关的项目)",
            body.text,
        )
        if evidence_match:
            members_span = _span(
                source,
                body.start + evidence_match.start("members"),
                body.start + evidence_match.end("members"),
            )
            scope = _span(
                source,
                body.start + evidence_match.start("scope"),
                body.start + evidence_match.end("scope"),
            )
            members, connectors = split_coordination_span(
                source, members_span, protected_spans=parsed.protected_spans
            )
            group = builder.group(
                "surface", "v4.shared_evidence", members, connectors, index
            )
            for member in members:
                builder.candidate(member, index)
            builder.scope("evidence", scope, group)
            continue
        builder.candidate(body, index)
    builder.rule("v4.experience_head_cardinality")
    return builder.build()


_EVALUATIVE_SUFFIX = re.compile(r"(?P<body>.+?)(?P<marker>强|积极|良好)$")


def _parse_capability_v4(source: str, parsed: v3.ParsedClause) -> ParsedClause | None:
    has_parallel_predicates = any(
        len(parts) > 1
        and all(_EVALUATIVE_SUFFIX.fullmatch(part.text) for part in parts)
        for segment in parsed.segments
        for parts, _ in (
            split_coordination_span(
                source,
                segment,
                separators=("、",),
                protected_spans=parsed.protected_spans,
            ),
        )
    )
    has_retained_ability_wrapper = any(
        candidate.span.text.startswith(("有", "具有", "具备", "及"))
        and candidate.span.text.endswith("能力")
        for candidate in parsed.item_candidates
    )
    has_action_sequence = any(
        "并" in candidate.span.text for candidate in parsed.item_candidates
    )
    has_scoped_completion = source.startswith("能够独立完成")
    needs_upgrade = (
        has_parallel_predicates
        or has_retained_ability_wrapper
        or has_action_sequence
        or has_scoped_completion
    )
    if not needs_upgrade:
        return None
    builder = _Builder(source, "capability", parsed.protected_spans, parsed.segments)
    segment_candidates: list[tuple[int, CoordinationMember]] = []
    leading_intersegment_connector: SourceSpan | None = None
    for index, segment in enumerate(parsed.segments):
        parts, connectors = split_coordination_span(
            source,
            segment,
            separators=("、",),
            protected_spans=parsed.protected_spans,
        )
        if len(parts) > 1 and all(
            _EVALUATIVE_SUFFIX.fullmatch(part.text) for part in parts
        ):
            cores: list[SourceSpan] = []
            for part in parts:
                match = _EVALUATIVE_SUFFIX.fullmatch(part.text)
                assert match is not None
                core = _span(
                    source,
                    part.start + match.start("body"),
                    part.start + match.end("body"),
                )
                marker = _span(
                    source,
                    part.start + match.start("marker"),
                    part.start + match.end("marker"),
                )
                builder.wrapper("suffix", marker, core)
                builder.candidate(core, index)
                cores.append(core)
            builder.group(
                "surface", "v4.parallel_predicates", tuple(cores), connectors, index
            )
            continue

        prefix = _infer_prefix(source, segment, parsed)
        body = segment
        if prefix is not None:
            marker, body = prefix
            builder.wrapper("prefix", marker, body)
            if marker.text.startswith("及"):
                leading_intersegment_connector = SourceSpan.from_bounds(
                    source, marker.start, marker.start + 1
                )

        suffix: SourceSpan | None = None
        if body.text.endswith("能力") and len(body.text) > len("能力"):
            suffix = SourceSpan.from_bounds(source, body.end - 2, body.end)
            body = _span(source, body.start, suffix.start)
            builder.wrapper(
                "suffix", suffix, _span(source, segment.start, suffix.start)
            )
        else:
            evaluative = _EVALUATIVE_SUFFIX.fullmatch(body.text)
            if evaluative is not None:
                marker = _span(
                    source,
                    body.start + evaluative.start("marker"),
                    body.start + evaluative.end("marker"),
                )
                body = _span(
                    source,
                    body.start + evaluative.start("body"),
                    body.start + evaluative.end("body"),
                )
                builder.wrapper("suffix", marker, body)

        action_members, action_connectors = split_coordination_span(
            source,
            body,
            separators=("、", "和", "与", "及", "并"),
            protected_spans=parsed.protected_spans,
        )
        if len(action_members) > 1:
            builder.group(
                "surface",
                "v4.action_sequence",
                action_members,
                action_connectors,
                index,
            )
            for member in action_members:
                builder.candidate(member, index)
            for member in action_members:
                embedded_span = member
                embedded_match = re.search(
                    r"(?:到|在)(?P<body>[^到在]+?(?:或者|或)[^到在]+?)(?:中|内|上)$",
                    member.text,
                )
                if embedded_match is not None:
                    embedded_span = _span(
                        source,
                        member.start + embedded_match.start("body"),
                        member.start + embedded_match.end("body"),
                    )
                embedded_members, embedded_connectors = split_coordination_span(
                    source,
                    embedded_span,
                    separators=("或者", "或"),
                    protected_spans=parsed.protected_spans,
                )
                if len(embedded_members) > 1:
                    builder.group(
                        "embedded",
                        "v4.embedded_alternative",
                        embedded_members,
                        embedded_connectors,
                        index,
                    )
            continue
        candidate = builder.candidate(body, index)
        segment_candidates.append((index, candidate))

    if leading_intersegment_connector is not None and len(segment_candidates) == 2:
        builder.group(
            "surface",
            "v4.intersegment_coordination",
            tuple(item.span for _, item in segment_candidates),
            (leading_intersegment_connector,),
            tuple(index for index, _ in segment_candidates),
        )
    builder.rule("v4.category_neutral_coordination")
    return builder.build()


def parse_clause(source_text: str, category: SurfaceCategory) -> ParsedClause:
    if not source_text.strip():
        raise ValueError("source_text must not be empty")
    parsed_v3 = v3.parse_clause(source_text, category)
    upgraded: ParsedClause | None = None
    if category == "responsibility":
        upgraded = _parse_responsibility_v4(source_text, parsed_v3)
    elif category == "skill":
        upgraded = _parse_skill_v4(source_text, parsed_v3)
    elif category == "experience":
        upgraded = _parse_experience_v4(source_text, parsed_v3)
    elif category == "capability":
        upgraded = _parse_capability_v4(source_text, parsed_v3)
    return upgraded if upgraded is not None else _translate_v3(parsed_v3)


def _unique(spans: tuple[SourceSpan, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for span in spans:
        key = span.text.casefold()
        if key not in seen:
            result.append(span.text)
            seen.add(key)
    return tuple(result)


def project_surface_items(parsed_clause: ParsedClause) -> StructuredSurfaceExtraction:
    items = tuple(candidate.span for candidate in parsed_clause.item_candidates)
    examples = tuple(
        example
        for attachment in parsed_clause.example_attachments
        if any(
            candidate.start < attachment.parent_span.end
            and attachment.parent_span.start < candidate.end
            for candidate in items
        )
        for example in attachment.example_spans
    )
    return StructuredSurfaceExtraction(
        category=parsed_clause.category,
        source_text=parsed_clause.source_text,
        items=_unique(items),
        examples=_unique(examples),
        rule_ids=parsed_clause.rule_ids,
        parsed_clause=parsed_clause,
    )


def extract_surface_items(
    source_text: str, category: SurfaceCategory
) -> StructuredSurfaceExtraction:
    return project_surface_items(parse_clause(source_text, category))

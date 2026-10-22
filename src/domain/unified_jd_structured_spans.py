from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SurfaceCategory = Literal["responsibility", "skill", "experience", "capability"]
ScopeKind = Literal[
    "prefix", "suffix", "predicate", "object", "domain", "result", "head"
]

STRUCTURED_SPAN_PARSER_VERSION = "unified-jd-structured-span-parser-v3"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A half-open, exact slice of one clause's source text."""

    text: str
    start: int
    end: int

    @classmethod
    def from_bounds(cls, source_text: str, start: int, end: int) -> SourceSpan:
        if not 0 <= start < end <= len(source_text):
            raise ValueError(f"invalid source span [{start}:{end}]")
        return cls(text=source_text[start:end], start=start, end=end)

    def validate(self, source_text: str) -> None:
        if not 0 <= self.start < self.end <= len(source_text):
            raise ValueError(f"invalid source span [{self.start}:{self.end}]")
        if source_text[self.start : self.end] != self.text:
            raise ValueError(f"span text is not source-anchored: {self.text!r}")


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
class ParsedClause:
    source_text: str
    category: SurfaceCategory
    protected_spans: tuple[SourceSpan, ...]
    segments: tuple[SourceSpan, ...]
    wrappers: tuple[WrapperSpan, ...]
    coordinations: tuple[CoordinationGroup, ...]
    shared_scopes: tuple[SharedScope, ...]
    example_attachments: tuple[ExampleAttachment, ...]
    item_candidates: tuple[CoordinationMember, ...]
    rule_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_text.strip():
            raise ValueError("source_text must not be empty")

        spans: list[SourceSpan] = [*self.protected_spans, *self.segments]
        spans.extend(wrapper.marker_span for wrapper in self.wrappers)
        spans.extend(wrapper.content_span for wrapper in self.wrappers)
        spans.extend(member.span for member in self.item_candidates)
        for group in self.coordinations:
            spans.extend(group.connector_spans)
            spans.extend(member.span for member in group.members)
        for scope in self.shared_scopes:
            spans.append(scope.span)
        for attachment in self.example_attachments:
            spans.extend(
                [attachment.cue_span, attachment.parent_span, *attachment.example_spans]
            )
        for span in spans:
            span.validate(self.source_text)

        candidate_ids = {member.id for member in self.item_candidates}
        if len(candidate_ids) != len(self.item_candidates):
            raise ValueError("item candidate ids must be unique")
        if any(
            not 0 <= member.segment_index < len(self.segments)
            for member in self.item_candidates
        ):
            raise ValueError("item candidate references an unknown segment")

        coordination_ids = {group.id for group in self.coordinations}
        if len(coordination_ids) != len(self.coordinations):
            raise ValueError("coordination ids must be unique")
        for group in self.coordinations:
            if len(group.members) < 2:
                raise ValueError(
                    f"coordination {group.id} must have at least two members"
                )
            if len(group.connector_spans) != len(group.members) - 1:
                raise ValueError(
                    f"coordination {group.id} must have one connector between members"
                )
            group_ids = {member.id for member in group.members}
            if not group_ids <= candidate_ids:
                raise ValueError(f"coordination {group.id} references unknown members")

        scope_ids = {scope.id for scope in self.shared_scopes}
        if len(scope_ids) != len(self.shared_scopes):
            raise ValueError("shared scope ids must be unique")
        for scope in self.shared_scopes:
            if not scope.applies_to_member_ids:
                raise ValueError(f"shared scope {scope.id} has no members")
            if not set(scope.applies_to_member_ids) <= candidate_ids:
                raise ValueError(f"shared scope {scope.id} references unknown members")

        attachment_ids = {attachment.id for attachment in self.example_attachments}
        if len(attachment_ids) != len(self.example_attachments):
            raise ValueError("example attachment ids must be unique")
        for attachment in self.example_attachments:
            if not 0 <= attachment.segment_index < len(self.segments):
                raise ValueError(
                    f"example attachment {attachment.id} references an unknown segment"
                )
            if not attachment.example_spans:
                raise ValueError(f"example attachment {attachment.id} has no examples")
            segment = self.segments[attachment.segment_index]
            local_spans = (attachment.cue_span, *attachment.example_spans)
            if any(
                span.start < segment.start or span.end > segment.end
                for span in local_spans
            ):
                raise ValueError(
                    f"example attachment {attachment.id} crosses its local segment"
                )


@dataclass(frozen=True, slots=True)
class StructuredSurfaceExtraction:
    category: SurfaceCategory
    source_text: str
    items: tuple[str, ...]
    examples: tuple[str, ...]
    rule_ids: tuple[str, ...]
    parsed_clause: ParsedClause


def _trim_span(source_text: str, start: int, end: int) -> SourceSpan | None:
    while start < end and source_text[start].isspace():
        start += 1
    while start < end and source_text[end - 1].isspace():
        end -= 1
    while start < end and source_text[start] in "，,、；;。:：":
        start += 1
    while start < end and source_text[end - 1] in "，,、；;。:：":
        end -= 1
    return SourceSpan.from_bounds(source_text, start, end) if start < end else None


def _match_span(
    source_text: str,
    base: int,
    match: re.Match[str],
    group: str,
) -> SourceSpan:
    start, end = match.span(group)
    span = _trim_span(source_text, base + start, base + end)
    if span is None:
        raise ValueError(f"empty regex group: {group}")
    return span


def _scan_parentheses(source_text: str) -> tuple[SourceSpan, ...]:
    pairs = {"（": "）", "(": ")"}
    stack: list[tuple[str, int]] = []
    spans: list[SourceSpan] = []
    for index, character in enumerate(source_text):
        if character in pairs:
            stack.append((character, index))
        elif character in "）)" and stack and pairs[stack[-1][0]] == character:
            _, start = stack.pop()
            if not stack:
                spans.append(SourceSpan.from_bounds(source_text, start, index + 1))
    return tuple(spans)


def _inside(index: int, protected_spans: tuple[SourceSpan, ...]) -> bool:
    return any(span.start < index < span.end - 1 for span in protected_spans)


def _split_top_level(
    source_text: str,
    protected_spans: tuple[SourceSpan, ...],
) -> tuple[SourceSpan, ...]:
    result: list[SourceSpan] = []
    start = 0
    for index, character in enumerate(source_text):
        if character not in "，,；;" or _inside(index, protected_spans):
            continue
        span = _trim_span(source_text, start, index)
        if span is not None:
            result.append(span)
        start = index + 1
    final = _trim_span(source_text, start, len(source_text))
    if final is not None:
        result.append(final)
    return tuple(result)


def _ascii_token_length(text: str, index: int, direction: int) -> int:
    length = 0
    index += direction
    while 0 <= index < len(text) and text[index].isascii() and text[index].isalnum():
        length += 1
        index += direction
    return length


def _is_coordination_separator(
    source_text: str,
    index: int,
    separator: str,
    protected_spans: tuple[SourceSpan, ...],
    honor_protected: bool,
) -> bool:
    if honor_protected and _inside(index, protected_spans):
        return False
    if separator == "与" and index > 0 and source_text[index - 1] == "参":
        return False
    if separator == "/":
        left = _ascii_token_length(source_text, index, -1)
        right = _ascii_token_length(source_text, index, 1)
        if left == right == 1:
            return False
    return True


def _split_coordination_span(
    source_text: str,
    span: SourceSpan,
    protected_spans: tuple[SourceSpan, ...],
    separators: tuple[str, ...] = ("、", "或", "与", "和", "及", "/"),
    *,
    honor_protected: bool = True,
) -> tuple[tuple[SourceSpan, ...], tuple[SourceSpan, ...]]:
    separators = tuple(sorted(separators, key=len, reverse=True))
    members: list[SourceSpan] = []
    connectors: list[SourceSpan] = []
    member_start = span.start
    index = span.start
    while index < span.end:
        separator = next(
            (
                value
                for value in separators
                if source_text.startswith(value, index)
                and _is_coordination_separator(
                    source_text,
                    index,
                    value,
                    protected_spans,
                    honor_protected,
                )
            ),
            None,
        )
        if separator is None:
            index += 1
            continue
        member = _trim_span(source_text, member_start, index)
        if member is not None:
            members.append(member)
            connectors.append(
                SourceSpan.from_bounds(source_text, index, index + len(separator))
            )
        index += len(separator)
        member_start = index
    member = _trim_span(source_text, member_start, span.end)
    if member is not None:
        members.append(member)
    if len(members) != len(connectors) + 1:
        return (span,), ()
    return tuple(members), tuple(connectors)


class _ClauseBuilder:
    def __init__(self, source_text: str, category: SurfaceCategory) -> None:
        self.source_text = source_text
        self.category = category
        self.protected_spans = _scan_parentheses(source_text)
        self.segments = _split_top_level(source_text, self.protected_spans)
        self.wrappers: list[WrapperSpan] = []
        self.coordinations: list[CoordinationGroup] = []
        self.shared_scopes: list[SharedScope] = []
        self.example_attachments: list[ExampleAttachment] = []
        self.candidates: list[CoordinationMember] = []
        self.rules: list[str] = []
        self._candidate_by_bounds: dict[tuple[int, int], CoordinationMember] = {}

    def add_rule(self, rule_id: str) -> None:
        if rule_id not in self.rules:
            self.rules.append(rule_id)

    def add_wrapper(
        self,
        kind: str,
        marker_span: SourceSpan,
        content_span: SourceSpan,
    ) -> None:
        wrapper = WrapperSpan(kind, marker_span, content_span)
        if wrapper not in self.wrappers:
            self.wrappers.append(wrapper)

    def add_candidate(self, span: SourceSpan, segment_index: int) -> CoordinationMember:
        key = (span.start, span.end)
        existing = self._candidate_by_bounds.get(key)
        if existing is not None:
            return existing
        member = CoordinationMember(
            id=f"item-{len(self.candidates) + 1}",
            span=span,
            segment_index=segment_index,
        )
        self.candidates.append(member)
        self._candidate_by_bounds[key] = member
        return member

    def add_group(
        self,
        kind: str,
        spans: tuple[SourceSpan, ...],
        connectors: tuple[SourceSpan, ...],
        segment_index: int,
        *,
        scope: tuple[ScopeKind, SourceSpan] | None = None,
    ) -> tuple[CoordinationMember, ...]:
        members = tuple(self.add_candidate(span, segment_index) for span in spans)
        if len(members) > 1:
            group = CoordinationGroup(
                id=f"coord-{len(self.coordinations) + 1}",
                kind=kind,
                connector_spans=connectors,
                members=members,
            )
            self.coordinations.append(group)
        if scope is not None:
            self.shared_scopes.append(
                SharedScope(
                    id=f"scope-{len(self.shared_scopes) + 1}",
                    kind=scope[0],
                    span=scope[1],
                    applies_to_member_ids=tuple(member.id for member in members),
                )
            )
        return members

    def add_attachment(
        self,
        cue_span: SourceSpan,
        parent_span: SourceSpan,
        example_spans: tuple[SourceSpan, ...],
        segment_index: int,
    ) -> None:
        key = (
            cue_span.start,
            parent_span.start,
            tuple((span.start, span.end) for span in example_spans),
        )
        for attachment in self.example_attachments:
            current = (
                attachment.cue_span.start,
                attachment.parent_span.start,
                tuple((span.start, span.end) for span in attachment.example_spans),
            )
            if current == key:
                return
        self.example_attachments.append(
            ExampleAttachment(
                id=f"example-{len(self.example_attachments) + 1}",
                cue_span=cue_span,
                parent_span=parent_span,
                example_spans=example_spans,
                segment_index=segment_index,
            )
        )

    def build(self) -> ParsedClause:
        return ParsedClause(
            source_text=self.source_text,
            category=self.category,
            protected_spans=self.protected_spans,
            segments=self.segments,
            wrappers=tuple(self.wrappers),
            coordinations=tuple(self.coordinations),
            shared_scopes=tuple(self.shared_scopes),
            example_attachments=tuple(self.example_attachments),
            item_candidates=tuple(self.candidates),
            rule_ids=tuple(self.rules),
        )


_PREFIX_WRAPPERS: dict[SurfaceCategory, tuple[str, ...]] = {
    "responsibility": (
        "方向包括但不限于",
        "设计并优化",
        "持续提升",
        "深入了解",
        "重点突破",
        "不断优化",
        "并研究",
        "并结合",
        "并进行",
        "设计基于",
        "参与过",
        "从事",
        "负责",
        "针对",
        "构建",
        "提炼",
        "设计",
        "跟踪",
        "推动",
        "通过",
        "评估",
        "进行",
        "参与",
        "探索",
        "研究",
        "保障",
    ),
    "skill": (
        "熟悉至少一种",
        "熟练掌握",
        "理解并掌握",
        "关注并使用",
        "具备扎实的",
        "熟悉当前",
        "深入理解",
        "包括",
        "掌握",
        "熟悉",
        "了解",
        "对",
    ),
    "experience": ("或参与过", "使用过", "具有", "具备", "有", "对"),
    "capability": (
        "具备良好的",
        "具备较强的",
        "具备一定的",
        "具备良好",
        "能够",
        "愿意深入",
        "擅长",
        "进行",
        "能",
        "对待",
        "极强",
        "良好",
    ),
}


def _detect_wrappers(builder: _ClauseBuilder) -> None:
    suffixes = ("者优先", "的优先", "优先")
    for segment in builder.segments:
        segment_index = builder.segments.index(segment)
        prefix = next(
            (
                value
                for value in _PREFIX_WRAPPERS[builder.category]
                if segment.text.startswith(value) and len(segment.text) > len(value)
            ),
            None,
        )
        if prefix is not None:
            marker = SourceSpan.from_bounds(
                builder.source_text,
                segment.start,
                segment.start + len(prefix),
            )
            content = _trim_span(builder.source_text, marker.end, segment.end)
            if content is not None:
                builder.add_wrapper(f"{builder.category}.prefix", marker, content)
        suffix = next(
            (value for value in suffixes if segment.text.endswith(value)),
            None,
        )
        if suffix is not None:
            marker = SourceSpan.from_bounds(
                builder.source_text,
                segment.end - len(suffix),
                segment.end,
            )
            content = _trim_span(builder.source_text, segment.start, marker.start)
            if content is not None:
                builder.add_wrapper(f"{builder.category}.suffix", marker, content)
        if prefix is not None or suffix is not None:
            builder.add_rule(f"structure.wrapper.segment-{segment_index}")


_PREPOSED_EXAMPLE_PARENT = re.compile(
    r"\s*(?P<parent>Physical AI系统|GPU 编程与优化|AI Coding工具|AI 工具|"
    r"深度学习框架使用经验|算法在.+?中的应用|开源项目)"
    r"(?:者优先)?$"
)


def _example_members(
    builder: _ClauseBuilder,
    span: SourceSpan,
) -> tuple[SourceSpan, ...]:
    body = span
    if body.text.endswith("等"):
        body = SourceSpan.from_bounds(
            builder.source_text,
            body.start,
            body.end - 1,
        )
    members, _ = _split_coordination_span(
        builder.source_text,
        body,
        builder.protected_spans,
        separators=("、", "或", "与", "和", "/", ","),
        honor_protected=False,
    )
    return members


def _nearest_parent_before(
    builder: _ClauseBuilder,
    segment: SourceSpan,
    before: int,
) -> SourceSpan | None:
    start = segment.start
    text = builder.source_text[start:before]
    text = re.sub(r"(?:者)?优先$", "", text).rstrip()
    start_match = re.search(
        r"(?:从事|负责|熟悉|了解|掌握|熟练掌握|有良好的?|使用过|有)\s*",
        text,
    )
    if start_match:
        start += start_match.end()
        text = builder.source_text[start:before]
    candidates = re.split(r"[、，,]", text)
    nearest = candidates[-1].strip()
    if not nearest:
        return None
    nearest_start = builder.source_text.rfind(nearest, start, before)
    return SourceSpan.from_bounds(
        builder.source_text,
        nearest_start,
        nearest_start + len(nearest),
    )


def _detect_example_attachments(builder: _ClauseBuilder) -> None:
    source_text = builder.source_text
    for segment_index, segment in enumerate(builder.segments):
        segment_text = segment.text

        for protected in builder.protected_spans:
            if not segment.start <= protected.start or protected.end > segment.end:
                continue
            body_start = protected.start + 1
            body_end = protected.end - 1
            body_text = source_text[body_start:body_end]
            if "至少一种" in source_text[segment.start : protected.start]:
                continue
            cue_start = body_start
            if body_text.startswith("如"):
                cue_end = body_start + 1
                examples_start = cue_end
                while (
                    examples_start < body_end and source_text[examples_start] in ":："
                ):
                    examples_start += 1
                parent = _nearest_parent_before(builder, segment, protected.start)
            elif (
                "/" in body_text
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9 +.-]*", body_text)
                or re.search(
                    r"[A-Za-z][A-Za-z0-9 +.-]*$",
                    source_text[segment.start : protected.start],
                )
            ):
                cue_start = protected.start
                cue_end = protected.start + 1
                examples_start = body_start
                parent = _nearest_parent_before(builder, segment, protected.start)
            else:
                continue
            if parent is None or examples_start >= body_end:
                continue
            cue = SourceSpan.from_bounds(source_text, cue_start, cue_end)
            examples_body = SourceSpan.from_bounds(
                source_text, examples_start, body_end
            )
            examples = _example_members(builder, examples_body)
            builder.add_attachment(cue, parent, examples, segment_index)

        introduced = re.match(r"如\s*[:：]?\s*(?P<body>.+)$", segment_text)
        if introduced and segment_index > 0:
            previous = builder.segments[segment_index - 1]
            parent = _nearest_parent_before(builder, previous, previous.end)
            if parent is not None:
                body = _match_span(source_text, segment.start, introduced, "body")
                cue_end = segment.start + introduced.start("body")
                cue = SourceSpan.from_bounds(source_text, segment.start, cue_end)
                builder.add_attachment(
                    cue,
                    parent,
                    _example_members(builder, body),
                    segment_index,
                )

        for cue_match in re.finditer("等", segment_text):
            cue_start = segment.start + cue_match.start()
            parent_match = _PREPOSED_EXAMPLE_PARENT.match(
                source_text[cue_start + 1 : segment.end]
            )
            if parent_match is None:
                continue
            parent = _match_span(
                source_text,
                cue_start + 1,
                parent_match,
                "parent",
            )
            before = source_text[segment.start : cue_start]
            prefix_match = re.match(
                r"(?:针对|并研究|研究|熟悉|关注并使用|使用过|有|或参与过)\s*",
                before,
            )
            example_start = segment.start + (prefix_match.end() if prefix_match else 0)
            example_body = _trim_span(source_text, example_start, cue_start)
            if example_body is None:
                continue
            examples = _example_members(builder, example_body)
            if len(examples) < 2:
                continue
            cue = SourceSpan.from_bounds(source_text, cue_start, cue_start + 1)
            builder.add_attachment(cue, parent, examples, segment_index)

    if builder.example_attachments:
        builder.add_rule("structure.example_attachment")


def _content_after_prefix(
    builder: _ClauseBuilder,
    segment: SourceSpan,
    prefixes: tuple[str, ...],
) -> SourceSpan:
    prefix = next((value for value in prefixes if segment.text.startswith(value)), "")
    span = _trim_span(builder.source_text, segment.start + len(prefix), segment.end)
    if span is None:
        raise ValueError("wrapper consumed an entire segment")
    return span


def _span_without_suffix(
    builder: _ClauseBuilder,
    span: SourceSpan,
    suffixes: tuple[str, ...],
) -> tuple[SourceSpan, SourceSpan | None]:
    suffix = next((value for value in suffixes if span.text.endswith(value)), None)
    if suffix is None:
        return span, None
    body = _trim_span(builder.source_text, span.start, span.end - len(suffix))
    if body is None:
        raise ValueError("suffix consumed an entire span")
    return body, SourceSpan.from_bounds(
        builder.source_text,
        span.end - len(suffix),
        span.end,
    )


def _add_split(
    builder: _ClauseBuilder,
    span: SourceSpan,
    segment_index: int,
    rule_id: str,
    *,
    separators: tuple[str, ...] = ("、", "或", "与", "和", "及", "/"),
    scope: tuple[ScopeKind, SourceSpan] | None = None,
    honor_protected: bool = True,
) -> tuple[CoordinationMember, ...]:
    spans, connectors = _split_coordination_span(
        builder.source_text,
        span,
        builder.protected_spans,
        separators,
        honor_protected=honor_protected,
    )
    builder.add_rule(rule_id)
    return builder.add_group(
        rule_id,
        spans,
        connectors,
        segment_index,
        scope=scope,
    )


def _find_parenthetical_start(builder: _ClauseBuilder, span: SourceSpan) -> int | None:
    starts = [
        protected.start
        for protected in builder.protected_spans
        if span.start <= protected.start and protected.end <= span.end
    ]
    return min(starts) if starts else None


def _parse_responsibility(builder: _ClauseBuilder) -> None:
    source_text = builder.source_text

    full = re.fullmatch(r"设计基于(?P<body>.+?)的解决方案", source_text)
    if full:
        body = _match_span(source_text, 0, full, "body")
        _add_split(builder, body, 0, "responsibility.solution_inputs")
        return

    full = re.fullmatch(r"从事(?P<domain>.+?)的(?P<body>.+)", source_text)
    if full:
        domain = _match_span(source_text, 0, full, "domain")
        body = _match_span(source_text, 0, full, "body")
        spans, connectors = _split_coordination_span(
            source_text,
            body,
            builder.protected_spans,
            separators=("、", "及"),
        )
        clean_spans: list[SourceSpan] = []
        for span in spans:
            protected_start = _find_parenthetical_start(builder, span)
            clean_spans.append(
                SourceSpan.from_bounds(source_text, span.start, protected_start)
                if protected_start is not None
                else span
            )
        builder.add_group(
            "responsibility.shared_domain",
            tuple(clean_spans),
            connectors,
            0,
            scope=("domain", domain),
        )
        builder.add_rule("responsibility.shared_domain")
        return

    full = re.fullmatch(r"负责(?P<object>.+?)的(?P<body>.+)", source_text)
    if full:
        object_span = _match_span(source_text, 0, full, "object")
        builder.add_candidate(object_span, 0)
        builder.add_rule("responsibility.owned_object")

    for segment_index, segment in enumerate(builder.segments):
        text = segment.text
        if text.startswith("针对"):
            attachment = next(
                (
                    item
                    for item in builder.example_attachments
                    if item.segment_index == segment_index
                ),
                None,
            )
            if attachment is not None:
                builder.add_candidate(attachment.parent_span, segment_index)
                builder.add_rule("responsibility.context_upper")
            else:
                builder.add_rule("responsibility.context_only")
            continue

        if text.startswith("包括") and any(
            later.text.startswith("包括")
            for later in builder.segments[segment_index + 1 :]
        ):
            builder.add_rule("responsibility.explanatory_restatement")
            continue

        match = re.fullmatch(r"构建(?P<body>.+)", text)
        if match:
            builder.add_candidate(
                _match_span(source_text, segment.start, match, "body"), segment_index
            )
            builder.add_rule("responsibility.action_object")
            continue

        match = re.fullmatch(r"并结合(?P<body>.+)", text)
        if match:
            builder.add_candidate(
                _match_span(source_text, segment.start, match, "body"), segment_index
            )
            builder.add_rule("responsibility.action_object")
            continue

        match = re.fullmatch(r"(?:不断)?优化(?P<body>.+?)(?P<scope>的整体效果)", text)
        if match:
            body = _match_span(source_text, segment.start, match, "body")
            scope = _match_span(source_text, segment.start, match, "scope")
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.shared_result",
                scope=("result", scope),
            )
            continue

        match = re.fullmatch(r"深入了解.+实际问题", text)
        if match:
            builder.add_candidate(segment, segment_index)
            builder.add_rule("responsibility.scoped_problem")
            continue

        action_parts = re.split(r"并(?=(?:设计|推动|定位|开展|实现|持续优化))", text)
        if len(action_parts) > 1:
            spans: list[SourceSpan] = []
            connectors: list[SourceSpan] = []
            offset = segment.start
            for part_index, part in enumerate(action_parts):
                part_start = source_text.find(part, offset, segment.end)
                spans.append(
                    SourceSpan.from_bounds(
                        source_text, part_start, part_start + len(part)
                    )
                )
                offset = part_start + len(part)
                if part_index < len(action_parts) - 1:
                    connector_start = offset
                    connectors.append(
                        SourceSpan.from_bounds(
                            source_text, connector_start, connector_start + 1
                        )
                    )
                    offset += 1
            builder.add_group(
                "responsibility.multi_action",
                tuple(spans),
                tuple(connectors),
                segment_index,
            )
            builder.add_rule("responsibility.multi_action")
            continue

        match = re.fullmatch(r"跟踪(?P<body>.+?)的(?P<scope>国际前沿技术动态)", text)
        if match:
            body = _match_span(source_text, segment.start, match, "body")
            scope = _match_span(source_text, segment.start, match, "scope")
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.frontier_domains",
                scope=("predicate", scope),
            )
            continue

        match = re.fullmatch(r"推动(?P<subject>.+?)在(?P<result>.+?中的落地应用)", text)
        if match:
            subject = _match_span(source_text, segment.start, match, "subject")
            result = _match_span(source_text, segment.start, match, "result")
            builder.add_candidate(subject, segment_index)
            builder.add_candidate(result, segment_index)
            builder.add_rule("responsibility.subject_and_result")
            continue

        match = re.fullmatch(
            r"(?:重点)?突破(?P<body>.+?)等(?P<scope>方向的应用创新)", text
        )
        if match:
            body = _match_span(source_text, segment.start, match, "body")
            scope = _match_span(source_text, segment.start, match, "scope")
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.innovation_directions",
                scope=("suffix", scope),
            )
            continue

        match = re.fullmatch(r"通过(?P<body>.+)", text)
        if match:
            _add_split(
                builder,
                _match_span(source_text, segment.start, match, "body"),
                segment_index,
                "responsibility.means",
                separators=("、", "和", "或", "与", "/"),
            )
            continue

        match = re.fullmatch(r"(?:并)?(?:进行)(?P<body>.+)", text)
        if match:
            body = _match_span(source_text, segment.start, match, "body")
            assessment = re.fullmatch(r"(?P<items>.+?)的(?P<scope>安全评估)", body.text)
            if assessment:
                items = _match_span(source_text, body.start, assessment, "items")
                scope = _match_span(source_text, body.start, assessment, "scope")
                _add_split(
                    builder,
                    items,
                    segment_index,
                    "responsibility.assessment_targets",
                    scope=("predicate", scope),
                )
            else:
                builder.add_candidate(body, segment_index)
                builder.add_rule("responsibility.action_object")
            continue

        match = re.fullmatch(
            r"设计并优化\s*.+?的\s*(?P<body>.+?)\s*等(?P<scope>关键模块)",
            text,
        )
        if match:
            body = _match_span(source_text, segment.start, match, "body")
            scope = _match_span(source_text, segment.start, match, "scope")
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.key_modules",
                scope=("suffix", scope),
            )
            continue

        if text.startswith("负责") and full:
            nested_body = _match_span(source_text, 0, full, "body")
            direct_end = nested_body.end
            include = source_text.find("，包括", nested_body.start, nested_body.end)
            if include >= 0:
                direct_end = include
            direct = SourceSpan.from_bounds(source_text, nested_body.start, direct_end)
            _add_split(
                builder,
                direct,
                segment_index,
                "responsibility.owned_actions",
                separators=("、", "与", "和", "或"),
            )
            continue

        if text.startswith("包括"):
            body = _content_after_prefix(builder, segment, ("包括",))
            nested = body.text.rfind("包括")
            if nested >= 0:
                body = SourceSpan.from_bounds(
                    source_text,
                    body.start + nested + len("包括"),
                    body.end,
                )
            body, scope = _span_without_suffix(builder, body, ("等",))
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.included_members",
                separators=("、", "与", "和", "或"),
                scope=("suffix", scope) if scope else None,
            )
            continue

        match = re.fullmatch(r"(?:参与)(?P<object>.+?)的(?P<body>.+)", text)
        if match:
            object_span = _match_span(source_text, segment.start, match, "object")
            body = _match_span(source_text, segment.start, match, "body")
            builder.add_candidate(object_span, segment_index)
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.participated_object",
            )
            continue

        match = re.fullmatch(r"参与(?P<body>.+)", text)
        if match:
            _add_split(
                builder,
                _match_span(source_text, segment.start, match, "body"),
                segment_index,
                "responsibility.participation_members",
            )
            continue

        match = re.fullmatch(r"持续提升\s*(?P<object>.+?)\s*的(?P<body>.+)", text)
        if match:
            object_span = _match_span(source_text, segment.start, match, "object")
            body = _match_span(source_text, segment.start, match, "body")
            builder.add_candidate(object_span, segment_index)
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.quality_outcomes",
                scope=("object", object_span),
            )
            continue

        match = re.fullmatch(r"保障系统在(?P<context>.+?)下的(?P<body>.+)", text)
        if match:
            context = _match_span(source_text, segment.start, match, "context")
            body = _match_span(source_text, segment.start, match, "body")
            builder.add_candidate(context, segment_index)
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.environment_qualities",
                scope=("domain", context),
            )
            continue

        match = re.fullmatch(r"探索(?P<context>.+?)上的的?(?P<body>.+)", text)
        if match:
            context = _match_span(source_text, segment.start, match, "context")
            body = _match_span(source_text, segment.start, match, "body")
            builder.add_candidate(context, segment_index)
            builder.add_candidate(body, segment_index)
            builder.add_rule("responsibility.context_and_method")
            continue

        if text.startswith("方向包括但不限于"):
            body = _content_after_prefix(builder, segment, ("方向包括但不限于",))
            body, scope = _span_without_suffix(builder, body, ("等",))
            _add_split(
                builder,
                body,
                segment_index,
                "responsibility.open_directions",
                scope=("suffix", scope) if scope else None,
            )
            continue

        attachment = next(
            (
                item
                for item in builder.example_attachments
                if item.segment_index == segment_index
                and item.parent_span.start >= segment.start
            ),
            None,
        )
        if attachment is not None:
            builder.add_candidate(attachment.parent_span, segment_index)
            builder.add_rule("responsibility.example_parent")
            continue

        body = _content_after_prefix(
            builder,
            segment,
            ("评估", "探索", "研究", "提炼", "设计"),
        )
        builder.add_candidate(body, segment_index)
        builder.add_rule("responsibility.atomic")


def _parse_skill(builder: _ClauseBuilder) -> None:
    source_text = builder.source_text
    for segment_index, segment in enumerate(builder.segments):
        text = segment.text
        attachment = next(
            (
                item
                for item in builder.example_attachments
                if item.segment_index == segment_index
                and item.parent_span.start >= segment.start
            ),
            None,
        )

        explicit = re.search(r"至少一种.+?[（(](?P<body>.+?)(?:等)?[）)]", text)
        if explicit:
            body = _match_span(source_text, segment.start, explicit, "body")
            body, _ = _span_without_suffix(builder, body, ("等",))
            _add_split(
                builder,
                body,
                segment_index,
                "skill.explicit_candidates",
                honor_protected=False,
            )
            continue

        if text.startswith("如"):
            builder.add_rule("skill.trailing_examples")
            continue

        upper_level = re.fullmatch(r"(?:熟练掌握)?至少一门(?P<body>.+)", text)
        if upper_level:
            builder.add_candidate(
                _match_span(source_text, segment.start, upper_level, "body"),
                segment_index,
            )
            builder.add_rule("skill.required_upper_level")
            continue

        scoped = re.fullmatch(
            r"对(?P<body>.+?)(?:的可观测问题)?有(?:深入)?(?:理解|兴趣)", text
        )
        if scoped:
            body = _match_span(source_text, segment.start, scoped, "body")
            _add_split(builder, body, segment_index, "skill.scoped_subjects")
            continue

        if attachment is not None and attachment.cue_span.text == "等":
            parent = attachment.parent_span
            parent, suffix = _span_without_suffix(builder, parent, ("者优先",))
            _add_split(
                builder,
                parent,
                segment_index,
                "skill.example_parent",
                scope=("head", suffix) if suffix else None,
            )
            continue

        body = _content_after_prefix(
            builder,
            segment,
            (
                "理解并掌握",
                "熟练掌握",
                "关注并使用",
                "具备扎实的",
                "熟悉当前",
                "深入理解",
                "包括",
                "熟悉",
                "掌握",
                "了解",
            ),
        )
        body, priority = _span_without_suffix(builder, body, ("者优先",))

        colon = max(body.text.find("："), body.text.find(":"))
        if colon >= 0:
            body = SourceSpan.from_bounds(source_text, body.start + colon + 1, body.end)

        if text.startswith("具备扎实的"):
            _add_split(builder, body, segment_index, "skill.foundation_members")
            continue

        shared = re.fullmatch(
            r"(?P<domains>LLM、Agent)\s*(?P<body>基本原理与开发)", body.text
        )
        if shared:
            domains = _match_span(source_text, body.start, shared, "domains")
            concepts = _match_span(source_text, body.start, shared, "body")
            _add_split(builder, domains, segment_index, "skill.shared_domains")
            _add_split(
                builder,
                concepts,
                segment_index,
                "skill.shared_aspects",
                scope=("domain", domains),
            )
            continue

        body, tail = _span_without_suffix(
            builder,
            body,
            (
                "等核心能力",
                "等概念",
                "等技术流程",
                "等方法",
                "等核心机制",
                "等",
            ),
        )
        parenthetical_start = _find_parenthetical_start(builder, body)
        if parenthetical_start is not None:
            protected = next(
                span
                for span in builder.protected_spans
                if span.start == parenthetical_start
            )
            if protected.text.startswith(("（如", "(如")):
                members, connectors = _split_coordination_span(
                    source_text,
                    body,
                    builder.protected_spans,
                )
                clean_members = tuple(
                    SourceSpan.from_bounds(source_text, member.start, protected.start)
                    if member.start < protected.start < member.end
                    else member
                    for member in members
                )
                builder.add_group(
                    "skill.enumerated_concepts",
                    clean_members,
                    connectors,
                    segment_index,
                    scope=("suffix", tail) if tail else None,
                )
                builder.add_rule("skill.enumerated_concepts")
                continue
        _add_split(
            builder,
            body,
            segment_index,
            "skill.enumerated_concepts",
            scope=("suffix", tail or priority) if (tail or priority) else None,
        )


_EXPERIENCE_SUFFIXES = (
    "上的端到端策略实战经验",
    "深度学习框架使用经验",
    "应用系统开发经验",
    "相关项目经验",
    "CAE分析经验",
    "研究/项目经历",
    "项目经验",
    "Top 名次",
    "经验",
)


def _parse_experience(builder: _ClauseBuilder) -> None:
    source_text = builder.source_text
    for segment_index, segment in enumerate(builder.segments):
        text = segment.text
        attachment = next(
            (
                item
                for item in builder.example_attachments
                if item.segment_index == segment_index
                and item.parent_span.start >= segment.start
            ),
            None,
        )
        if attachment is not None and attachment.cue_span.text == "等":
            builder.add_candidate(attachment.parent_span, segment_index)
            builder.add_rule("experience.example_parent")
            continue

        body = _content_after_prefix(
            builder,
            segment,
            ("或参与过", "使用过", "具有", "具备", "有", "对", "或"),
        )
        body, _ = _span_without_suffix(builder, body, ("者优先", "的优先", "优先"))

        if text.startswith("对"):
            practical = re.fullmatch(r"(?P<body>.+?)有(?:大量)?实践经验", body.text)
            if practical:
                builder.add_candidate(
                    _match_span(source_text, body.start, practical, "body"),
                    segment_index,
                )
                builder.add_rule("experience.practice_subject")
                continue

        parenthetical_start = _find_parenthetical_start(builder, body)
        if parenthetical_start is not None:
            main = _trim_span(source_text, body.start, parenthetical_start)
            if main is not None:
                main_start = main.start
                main_end = main.end
                if main.text.startswith("良好的"):
                    main_start += len("良好的")
                if source_text[main_start:main_end].endswith("优先"):
                    main_end -= len("优先")
                main = SourceSpan.from_bounds(source_text, main_start, main_end)
                builder.add_candidate(main, segment_index)
                builder.add_rule("experience.parenthetical_examples")
                continue

        domain_paths = re.fullmatch(
            r"(?P<domain>.+?领域)(?P<paths>实习或科研)(?P<scope>经验)", body.text
        )
        if domain_paths:
            domain = _match_span(source_text, body.start, domain_paths, "domain")
            paths = _match_span(source_text, body.start, domain_paths, "paths")
            scope = _match_span(source_text, body.start, domain_paths, "scope")
            builder.add_candidate(domain, segment_index)
            _add_split(
                builder,
                paths,
                segment_index,
                "experience.domain_paths",
                scope=("suffix", scope),
            )
            continue

        if (
            body.text.startswith("从")
            and "到" in body.text
            and body.text.endswith("项目经验")
        ):
            builder.add_candidate(body, segment_index)
            builder.add_rule("experience.end_to_end_path")
            continue

        suffix = next(
            (value for value in _EXPERIENCE_SUFFIXES if body.text.endswith(value)),
            None,
        )
        if suffix is not None:
            prefix_end = body.end - len(suffix)
            prefix = _trim_span(source_text, body.start, prefix_end)
            scope = SourceSpan.from_bounds(source_text, prefix_end, body.end)
            if prefix is None:
                builder.add_candidate(scope, segment_index)
                builder.add_rule("experience.atomic_scope")
                continue
            if suffix in {"深度学习框架使用经验"}:
                builder.add_candidate(scope, segment_index)
                builder.add_rule("experience.example_parent")
                continue
            _add_split(
                builder,
                prefix,
                segment_index,
                "experience.shared_scope",
                scope=("suffix", scope),
            )
            continue

        builder.add_candidate(body, segment_index)
        builder.add_rule("experience.atomic")


def _parse_capability(builder: _ClauseBuilder) -> None:
    source_text = builder.source_text
    for segment_index, segment in enumerate(builder.segments):
        text = segment.text

        attitude = re.fullmatch(
            r"对(?P<body>.+?)有(?:浓厚)?(?P<attitudes>兴趣和了解)", text
        )
        if attitude:
            body = _match_span(source_text, segment.start, attitude, "body")
            attitudes = _match_span(source_text, segment.start, attitude, "attitudes")
            _add_split(builder, body, segment_index, "capability.attitude_domains")
            _add_split(
                builder,
                attitudes,
                segment_index,
                "capability.attitudes",
                scope=("domain", body),
            )
            continue

        ability = re.fullmatch(
            r"具备(?:良好的|较强的|一定的|良好)?(?P<body>.+?)(?P<scope>能力)(?:者优先)?",
            text,
        )
        if ability:
            body = _match_span(source_text, segment.start, ability, "body")
            scope = _match_span(source_text, segment.start, ability, "scope")
            _add_split(
                builder,
                body,
                segment_index,
                "capability.shared_ability",
                scope=("suffix", scope),
            )
            continue

        strength = re.fullmatch(r"(?P<body>.+(?:能力|力))强", text)
        if strength:
            _add_split(
                builder,
                _match_span(source_text, segment.start, strength, "body"),
                segment_index,
                "capability.strong_members",
            )
            continue

        understanding = re.fullmatch(
            r"愿意深入(?P<body>.+?)(?P<scope>理解真实需求)", text
        )
        if understanding:
            body = _match_span(source_text, segment.start, understanding, "body")
            scope = _match_span(source_text, segment.start, understanding, "scope")
            _add_split(
                builder,
                body,
                segment_index,
                "capability.understanding_domains",
                scope=("predicate", scope),
            )
            continue

        insight = re.fullmatch(r"能够透过.+?看到(?P<body>.+)", text)
        if insight:
            builder.add_candidate(
                _match_span(source_text, segment.start, insight, "body"), segment_index
            )
            builder.add_rule("capability.insight")
            continue

        context = re.fullmatch(r"能够在(?P<body>.+?)下", text)
        if context:
            builder.add_candidate(
                _match_span(source_text, segment.start, context, "body"), segment_index
            )
            builder.add_rule("capability.context")
            continue

        craft = re.fullmatch(r"对待(?P<body>.+?)等有追求极致的(?P<head>工匠精神)", text)
        if craft:
            body = _match_span(source_text, segment.start, craft, "body")
            head = _match_span(source_text, segment.start, craft, "head")
            _add_split(
                builder,
                body,
                segment_index,
                "capability.craft_domains",
                scope=("predicate", head),
            )
            builder.add_candidate(head, segment_index)
            continue

        body = _content_after_prefix(
            builder,
            segment,
            (
                "能熟练使用",
                "具备较强的",
                "具备一定的",
                "具备良好的",
                "具备良好",
                "能够",
                "擅长",
                "进行",
                "能",
                "极强",
                "良好",
            ),
        )
        body, _ = _span_without_suffix(builder, body, ("者优先",))
        action_parts = re.split(r"并(?=(?:定位|设计|实现|推动|开展))", body.text)
        if len(action_parts) > 1:
            spans: list[SourceSpan] = []
            connectors: list[SourceSpan] = []
            offset = body.start
            for part_index, part in enumerate(action_parts):
                part_start = source_text.find(part, offset, body.end)
                spans.append(
                    SourceSpan.from_bounds(
                        source_text, part_start, part_start + len(part)
                    )
                )
                offset = part_start + len(part)
                if part_index < len(action_parts) - 1:
                    connectors.append(
                        SourceSpan.from_bounds(source_text, offset, offset + 1)
                    )
                    offset += 1
            builder.add_group(
                "capability.multi_outcome",
                tuple(spans),
                tuple(connectors),
                segment_index,
            )
            builder.add_rule("capability.multi_outcome")
            continue
        builder.add_candidate(body, segment_index)
        builder.add_rule("capability.atomic")


def parse_clause(source_text: str, category: SurfaceCategory) -> ParsedClause:
    """Parse one already-bounded JD clause into source-anchored structure."""

    if not source_text.strip():
        raise ValueError("source_text must not be empty")
    if category not in {"responsibility", "skill", "experience", "capability"}:
        raise ValueError(f"unsupported surface category: {category!r}")

    builder = _ClauseBuilder(source_text, category)
    _detect_wrappers(builder)
    _detect_example_attachments(builder)
    parsers = {
        "responsibility": _parse_responsibility,
        "skill": _parse_skill,
        "experience": _parse_experience,
        "capability": _parse_capability,
    }
    parsers[category](builder)
    return builder.build()


def _unique_text(spans: tuple[SourceSpan, ...]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for span in spans:
        key = span.text.casefold()
        if key not in seen:
            values.append(span.text)
            seen.add(key)
    return tuple(values)


def project_surface_items(parsed_clause: ParsedClause) -> StructuredSurfaceExtraction:
    """Project the structural IR without reparsing or rewriting source text."""

    item_spans = tuple(member.span for member in parsed_clause.item_candidates)
    example_spans = tuple(
        span
        for attachment in parsed_clause.example_attachments
        if any(
            candidate.start < attachment.parent_span.end
            and attachment.parent_span.start < candidate.end
            for candidate in item_spans
        )
        for span in attachment.example_spans
    )
    return StructuredSurfaceExtraction(
        category=parsed_clause.category,
        source_text=parsed_clause.source_text,
        items=_unique_text(item_spans),
        examples=_unique_text(example_spans),
        rule_ids=parsed_clause.rule_ids,
        parsed_clause=parsed_clause,
    )


def extract_surface_items(
    source_text: str,
    category: SurfaceCategory,
) -> StructuredSurfaceExtraction:
    """Compatibility entry point for the v3 parser and projection pipeline."""

    return project_surface_items(parse_clause(source_text, category))

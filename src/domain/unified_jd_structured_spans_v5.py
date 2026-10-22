from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain import unified_jd_structured_spans_v4 as v4

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

STRUCTURED_SPAN_PARSER_VERSION = "unified-jd-structured-span-parser-v5-development"

_PREFIX_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"能够独立完成",
        r"熟悉掌握常用的",
        r"能够快速将",
        r"与[^，,；;：:]{1,16}?共同建立",
        r"具备(?:优秀|丰富|较强|扎实|良好|深厚)的?",
        r"有真实的",
        r"有发表",
        r"熟练使用",
        r"能够使用",
        r"共同维护",
        r"通过输出",
        r"分析总结",
        r"3年以上",
        r"基于",
        r"结合",
        r"通过",
        r"识别",
        r"推动",
        r"提高",
        r"降低",
        r"熟悉",
        r"掌握",
        r"精通",
        r"具备",
        r"能够",
        r"能利用",
        r"能将",
        r"拥有",
        r"有",
        r"负责",
        r"参与",
        r"建设",
        r"探索",
        r"研究",
        r"理解",
        r"洞察",
        r"构建",
        r"打通",
        r"沉淀",
        r"挖掘",
        r"监控",
        r"协助",
        r"深厚的",
        r"对",
        r"为",
        r"与",
        r"以",
        r"在",
    )
)
_PRIORITY_SUFFIXES = ("者优先", "的优先", "优先")
_SHARED_SUFFIXES = ("的经验", "能力", "经验", "信息", "加速")
_POSTPOSED_CONTAINER_HEADS = ("领域", "方面")
_INNER_CONNECTORS = ("或者", "以及", "并且", "与", "和", "及", "或", "并", "到")
_SURFACE_CONNECTORS = ("或者", "以及", "并且", "、", "与", "和", "及", "或", "/", "并")


@dataclass(frozen=True, slots=True)
class _Region:
    span: SourceSpan
    index: int
    prefix: tuple[SourceSpan, SourceSpan] | None
    core: SourceSpan
    suffixes: tuple[tuple[str, SourceSpan, SourceSpan], ...]


@dataclass(frozen=True, slots=True)
class _AttachmentPlan:
    cue: SourceSpan
    parent: SourceSpan
    examples: tuple[SourceSpan, ...]
    connectors: tuple[SourceSpan, ...]
    region_index: int
    residuals: tuple[SourceSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class _DirectOpenList:
    cue: SourceSpan
    members: tuple[SourceSpan, ...]
    connectors: tuple[SourceSpan, ...]
    region_index: int


def _trim(source: str, start: int, end: int) -> SourceSpan | None:
    while start < end and (source[start].isspace() or source[start] in "，,；;。:："):
        start += 1
    while start < end and (
        source[end - 1].isspace() or source[end - 1] in "，,；;。:："
    ):
        end -= 1
    return SourceSpan.from_bounds(source, start, end) if start < end else None


def _span(source: str, start: int, end: int) -> SourceSpan:
    result = _trim(source, start, end)
    if result is None:
        raise ValueError("empty v5 structural span")
    return result


def _inside(index: int, spans: tuple[SourceSpan, ...]) -> bool:
    return any(span.start < index < span.end - 1 for span in spans)


def _split_regions(
    source: str, protected: tuple[SourceSpan, ...]
) -> tuple[SourceSpan, ...]:
    regions: list[SourceSpan] = []
    start = 0
    for index, character in enumerate(source):
        if character not in "，,；;：:" or _inside(index, protected):
            continue
        region = _trim(source, start, index)
        if region is not None:
            regions.append(region)
        start = index + 1
    final = _trim(source, start, len(source))
    if final is not None:
        regions.append(final)
    return tuple(regions)


def _ascii_run(source: str, index: int, direction: int) -> int:
    length = 0
    index += direction
    while (
        0 <= index < len(source) and source[index].isascii() and source[index].isalnum()
    ):
        length += 1
        index += direction
    return length


def _connector_at(
    source: str,
    index: int,
    end: int,
    separators: tuple[str, ...],
    protected: tuple[SourceSpan, ...],
) -> str | None:
    connector = next(
        (
            value
            for value in sorted(separators, key=len, reverse=True)
            if source.startswith(value, index) and index + len(value) <= end
        ),
        None,
    )
    if connector is None or _inside(index, protected):
        return None
    if (
        connector == "/"
        and _ascii_run(source, index, -1) == _ascii_run(source, index, 1) == 1
    ):
        return None
    if connector == "及" and source.startswith("及以上", index):
        return None
    if connector == "或" and (
        re.search(r"(?:一|若干)种$", source[max(0, index - 4) : index])
        and source.startswith("多种", index + 1)
    ):
        return None
    return connector


def _split(
    source: str,
    value: SourceSpan,
    separators: tuple[str, ...],
    protected: tuple[SourceSpan, ...],
) -> tuple[tuple[SourceSpan, ...], tuple[SourceSpan, ...]]:
    members: list[SourceSpan] = []
    connectors: list[SourceSpan] = []
    member_start = value.start
    index = value.start
    while index < value.end:
        connector = _connector_at(source, index, value.end, separators, protected)
        if connector is None:
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
    final = _trim(source, member_start, value.end)
    if final is not None:
        members.append(final)
    if len(members) != len(connectors) + 1:
        return (value,), ()
    return tuple(members), tuple(connectors)


def _prefix_for(
    source: str, region: SourceSpan, base: ParsedClause
) -> tuple[SourceSpan, SourceSpan] | None:
    for pattern in _PREFIX_PATTERNS:
        match = pattern.match(region.text)
        if match is None or match.end() >= len(region.text):
            continue
        marker = SourceSpan.from_bounds(
            source, region.start, region.start + match.end()
        )
        content = _trim(source, marker.end, region.end)
        if content is not None:
            return marker, content
    for wrapper in base.wrappers:
        if wrapper.kind.split(".")[-1] != "prefix":
            continue
        if wrapper.marker_span.start != region.start:
            continue
        content = _trim(source, wrapper.marker_span.end, region.end)
        if content is not None:
            return wrapper.marker_span, content
    return None


def _suffixes_for(
    source: str, operand: SourceSpan
) -> tuple[SourceSpan, tuple[tuple[str, SourceSpan, SourceSpan], ...]]:
    full_operand = operand
    suffixes: list[tuple[str, SourceSpan, SourceSpan]] = []
    core = operand

    evidence = re.search(
        r"(?P<marker>有[^，,；;：:]{1,18}?(?:认知|了解|认识|经验|兴趣|探索欲)(?:者优先)?)$",
        core.text,
    )
    if evidence is not None and evidence.start("marker") > 0:
        marker = SourceSpan.from_bounds(
            source,
            core.start + evidence.start("marker"),
            core.start + evidence.end("marker"),
        )
        content = _span(source, core.start, marker.start)
        suffixes.append(("suffix", marker, content))
        core = content
        return core, tuple(suffixes)

    if core.text.endswith("进行优化") and len(core.text) > 4:
        marker = SourceSpan.from_bounds(source, core.end - 4, core.end)
        content = _span(source, core.start, marker.start)
        suffixes.append(("suffix", marker, content))
        core = content

    for value in _PRIORITY_SUFFIXES:
        if core.text.endswith(value) and len(core.text) > len(value):
            marker = SourceSpan.from_bounds(source, core.end - len(value), core.end)
            content = _span(source, full_operand.start, marker.start)
            suffixes.append(("suffix", marker, content))
            core = _span(source, core.start, marker.start)
            break
    return core, tuple(suffixes)


def _regions(source: str, base: ParsedClause) -> tuple[_Region, ...]:
    result: list[_Region] = []
    for index, region in enumerate(_split_regions(source, base.protected_spans)):
        prefix = _prefix_for(source, region, base)
        operand = prefix[1] if prefix is not None else region
        core, suffixes = _suffixes_for(source, operand)
        result.append(_Region(region, index, prefix, core, suffixes))
    return tuple(result)


def _strip_terminal_deng(source: str, value: SourceSpan) -> SourceSpan:
    end = value.end
    while end > value.start and source[end - 1].isspace():
        end -= 1
    if end > value.start and source[end - 1] == "等":
        end -= 1
    return _span(source, value.start, end)


def _example_parts(
    source: str, value: SourceSpan, protected: tuple[SourceSpan, ...]
) -> tuple[tuple[SourceSpan, ...], tuple[SourceSpan, ...]]:
    return _split(source, value, ("、", ",", "/"), protected)


def _parent_and_residual(
    source: str, tail: SourceSpan
) -> tuple[SourceSpan | None, tuple[SourceSpan, ...]]:
    end = tail.end
    for suffix in _PRIORITY_SUFFIXES:
        if source[tail.start : end].strip().endswith(suffix):
            stripped_end = source.rfind(suffix, tail.start, end)
            end = stripped_end
            break
    trimmed = _trim(source, tail.start, end)
    if trimmed is None:
        return None, ()

    for head in _POSTPOSED_CONTAINER_HEADS:
        if not trimmed.text.startswith(head):
            continue
        parent = SourceSpan.from_bounds(
            source, trimmed.start, trimmed.start + len(head)
        )
        rest = _trim(source, parent.end, trimmed.end)
        if rest is None or rest.text in {"的经验", "经验"}:
            return parent, ()
        if rest.text.startswith("的") and len(rest.text) > 1:
            rest = _span(source, rest.start + 1, rest.end)
        return parent, (rest,)

    boundary = re.search(r"(?=有[^，,；;]+$|独立完成|加速|提升|进行优化)", trimmed.text)
    if boundary is not None and boundary.start() > 0:
        parent = _span(source, trimmed.start, trimmed.start + boundary.start())
        residual = _trim(source, parent.end, trimmed.end)
        return parent, (residual,) if residual is not None else ()
    if trimmed.text.endswith("的经验") and len(trimmed.text) > 3:
        parent = _span(source, trimmed.start, trimmed.end - 3)
        return parent, ()
    return trimmed, ()


def _discover_attachments(
    source: str,
    regions: tuple[_Region, ...],
    protected: tuple[SourceSpan, ...],
) -> tuple[tuple[_AttachmentPlan, ...], tuple[_DirectOpenList, ...]]:
    plans: list[_AttachmentPlan] = []
    direct_lists: list[_DirectOpenList] = []

    for region in regions:
        for enclosure in protected:
            if not (
                region.core.start <= enclosure.start
                and enclosure.end <= region.core.end
            ):
                continue
            body = _trim(source, enclosure.start + 1, enclosure.end - 1)
            if body is None:
                continue
            cue: SourceSpan
            if body.text.startswith("如"):
                cue = SourceSpan.from_bounds(source, body.start, body.start + 1)
                examples_body = _trim(source, cue.end, body.end)
            elif any(value in body.text for value in ("、", "/", ",")):
                cue = SourceSpan.from_bounds(
                    source, enclosure.start, enclosure.start + 1
                )
                examples_body = body
            else:
                continue
            if examples_body is None:
                continue
            examples_body = _strip_terminal_deng(source, examples_body)
            examples, connectors = _example_parts(source, examples_body, ())
            if len(examples) < 2:
                continue
            parent = _trim(source, region.core.start, enclosure.start)
            if parent is None:
                continue
            residual = _trim(source, enclosure.end, region.core.end)
            plans.append(
                _AttachmentPlan(
                    cue,
                    parent,
                    examples,
                    connectors,
                    region.index,
                    (residual,) if residual is not None else (),
                )
            )

    for position, region in enumerate(regions):
        introduced = re.match(r"如(?=\s*\S)", region.core.text)
        if introduced is None or position == 0:
            continue
        cue = SourceSpan.from_bounds(source, region.core.start, region.core.start + 1)
        example_body = _span(source, cue.end, region.core.end)
        example_body = _strip_terminal_deng(source, example_body)
        examples, connectors = _example_parts(source, example_body, protected)
        if not examples:
            continue
        parent_region = regions[position - 1]
        plans.append(
            _AttachmentPlan(
                cue,
                parent_region.core,
                examples,
                connectors,
                region.index,
            )
        )

    occupied = {(plan.region_index, plan.cue.start) for plan in plans}
    for region in regions:
        for offset, character in enumerate(region.core.text):
            cue_start = region.core.start + offset
            if character != "等" or _inside(cue_start, protected):
                continue
            if (region.index, cue_start) in occupied or region.core.text.startswith(
                "如"
            ):
                continue
            before = _trim(source, region.core.start, cue_start)
            tail = _trim(source, cue_start + 1, region.core.end)
            if before is None:
                continue
            examples, connectors = _example_parts(source, before, protected)
            if not examples:
                continue
            cue = SourceSpan.from_bounds(source, cue_start, cue_start + 1)
            if tail is None:
                direct_lists.append(
                    _DirectOpenList(cue, examples, connectors, region.index)
                )
                break
            parent, residuals = _parent_and_residual(source, tail)
            if parent is None:
                direct_lists.append(
                    _DirectOpenList(cue, examples, connectors, region.index)
                )
                continue
            plans.append(
                _AttachmentPlan(
                    cue,
                    parent,
                    examples,
                    connectors,
                    region.index,
                    residuals,
                )
            )
            break
    return tuple(plans), tuple(direct_lists)


def _normalized_members(
    source: str,
    value: SourceSpan,
    members: tuple[SourceSpan, ...],
) -> tuple[tuple[SourceSpan, ...], tuple[str, SourceSpan] | None]:
    if len(members) < 2:
        return members, None
    first = members[0]
    prefix = re.match(r"(?P<prefix>[^的]{1,12}的)(?P<body>.+)", first.text)
    if prefix is not None:
        prefix_span = SourceSpan.from_bounds(
            source, first.start, first.start + prefix.end("prefix")
        )
        normalized_first = _span(source, prefix_span.end, first.end)
        return (normalized_first, *members[1:]), ("prefix", prefix_span)

    last = members[-1]
    for suffix in _SHARED_SUFFIXES:
        if not last.text.endswith(suffix) or len(last.text) <= len(suffix):
            continue
        suffix_span = SourceSpan.from_bounds(source, last.end - len(suffix), last.end)
        normalized_last = _span(source, last.start, suffix_span.start)
        kind = "evidence" if "经验" in suffix else "suffix"
        return (*members[:-1], normalized_last), (kind, suffix_span)
    return members, None


def _strip_residual_operator(source: str, value: SourceSpan) -> SourceSpan | None:
    text = value.text
    if text in {"的经验", "经验"}:
        return None
    for marker in ("独立完成", "加速", "提升", "进行优化"):
        if text.startswith(marker) and len(text) > len(marker):
            return _trim(source, value.start + len(marker), value.end)
    if text.startswith("在") and len(text) > 1:
        return _trim(source, value.start + 1, value.end)
    if text.startswith("的") and len(text) > 1:
        return _trim(source, value.start + 1, value.end)
    return value


def _add_surface(
    builder: v4._Builder,
    value: SourceSpan,
    segment_index: int,
    processed: set[tuple[int, int]],
) -> None:
    value = _strip_residual_operator(builder.source, value)
    if value is None:
        return
    bounds = (value.start, value.end)
    if bounds in processed:
        return
    processed.add(bounds)

    transition = re.fullmatch(
        r"从(?P<left>.+?)到(?P<right>.+?)(?P<scope>的[^的]+)$", value.text
    )
    if transition is not None:
        left = _span(
            builder.source,
            value.start + transition.start("left"),
            value.start + transition.end("left"),
        )
        right = _span(
            builder.source,
            value.start + transition.start("right"),
            value.start + transition.end("right"),
        )
        connector_start = value.start + transition.end("left")
        connector = SourceSpan.from_bounds(
            builder.source, connector_start, connector_start + 1
        )
        members = builder.group(
            "embedded",
            "v5.transition",
            (left, right),
            (connector,),
            segment_index,
        )
        scope_span = _span(
            builder.source,
            value.start + transition.start("scope"),
            value.start + transition.end("scope"),
        )
        builder.scope("result", scope_span, members)
        builder.candidate(value, segment_index)
        return

    raw_members, connectors = _split(
        builder.source,
        value,
        _SURFACE_CONNECTORS,
        builder.protected_spans,
    )
    if len(raw_members) < 2:
        builder.candidate(value, segment_index)
        return
    members, shared = _normalized_members(builder.source, value, raw_members)
    group = builder.group(
        "surface", "v5.region_surface", members, connectors, segment_index
    )
    if shared is not None:
        builder.scope(shared[0], shared[1], group)
    for member in members:
        builder.candidate(member, segment_index)


def _add_embedded_example_groups(
    builder: v4._Builder,
    examples: tuple[SourceSpan, ...],
    segment_index: int,
) -> None:
    for example in examples:
        raw_members, connectors = _split(
            builder.source,
            example,
            _INNER_CONNECTORS,
            builder.protected_spans,
        )
        if len(raw_members) < 2:
            continue
        members, shared = _normalized_members(builder.source, example, raw_members)
        group = builder.group(
            "embedded", "v5.example_inner", members, connectors, segment_index
        )
        if shared is not None:
            builder.scope(shared[0], shared[1], group)


def _add_attachment(
    builder: v4._Builder,
    plan: _AttachmentPlan,
    processed: set[tuple[int, int]],
) -> None:
    builder.group(
        "example",
        "v5.region_examples",
        plan.examples,
        plan.connectors,
        plan.region_index,
    )
    _add_embedded_example_groups(builder, plan.examples, plan.region_index)
    _add_surface(builder, plan.parent, plan.region_index, processed)
    topology = v4.TopologyAttachment(
        cue_span=plan.cue,
        parent_span=plan.parent,
        parent_region=plan.parent,
        example_spans=plan.examples,
        example_connectors=plan.connectors,
        parent_members=(),
        parent_connectors=(),
        evidence_scope=None,
        evidence_item=None,
    )
    builder.attachment(topology, plan.region_index)


def _add_suffix_embedded_group(
    builder: v4._Builder,
    marker: SourceSpan,
    segment_index: int,
) -> None:
    body = marker
    if body.text.startswith("有") and len(body.text) > 1:
        body = _span(builder.source, body.start + 1, body.end)
    for suffix in _PRIORITY_SUFFIXES:
        if body.text.endswith(suffix) and len(body.text) > len(suffix):
            body = _span(builder.source, body.start, body.end - len(suffix))
            break
    members, connectors = _split(
        builder.source, body, _INNER_CONNECTORS, builder.protected_spans
    )
    if len(members) > 1:
        builder.group(
            "embedded", "v5.wrapper_inner", members, connectors, segment_index
        )


def _with_quantifier_labels(parsed: ParsedClause) -> ParsedClause:
    labels = {
        (item.span.start, item.span.end): item for item in parsed.connector_labels
    }
    for match in re.finditer(r"及(?=以上)", parsed.source_text):
        span = SourceSpan.from_bounds(parsed.source_text, match.start(), match.end())
        labels[(span.start, span.end)] = ConnectorLabel(span, "quantifier")
    return ParsedClause(
        source_text=parsed.source_text,
        category=parsed.category,
        protected_spans=parsed.protected_spans,
        segments=parsed.segments,
        wrappers=tuple(
            sorted(
                parsed.wrappers,
                key=lambda item: (item.marker_span.start, item.marker_span.end),
            )
        ),
        connector_labels=tuple(labels[key] for key in sorted(labels)),
        coordinations=parsed.coordinations,
        shared_scopes=parsed.shared_scopes,
        example_attachments=tuple(
            sorted(parsed.example_attachments, key=lambda item: item.cue_span.start)
        ),
        item_candidates=tuple(
            sorted(
                parsed.item_candidates,
                key=lambda item: (item.span.start, item.span.end),
            )
        ),
        rule_ids=parsed.rule_ids,
    )


def _fresh_parse(
    source: str, category: SurfaceCategory, base: ParsedClause
) -> tuple[ParsedClause, tuple[_DirectOpenList, ...]]:
    regions = _regions(source, base)
    builder = v4._Builder(
        source,
        category,
        base.protected_spans,
        tuple(region.span for region in regions),
    )
    for region in regions:
        if region.prefix is not None:
            builder.wrapper("prefix", *region.prefix)
        for kind, marker, content in region.suffixes:
            builder.wrapper(kind, marker, content)
            _add_suffix_embedded_group(builder, marker, region.index)

    attachments, direct_lists = _discover_attachments(
        source, regions, base.protected_spans
    )
    processed: set[tuple[int, int]] = set()
    for plan in attachments:
        _add_attachment(builder, plan, processed)
        for residual in plan.residuals:
            if residual.text.startswith("独立完成"):
                marker = SourceSpan.from_bounds(
                    source, residual.start, residual.start + len("独立完成")
                )
                content = _span(source, marker.end, residual.end)
                builder.wrapper("prefix", marker, content)
            _add_surface(builder, residual, plan.region_index, processed)

    direct_by_region = {item.region_index: item for item in direct_lists}
    attachment_regions = {plan.region_index for plan in attachments}
    explicit_parent_regions = {
        position - 1
        for position, region in enumerate(regions)
        if position > 0 and region.core.text.startswith("如")
    }
    explicit_parent_regions.update(
        direct.region_index - 1 for direct in direct_lists if direct.region_index > 0
    )
    for region in regions:
        direct = direct_by_region.get(region.index)
        if direct is not None:
            builder.wrapper(
                "open_list_suffix",
                direct.cue,
                _span(source, direct.members[0].start, direct.members[-1].end),
            )
            group = builder.group(
                "surface",
                "v5.direct_open_list",
                direct.members,
                direct.connectors,
                region.index,
            )
            for member in group:
                builder.candidate(member.span, region.index)
            processed.add((region.core.start, region.core.end))
            continue
        if region.index in attachment_regions:
            continue
        if region.core.text.startswith("如"):
            continue
        if region.index in explicit_parent_regions and re.fullmatch(
            r"以下(?:经验|方向|技能|能力|内容)", region.core.text
        ):
            continue
        _add_surface(builder, region.core, region.index, processed)

    builder.rule("v5.protect_and_segment")
    builder.rule("v5.wrapper_boundary_first")
    builder.rule("v5.attachment_regions")
    if direct_lists:
        builder.rule("v5.priority_tail_rejection")
    if any(
        source[plan.examples[0].start - 1 : plan.examples[0].start] == "对"
        for plan in attachments
        if plan.examples[0].start > 0
    ):
        builder.rule("v5.prepositional_wrapper_before_example_split")
    builder.rule("v5.region_first_connector_roles")
    builder.rule("v5.graph_projection")
    return _with_quantifier_labels(builder.build()), direct_lists


def _attachment_signature(
    parsed: ParsedClause,
) -> set[tuple[int, int, int, int, tuple[tuple[int, int], ...]]]:
    return {
        (
            item.cue_span.start,
            item.cue_span.end,
            item.parent_span.start,
            item.parent_span.end,
            tuple((example.start, example.end) for example in item.example_spans),
        )
        for item in parsed.example_attachments
    }


def _connector_role_map(parsed: ParsedClause) -> dict[tuple[int, int], str]:
    return {
        (item.span.start, item.span.end): item.role for item in parsed.connector_labels
    }


def _should_use_fresh(
    base: ParsedClause,
    fresh: ParsedClause,
    direct_lists: tuple[_DirectOpenList, ...],
) -> bool:
    base_prefixes = {
        (item.marker_span.start, item.marker_span.end)
        for item in base.wrappers
        if item.kind.split(".")[-1] == "prefix"
    }
    fresh_prefixes = {
        (item.marker_span.start, item.marker_span.end)
        for item in fresh.wrappers
        if item.kind == "prefix"
    }
    if not fresh_prefixes <= base_prefixes:
        return True

    if _attachment_signature(fresh) != _attachment_signature(base):
        return True
    base_roles = _connector_role_map(base)
    for group in fresh.coordinations:
        if group.role != "example":
            continue
        if any(
            base_roles.get((span.start, span.end)) != "example"
            for span in group.connector_spans
        ):
            return True

    base_items = set(v4.project_surface_items(base).items)
    for direct in direct_lists:
        if not {member.text for member in direct.members} <= base_items:
            return True
    for attachment in base.example_attachments:
        if attachment.example_spans and attachment.example_spans[0].text.startswith(
            "对"
        ):
            return True
        if attachment.parent_span.text in _PRIORITY_SUFFIXES:
            return True
    return False


def parse_clause(source_text: str, category: SurfaceCategory) -> ParsedClause:
    if not source_text.strip():
        raise ValueError("source_text must not be empty")
    base = v4.parse_clause(source_text, category)
    fresh, direct_lists = _fresh_parse(source_text, category, base)
    return fresh if _should_use_fresh(base, fresh, direct_lists) else base


def project_surface_items(parsed_clause: ParsedClause) -> StructuredSurfaceExtraction:
    projected = v4.project_surface_items(parsed_clause)
    if parsed_clause.rule_ids and parsed_clause.rule_ids[0].startswith("v5."):
        return StructuredSurfaceExtraction(
            category=projected.category,
            source_text=projected.source_text,
            items=projected.items,
            examples=projected.examples,
            rule_ids=parsed_clause.rule_ids,
            parsed_clause=parsed_clause,
        )
    return projected


def extract_surface_items(
    source_text: str, category: SurfaceCategory
) -> StructuredSurfaceExtraction:
    return project_surface_items(parse_clause(source_text, category))

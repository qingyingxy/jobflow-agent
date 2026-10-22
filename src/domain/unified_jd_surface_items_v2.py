from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SurfaceCategory = Literal["responsibility", "skill", "experience", "capability"]

SURFACE_ITEM_EXTRACTOR_VERSION = "unified-jd-surface-items-grammar-v2"


@dataclass(frozen=True)
class SurfaceItemExtraction:
    """Source-anchored surface items produced by the v2 compositional grammar."""

    category: SurfaceCategory
    source_text: str
    items: tuple[str, ...]
    examples: tuple[str, ...]
    rule_ids: tuple[str, ...]


def _unique(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip(" \t\r\n，,、；;。")
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return tuple(result)


def _split_outside_parentheses(text: str, separators: tuple[str, ...]) -> list[str]:
    ordered_separators = sorted(separators, key=len, reverse=True)
    result: list[str] = []
    start = 0
    depth = 0
    position = 0
    while position < len(text):
        character = text[position]
        if character in "（(":
            depth += 1
            position += 1
            continue
        if character in "）)":
            depth = max(0, depth - 1)
            position += 1
            continue
        if depth == 0:
            separator = next(
                (
                    candidate
                    for candidate in ordered_separators
                    if text.startswith(candidate, position)
                ),
                None,
            )
            if separator is not None:
                result.append(text[start:position])
                position += len(separator)
                start = position
                continue
        position += 1
    result.append(text[start:])
    return [item for item in result if item.strip()]


def _split_enumeration(text: str) -> list[str]:
    return _split_outside_parentheses(text, ("、", "或", "与", "和", "及"))


def _strip_explicit_example_groups(text: str) -> str:
    text = re.sub(r"[（(]如[:：]?[^）)]+[）)]", "", text)
    return re.sub(r"[（(][^）)]*/[^）)]+[）)]", "", text)


def _split_example_values(text: str) -> list[str]:
    body = re.sub(r"等$", "", text.strip())
    return _split_outside_parentheses(body, ("、", "/", "或", "与", "和", ","))


def _extract_examples(
    source_text: str,
    category: SurfaceCategory,
    surface_items: tuple[str, ...],
) -> tuple[str, ...]:
    examples: list[str] = []

    for match in re.finditer(r"[（(]如[:：]?(?P<body>[^）)]+)[）)]", source_text):
        examples.extend(_split_example_values(match.group("body")))

    introduced = re.search(r"[，,]\s*如[:：]?\s*(?P<body>[^。]+)$", source_text)
    if introduced:
        examples.extend(_split_example_values(introduced.group("body")))

    for match in re.finditer(r"(?P<group>[（(](?P<body>[^）)]+)[）)])", source_text):
        body = match.group("body")
        if body.startswith("如"):
            continue
        attached_to_surface_item = any(
            source_text[: match.start()].endswith(item) for item in surface_items
        )
        if (
            any(match.group("group") in item for item in surface_items)
            or attached_to_surface_item
        ):
            examples.extend(_split_example_values(body))

    preposed_patterns = {
        "responsibility": (r"针对(?P<body>[^，,]+?)等\s*(?P<upper>[^，,]+)",),
        "skill": (
            r"^(?:熟悉|掌握)\s*(?P<body>.+?)\s*等\s*"
            r"(?P<upper>.+?)(?:者优先)?$",
        ),
        "experience": (
            r"^(?:有|使用过)\s*(?P<body>.+?)\s*等\s*"
            r"(?P<upper>.+?)(?:者优先)?$",
        ),
        "capability": (),
    }
    for pattern in preposed_patterns[category]:
        match = re.search(pattern, source_text)
        if not match:
            continue
        upper = match.group("upper").strip()
        body = match.group("body").strip()
        has_enumeration = any(separator in body for separator in ("、", "/", ","))
        upper_is_surface_scope = upper in surface_items or all(
            item in upper for item in surface_items
        )
        if has_enumeration and upper_is_surface_scope:
            examples.extend(_split_example_values(body))

    return _unique(examples)


def _extract_skill_items(source_text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    explicit_candidates = re.search(
        r"至少一种[^（(]*(?:（|\()(?P<body>[^）)]+)", source_text
    )
    if explicit_candidates:
        body = re.sub(r"等$", "", explicit_candidates.group("body").strip())
        return _unique(_split_enumeration(body.replace("/", "、"))), (
            "skill.explicit_candidate_group",
        )

    introduced_examples = re.search(
        r"至少一门(?P<upper>[^，,。]+)[，,]\s*如[:：]?", source_text
    )
    if introduced_examples:
        return _unique([introduced_examples.group("upper")]), (
            "skill.upper_level_with_examples",
        )

    preposed_examples = re.fullmatch(
        r"(?:熟悉|掌握)\s*(?P<examples>.+?)\s*等\s*"
        r"(?P<upper>.+?)(?:者优先)?",
        source_text,
    )
    if preposed_examples and any(
        separator in preposed_examples.group("examples")
        for separator in ("、", "/", ",")
    ):
        return _unique(_split_enumeration(preposed_examples.group("upper"))), (
            "skill.preposed_examples_with_upper_level",
        )

    items: list[str] = []
    rules: list[str] = []
    for raw_segment in _split_outside_parentheses(source_text, ("，", ",")):
        segment = raw_segment.strip()
        scoped_attitude = re.fullmatch(
            r"对(?P<body>.+?)(?:的可观测问题)?有(?:深入)?(?:理解|兴趣)",
            segment,
        )
        if scoped_attitude:
            items.extend(_split_enumeration(scoped_attitude.group("body")))
            rules.append("skill.scoped_attitude_wrapper")
            continue

        if "：" in segment or ":" in segment:
            segment = re.split(r"[:：]", segment, maxsplit=1)[1]
            rules.append("skill.upper_level_introduction")
        segment = re.sub(
            r"^(?:理解并掌握|熟练掌握|熟悉当前|熟悉|掌握|了解)\s*",
            "",
            segment,
        )
        segment = _strip_explicit_example_groups(segment)
        segment = re.sub(
            r"等(?:核心能力|概念|关键算法|技术流程|方法)?(?:者优先)?$",
            "",
            segment,
        )
        segment = re.sub(r"者优先$", "", segment)
        items.extend(_split_enumeration(segment))
        rules.append("skill.wrapper_then_enumeration")

    return _unique(items), _unique(rules)


def _extract_experience_items(
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    upper_group = re.fullmatch(
        r"(?:有|使用过)\s*(?P<examples>.+?)\s*等\s*"
        r"(?P<upper>[^，。()（）]+?)(?:者优先)?",
        source_text,
    )
    if upper_group and any(
        separator in upper_group.group("examples") for separator in ("、", "/", ",")
    ):
        return _unique([upper_group.group("upper")]), (
            "experience.preposed_examples_with_upper_level",
        )

    practical = re.fullmatch(
        r"对(?P<body>.+?)有(?:大量)?实践经验(?:的)?(?:优先)?", source_text
    )
    if practical:
        return _unique([practical.group("body")]), (
            "experience.scoped_practice_wrapper",
        )

    core = re.sub(r"^有\s*", "", source_text).strip()
    core = re.sub(r"^良好的?", "", core)
    core = _strip_explicit_example_groups(core)
    core = re.sub(r"(?:的|者)?优先$", "", core).strip()
    items: list[str] = []
    rules: list[str] = []
    for raw_segment in _split_outside_parentheses(core, ("，", ",")):
        segment = re.sub(r"^或\s*", "", raw_segment.strip())
        shared_suffix = re.fullmatch(
            r"(?P<body>.+?)(?:相关)?(?P<suffix>"
            r"研究/项目经历|项目经验|上的端到端策略实战经验|"
            r"应用系统开发经验|Top\s*名次)",
            segment,
        )
        if shared_suffix and any(
            separator in shared_suffix.group("body")
            for separator in ("、", "/", "或", "与", "和")
        ):
            body = shared_suffix.group("body")
            items.extend(_split_enumeration(body.replace("/", "、")))
            rules.append("experience.shared_suffix_candidates")
            continue
        items.append(segment)
        rules.append("experience.wrapper_stripped_atomic")

    return _unique(items), _unique(rules)


def _parse_responsibility_segment(segment: str) -> tuple[list[str], list[str]]:
    original = segment.strip()
    segment = original.removeprefix("并").strip()

    context_examples = re.fullmatch(r"针对(?P<examples>.+?)等\s*(?P<upper>.+)", segment)
    if context_examples:
        return [context_examples.group("upper")], ["responsibility.context_upper_level"]
    if segment.startswith("针对"):
        return [], ["responsibility.context_dropped"]

    key_modules = re.fullmatch(
        r"设计并优化\s*.+?的\s*(?P<body>.+?)\s*等关键模块", segment
    )
    if key_modules:
        return _split_enumeration(key_modules.group("body")), [
            "responsibility.shared_module_scope"
        ]

    tracked_frontier = re.fullmatch(r"跟踪(?P<body>.+?)的国际前沿技术动态", segment)
    if tracked_frontier:
        return _split_enumeration(tracked_frontier.group("body")), [
            "responsibility.shared_frontier_scope"
        ]

    business_landing = re.fullmatch(
        r"推动(?P<subject>.+?)在(?P<context>.+?中的.+)", segment
    )
    if business_landing:
        return [
            business_landing.group("subject"),
            business_landing.group("context"),
        ], ["responsibility.subject_and_landing_outcome"]

    direction_breakthrough = re.fullmatch(
        r"(?:重点)?突破(?P<body>.+?)等方向的应用创新", segment
    )
    if direction_breakthrough:
        return _split_enumeration(direction_breakthrough.group("body")), [
            "responsibility.shared_direction_scope"
        ]

    if segment.startswith("通过"):
        body = segment.removeprefix("通过")
        return _split_enumeration(body), ["responsibility.means_wrapper"]

    safety_scope = re.fullmatch(r"进行(?P<body>.+?)的安全评估", segment)
    if safety_scope:
        return _split_enumeration(safety_scope.group("body")), [
            "responsibility.shared_assessment_scope"
        ]

    participated_object = re.fullmatch(r"参与(?P<object>.+?)的(?P<body>.+)", segment)
    if participated_object:
        return [
            participated_object.group("object"),
            participated_object.group("body"),
        ], ["responsibility.participated_object"]

    simple_object = re.fullmatch(r"(?:构建|结合|进行)(?P<body>.+)", segment)
    if simple_object:
        return [simple_object.group("body")], ["responsibility.action_object"]

    optimization = re.fullmatch(r"(?:不断)?优化(?P<body>.+?)(?:的整体效果)?", segment)
    if optimization:
        return _split_enumeration(optimization.group("body")), [
            "responsibility.shared_predicate"
        ]

    action_parts = re.split(r"并(?=(?:设计|推动|定位|开展|实现))", segment)
    if len(action_parts) > 1:
        return action_parts, ["responsibility.multi_action"]

    has_enumeration = any(
        separator in segment for separator in ("、", "与", "和", "或")
    )
    preserve_scoped_action = "中的" in segment or segment.startswith(
        ("深入了解", "了解", "研究", "分析")
    )
    if has_enumeration and not preserve_scoped_action:
        return _split_enumeration(segment), ["responsibility.coordinated_work_items"]

    return [original], ["responsibility.atomic_action"]


def _parse_responsibility_body(body: str) -> tuple[list[str], list[str]]:
    if body.count("包括") >= 2 and "，包括" in body:
        direct, explanation = body.split("，包括", maxsplit=1)
        members = explanation.rsplit("包括", maxsplit=1)[1]
        members = re.sub(r"等$", "", members)
        return [*_split_enumeration(direct), *_split_enumeration(members)], [
            "responsibility.nested_including_members"
        ]

    items: list[str] = []
    rules: list[str] = []
    for segment in _split_outside_parentheses(body, ("，", ",")):
        segment_items, segment_rules = _parse_responsibility_segment(segment)
        items.extend(segment_items)
        rules.extend(segment_rules)
    return items, rules


def _extract_responsibility_items(
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    solution_paths = re.fullmatch(r"设计基于(?P<body>.+?)的解决方案", source_text)
    if solution_paths:
        return _unique(_split_enumeration(solution_paths.group("body"))), (
            "responsibility.shared_solution_suffix",
        )

    work_subject = re.fullmatch(r"从事.+?的(?P<body>.+)", source_text)
    if work_subject:
        body = _strip_explicit_example_groups(work_subject.group("body"))
        return _unique(_split_enumeration(body)), ("responsibility.shared_subject",)

    owned_object = re.fullmatch(r"负责(?P<object>.+?)的(?P<body>.+)", source_text)
    if owned_object:
        body_items, body_rules = _parse_responsibility_body(owned_object.group("body"))
        return _unique([owned_object.group("object"), *body_items]), _unique(
            ["responsibility.shared_object", *body_rules]
        )

    items, rules = _parse_responsibility_body(source_text)
    return _unique(items), _unique(rules)


def _extract_capability_items(
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    items: list[str] = []
    rules: list[str] = []
    segments = _split_outside_parentheses(source_text, ("，", ","))

    for raw_segment in segments:
        segment = raw_segment.strip()
        domain_attitude = re.fullmatch(
            r"对(?P<body>.+?)有(?:浓厚)?(?P<attitudes>兴趣和了解)", segment
        )
        if domain_attitude:
            items.extend(
                _split_outside_parentheses(domain_attitude.group("body"), ("/",))
            )
            items.extend(_split_enumeration(domain_attitude.group("attitudes")))
            rules.append("capability.domain_attitudes")
            continue

        ability_group = re.fullmatch(
            r"具备(?:良好的|一定的|较强的?)?(?P<body>.+?)能力(?:者优先)?",
            segment,
        )
        if ability_group:
            items.extend(_split_enumeration(ability_group.group("body")))
            rules.append("capability.shared_ability_suffix")
            continue

        strength_group = re.fullmatch(r"(?P<body>.+(?:能力|力))强", segment)
        if strength_group:
            items.extend(_split_enumeration(strength_group.group("body")))
            rules.append("capability.strength_group")
            continue

        understanding_group = re.fullmatch(
            r"愿意深入(?P<body>.+?)理解真实需求", segment
        )
        if understanding_group:
            items.extend(_split_enumeration(understanding_group.group("body")))
            rules.append("capability.shared_understanding_suffix")
            continue

        insight_group = re.fullmatch(r"能够透过.+?看到(?P<body>.+)", segment)
        if insight_group:
            items.append(insight_group.group("body"))
            rules.append("capability.insight_object")
            continue

        context_group = re.fullmatch(r"(?:能够|能)?在(?P<body>.+?)下", segment)
        if context_group:
            items.append(context_group.group("body"))
            rules.append("capability.context_scope")
            continue

        if segment.startswith(("能够", "能")):
            body = re.sub(r"^(?:能够|能)", "", segment)
            items.extend(_split_outside_parentheses(body, ("并",)))
            rules.append("capability.demonstrable_outcomes")
            continue

        if segment.startswith("进行"):
            items.append(segment.removeprefix("进行"))
            rules.append("capability.action_wrapper")
            continue

        if segment.startswith("擅长"):
            items.append(segment.removeprefix("擅长"))
            rules.append("capability.demonstrable_outcome")
            continue

        degree_stripped = re.sub(r"^(?:极强|良好|较强的?)", "", segment)
        items.append(degree_stripped)
        rules.append("capability.atomic_fallback")

    return _unique(items), _unique(rules)


def extract_surface_items(
    source_text: str,
    category: SurfaceCategory,
) -> SurfaceItemExtraction:
    """Extract source-grounded units with category grammar and no model calls."""

    if not source_text.strip():
        raise ValueError("source_text must not be empty")

    extractors = {
        "responsibility": _extract_responsibility_items,
        "skill": _extract_skill_items,
        "experience": _extract_experience_items,
        "capability": _extract_capability_items,
    }
    items, rule_ids = extractors[category](source_text)
    return SurfaceItemExtraction(
        category=category,
        source_text=source_text,
        items=items,
        examples=_extract_examples(source_text, category, items),
        rule_ids=rule_ids,
    )

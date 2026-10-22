from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SurfaceCategory = Literal["responsibility", "skill", "experience", "capability"]

SURFACE_ITEM_EXTRACTOR_VERSION = "unified-jd-surface-items-rules-v1"


@dataclass(frozen=True)
class SurfaceItemExtraction:
    """Auditable output from the frozen, non-production surface rules."""

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
    return _split_outside_parentheses(text, ("、", "/", "或", "与", "和", "及"))


def _strip_inline_example_groups(text: str) -> str:
    text = re.sub(r"（如[^）]+）", "", text)
    text = re.sub(r"（[A-Za-z][A-Za-z0-9+.-]*/[A-Za-z0-9+./-]+）", "", text)
    return text


def _extract_examples(source_text: str, category: SurfaceCategory) -> tuple[str, ...]:
    examples: list[str] = []

    for match in re.finditer(r"（如(?P<body>[^）]+)）", source_text):
        examples.extend(_split_enumeration(match.group("body")))

    introduced = re.search(r"[，,]如[:：]?(?P<body>[^。]+)$", source_text)
    if introduced:
        examples.extend(_split_enumeration(introduced.group("body")))

    for match in re.finditer(r"（(?P<body>[A-Za-z][A-Za-z0-9+./-]*)）", source_text):
        body = match.group("body")
        is_explicit_candidate_group = (
            category == "skill" and "至少一种" in source_text and "/" in body
        )
        if not is_explicit_candidate_group:
            examples.extend(body.split("/"))

    framework_examples = re.search(
        r"^有(?P<body>[A-Za-z][A-Za-z0-9+./ -]+)等[^，。]*(?:使用经验|实践经验)$",
        source_text,
    )
    if framework_examples:
        examples.extend(framework_examples.group("body").split("/"))

    tool_examples = re.search(
        r"^使用过\s+(?P<body>.+?)\s+等\s+AI\s*工具$",
        source_text,
    )
    if tool_examples:
        examples.extend(
            _split_outside_parentheses(tool_examples.group("body"), ("、", ","))
        )

    return _unique(examples)


def _extract_skill_items(source_text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    explicit_candidates = re.search(
        r"至少一种[^（]*(?:（|\()(?P<body>[^）)]+)", source_text
    )
    if explicit_candidates:
        body = re.sub(r"等$", "", explicit_candidates.group("body").strip())
        return _unique(_split_enumeration(body)), ("skill.explicit_candidate_group",)

    introduced_examples = re.search(
        r"至少一门(?P<upper>[^，,。]+)[，,]\s*如[:：]?",
        source_text,
    )
    if introduced_examples:
        return _unique([introduced_examples.group("upper")]), (
            "skill.upper_level_with_examples",
        )

    core = re.sub(
        r"^(?:理解并掌握|熟练掌握|熟悉当前|熟悉|掌握|了解)\s*", "", source_text
    )
    core = re.sub(r"等(?:核心能力|概念|关键算法)?$", "", core)
    core = _strip_inline_example_groups(core)
    items = _split_outside_parentheses(core, ("、", "或", "与"))
    return _unique(items), ("skill.coordinated_terms",)


def _extract_experience_items(
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tool_group = re.search(r"等\s*(?P<upper>AI\s*工具)$", source_text)
    if source_text.startswith("使用过") and tool_group:
        return _unique([tool_group.group("upper")]), (
            "experience.upper_level_tool_experience",
        )

    framework_group = re.search(
        r"等(?P<upper>[^，。]*(?:使用经验|实践经验|工程经验))$",
        source_text,
    )
    if framework_group:
        return _unique([framework_group.group("upper")]), (
            "experience.upper_level_framework_experience",
        )

    core = re.sub(r"^有\s*", "", source_text)
    core = re.sub(r"者优先$", "", core)
    shared_suffix = re.fullmatch(
        r"(?P<body>.+?)(?:相关)?(?P<suffix>研究/项目经历|项目经验|上的端到端策略实战经验)",
        core,
    )
    if shared_suffix:
        return _unique(_split_enumeration(shared_suffix.group("body"))), (
            "experience.shared_suffix_candidates",
        )

    return _unique([core]), ("experience.atomic_fallback",)


def _extract_capability_items(
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    items: list[str] = []
    rules: list[str] = []
    segments = _split_outside_parentheses(source_text, ("，",))

    for raw_segment in segments:
        segment = raw_segment.strip()
        ability_group = re.fullmatch(
            r"具备(?:良好的|一定的)?(?P<body>.+?)能力(?:者优先)?",
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
            r"愿意深入(?P<body>.+?)理解真实需求",
            segment,
        )
        if understanding_group:
            items.extend(_split_enumeration(understanding_group.group("body")))
            rules.append("capability.shared_understanding_suffix")
            continue

        insight_group = re.fullmatch(
            r"能够透过.+?看到(?P<body>.+)",
            segment,
        )
        if insight_group:
            items.append(insight_group.group("body"))
            rules.append("capability.insight_object")
            continue

        if segment.startswith(("能够", "能")):
            body = re.sub(r"^(?:能够|能)", "", segment)
            items.extend(_split_outside_parentheses(body, ("并",)))
            rules.append("capability.demonstrable_outcomes")
            continue

        if segment.startswith("擅长"):
            items.append(segment.removeprefix("擅长"))
            rules.append("capability.demonstrable_outcome")
            continue

        degree_stripped = re.sub(r"^(?:极强|良好|较强的?)", "", segment)
        items.append(degree_stripped)
        rules.append("capability.atomic_fallback")

    return _unique(items), _unique(rules)


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
        body = _strip_inline_example_groups(work_subject.group("body"))
        return _unique(_split_enumeration(body)), ("responsibility.shared_subject",)

    owned_object = re.fullmatch(r"负责(?P<object>.+?)的(?P<body>.+)", source_text)
    if owned_object:
        body = _strip_inline_example_groups(owned_object.group("body"))
        return _unique([owned_object.group("object"), *_split_enumeration(body)]), (
            "responsibility.shared_object",
        )

    items: list[str] = []
    rules: list[str] = []
    segments = _split_outside_parentheses(source_text, ("，",))
    for raw_segment in segments:
        segment = raw_segment.strip()
        if segment.startswith("针对") and not re.search(
            r"构建|设计|优化|分析|研究|开发|落地|推动", segment
        ):
            rules.append("responsibility.context_dropped")
            continue

        segment = segment.removeprefix("并")
        simple_object = re.fullmatch(r"(?:构建|结合)(?P<body>.+)", segment)
        if simple_object:
            items.append(simple_object.group("body"))
            rules.append("responsibility.action_object")
            continue

        optimization = re.fullmatch(
            r"(?:不断)?优化(?P<body>.+?)(?:的整体效果)?",
            segment,
        )
        if optimization:
            items.extend(_split_enumeration(optimization.group("body")))
            rules.append("responsibility.shared_predicate")
            continue

        action_parts = re.split(r"并(?=(?:设计|推动|定位|开展|实现))", segment)
        items.extend(action_parts)
        rules.append(
            "responsibility.multi_action"
            if len(action_parts) > 1
            else "responsibility.atomic_action"
        )

    return _unique(items), _unique(rules)


def extract_surface_items(
    source_text: str,
    category: SurfaceCategory,
) -> SurfaceItemExtraction:
    """Extract source-grounded items without canonicalizing or calling a model."""

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
        examples=_extract_examples(source_text, category),
        rule_ids=rule_ids,
    )

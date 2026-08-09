from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# These are deliberately canonical, user-matchable labels. Fine-grained terms
# such as MCP, ReAct, and KV Cache remain traceability mentions unless the JD
# explicitly treats them as a standalone required skill.
SKILL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Agent Harness", r"Agent[\s-]*Harness"),
    ("Agent评测", r"Agent\s*(?:评测|评估)"),
    ("Python", r"(?<![A-Za-z])Python(?![A-Za-z])"),
    ("Java", r"(?<![A-Za-z])Java(?![A-Za-z])"),
    ("Go", r"(?<![A-Za-z])Go(?![A-Za-z])"),
    ("C++", r"C\+\+"),
    ("C#", r"C#"),
    ("JavaScript", r"JavaScript"),
    ("TypeScript", r"TypeScript"),
    ("SQL", r"(?<![A-Za-z])SQL(?![A-Za-z])"),
    ("PyTorch", r"PyTorch"),
    ("TensorFlow", r"TensorFlow"),
    ("PaddlePaddle", r"PaddlePaddle"),
    ("LangChain", r"LangChain"),
    ("AutoGen", r"AutoGen"),
    ("RAG", r"(?<![A-Za-z])RAG(?![A-Za-z])"),
    ("Prompt Engineering", r"Prompt\s*Engineering|提示工程"),
    ("Agent", r"(?<![A-Za-z])Agent(?:s)?(?![A-Za-z])|智能体"),
    ("LLM", r"(?<![A-Za-z])LLM(?:s)?(?![A-Za-z])|大模型"),
    ("NLP", r"(?<![A-Za-z])NLP(?![A-Za-z])|自然语言处理"),
    ("Transformer", r"Transformer"),
    ("Linux", r"(?<![A-Za-z])Linux(?![A-Za-z])"),
    ("Docker", r"Docker"),
    ("Kubernetes", r"Kubernetes|(?<![A-Za-z])K8s(?![A-Za-z])"),
    ("CUDA", r"CUDA"),
    ("vLLM", r"vLLM"),
    ("SGLang", r"SGLang"),
    ("MNN", r"(?<![A-Za-z])MNN(?![A-Za-z])"),
    ("Unity", r"Unity"),
    ("Unreal Engine", r"Unreal(?:\s+Engine)?"),
    ("CMake", r"CMake"),
    ("计算机视觉", r"计算机视觉"),
    ("机器学习", r"机器学习"),
    ("深度学习", r"深度学习"),
    ("强化学习", r"强化学习|(?<![A-Za-z])RL(?![A-Za-z])"),
    ("推荐系统", r"推荐系统|推荐算法"),
    ("搜索", r"搜索引擎|搜索算法"),
    ("数据结构与算法", r"数据结构(?:与|和)算法|数据结构、算法"),
    ("图形学", r"图形学"),
    ("渲染", r"渲染"),
    ("计算机基础知识", r"计算机基础(?:知识)?"),
    ("编程基础", r"代码学习基础|编程基础"),
    ("编程能力", r"编程能力|代码能力"),
    ("数据分析", r"数据分析"),
    ("基础安全隐私知识", r"基础安全隐私知识|安全隐私知识"),
    ("安全漏洞检测", r"安全漏洞[^；。\n]{0,24}检测"),
    ("隐私合规", r"隐私合规"),
    ("数据安全", r"数据安全"),
    ("个人信息保护", r"个人信息保护"),
    ("AI功能工程化实现", r"AI\s*功能(?:的)?\s*工程化实现"),
    ("AI基本原理", r"AI\s*基本原理"),
    ("API调用能力", r"API\s*调用能力"),
    ("算法复现", r"算法复现"),
    ("功能落地", r"功能落地"),
    (
        "AI能力边界理解",
        r"AI\s*能力(?:的)?\s*边界(?:与|和)?(?:应用潜力|可能性)?",
    ),
    (
        "AI产品/方案设计",
        r"AI\s*功能\s*设计|AI\s*(?:为核心(?:或|、)?\s*AI\s*增强型|增强型)?[^。；\n]{0,12}(?:产品|方案)",
    ),
    (
        "AI产品技术趋势",
        r"AI(?:产品)?\s*(?:技术)?(?:趋势|技术发展)|AI[^。；\n]{0,20}技术趋势",
    ),
    (
        "AI产品最佳实践",
        r"AI(?:产品)?\s*最佳实践|AI[^。；\n]{0,20}最佳实践",
    ),
    ("多模态学习", r"多模态学习"),
)

_SOFT_SKILL_PATTERN = re.compile(
    r"结构化思维|逻辑清晰|沟通|表达能力|团队协作|学习能力|自驱力|责任心|"
    r"好奇心|洞察力|审美|英语流利|问题分析与解决能力|综合素质|执行能力|"
    r"用户理解|产品体验|创造力|想象力|专业背景|学历要求",
)


@dataclass(frozen=True)
class SkillMatch:
    canonical: str
    source_text: str
    start: int
    end: int


def extract_skill_matches(value: str) -> list[SkillMatch]:
    """Extract known canonical skills in their source-text order."""

    matches: list[SkillMatch] = []
    for canonical, pattern in SKILL_PATTERNS:
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            matches.append(
                SkillMatch(
                    canonical=canonical,
                    source_text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    matches.sort(key=lambda item: (item.start, item.end, item.canonical))
    return matches


def extract_requirement_skill_matches(source_content: str) -> list[SkillMatch]:
    """Extract known skills from the requirement section of a JD."""

    return _unique_matches(extract_skill_matches(_requirement_text(source_content)))


def normalize_skill_values(
    values: Iterable[Any],
    *,
    keep_unknown: bool = True,
) -> list[str]:
    """Split model phrase-level skills into canonical, matchable labels."""

    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = re.sub(r"\s+", " ", value).strip(" \t\r\n,，、;；")
        if not text or _SOFT_SKILL_PATTERN.search(text):
            continue

        matches = extract_skill_matches(text)
        if matches:
            candidates = [match.canonical for match in matches]
        elif keep_unknown:
            candidates = [text]
        else:
            candidates = []

        for candidate in candidates:
            if candidate not in seen:
                labels.append(candidate)
                seen.add(candidate)
    return labels


def normalize_skill_fields(
    payload: dict[str, Any],
    *,
    source_content: str | None = None,
) -> dict[str, Any]:
    """Normalize required/preferred skills before the domain model validates them.

    When requirements are present, they remain the source of truth. A grouped
    skill requirement is expanded into one requirement per canonical skill and
    reuses the original evidence, which remains a valid contiguous source
    fragment for every expanded item.
    """

    normalized = copy.deepcopy(payload)
    requirements = normalized.get("requirements")
    if isinstance(requirements, list):
        rebuilt: list[dict[str, Any]] = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            category = requirement.get("category")
            if category not in {"required_skill", "preferred_skill"}:
                rebuilt.append(requirement)
                continue

            evidence = requirement.get("evidence") or []
            evidence_texts = [
                item.get("source_text")
                for item in evidence
                if isinstance(item, dict)
            ]
            labels = normalize_skill_values(
                [requirement.get("name"), *evidence_texts],
                keep_unknown=False,
            )
            if not labels:
                labels = normalize_skill_values(
                    [requirement.get("name")],
                    keep_unknown=True,
                )
            if not labels:
                continue
            for label in labels:
                expanded = copy.deepcopy(requirement)
                expanded["name"] = label
                rebuilt.append(expanded)

        normalized["requirements"] = rebuilt
        for category, field_name in (
            ("required_skill", "required_skills"),
            ("preferred_skill", "preferred_skills"),
        ):
            labels = [
                item.get("name")
                for item in rebuilt
                if item.get("category") == category
                and isinstance(item.get("name"), str)
            ]
            if labels:
                normalized[field_name] = labels
            elif field_name in normalized:
                normalized[field_name] = None
    else:
        for field_name in ("required_skills", "preferred_skills"):
            value = normalized.get(field_name)
            if isinstance(value, list):
                normalized[field_name] = normalize_skill_values(value)

    if source_content:
        _augment_required_skills_from_source(normalized, source_content)
    return normalized


def normalize_core_fields(
    payload: dict[str, Any],
    *,
    source_content: str,
) -> dict[str, Any]:
    """Normalize the lightweight Parser contract used by discovery/evaluation."""

    normalized: dict[str, Any] = {
        field_name: payload.get(field_name)
        for field_name in ("job_type", "locations", "required_skills")
    }
    if isinstance(normalized["job_type"], str):
        normalized["job_type"] = normalized["job_type"].strip() or None
    locations = normalized["locations"]
    if isinstance(locations, str):
        locations = re.split(r"[/、,，;；|]", locations)
    if isinstance(locations, list):
        normalized["locations"] = _unique_labels(
            [
                item.strip()
                for item in locations
                if isinstance(item, str) and item.strip()
            ]
        ) or None
    model_skills = normalize_skill_values(
        normalized.get("required_skills")
        if isinstance(normalized.get("required_skills"), list)
        else [normalized["required_skills"]]
        if isinstance(normalized.get("required_skills"), str)
        else [],
        keep_unknown=False,
    )
    source_matches = extract_requirement_skill_matches(source_content)
    source_skills = [match.canonical for match in source_matches]
    merged_skills = _unique_labels([*source_skills, *model_skills])
    normalized["required_skills"] = merged_skills or None
    return normalized


def _augment_required_skills_from_source(
    payload: dict[str, Any],
    source_content: str,
) -> None:
    """Recover explicit technical terms the model omitted from its skill list."""

    # Keep an entirely empty model result as an honest null parse. Source
    # augmentation is a recall aid after the model has entered the skill or
    # requirements path, not a replacement for the Parser's field decision.
    if not payload.get("required_skills") and not payload.get("requirements"):
        return

    requirement_text = _requirement_text(source_content)
    matches = _unique_matches(extract_skill_matches(requirement_text))
    if not matches:
        return

    existing = [
        value
        for value in payload.get("required_skills") or []
        if isinstance(value, str)
    ]
    known_existing = normalize_skill_values(existing, keep_unknown=False)
    labels = _unique_labels(
        [*(match.canonical for match in matches), *known_existing]
    )

    requirements = payload.get("requirements")
    if not isinstance(requirements, list):
        requirements = []
    filtered_requirements: list[dict[str, Any]] = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        if requirement.get("category") != "required_skill":
            filtered_requirements.append(requirement)
            continue
        if normalize_skill_values(
            [requirement.get("name")],
            keep_unknown=False,
        ):
            filtered_requirements.append(requirement)
    requirements = filtered_requirements
    required_by_name = {
        item.get("name"): item
        for item in requirements
        if item.get("category") == "required_skill"
        and isinstance(item.get("name"), str)
    }
    for match in matches:
        if match.canonical in required_by_name:
            continue
        required_by_name[match.canonical] = {
            "category": "required_skill",
            "name": match.canonical,
            "description": f"岗位原文明确提到 {match.source_text}",
            "mandatory": True,
            "evidence": [
                {
                    "field_path": "requirements[]",
                    "source_text": match.source_text,
                }
            ],
        }
    non_required = [
        item
        for item in requirements
        if item.get("category") != "required_skill"
    ]
    ordered_required = [
        required_by_name[label]
        for label in labels
        if label in required_by_name
    ]
    for index, requirement in enumerate(
        ordered_required,
        start=len(non_required),
    ):
        for evidence in requirement.get("evidence") or []:
            if isinstance(evidence, dict):
                evidence["field_path"] = f"requirements[{index}]"
    payload["requirements"] = [*non_required, *ordered_required]
    payload["required_skills"] = labels

    field_evidence = payload.get("field_evidence")
    if not isinstance(field_evidence, list):
        field_evidence = []
        payload["field_evidence"] = field_evidence
    has_skill_evidence = any(
        isinstance(item, dict)
        and (
            item.get("field_path") == "required_skills"
            or str(item.get("field_path", "")).startswith("required_skills[")
        )
        for item in field_evidence
    )
    if not has_skill_evidence:
        field_evidence.append(
            {
                "field_path": "required_skills",
                "source_text": matches[0].source_text,
            }
        )


def _requirement_text(source_content: str) -> str:
    headings = re.finditer(
        r"任职要求|岗位要求|职位要求|资格要求|招聘要求|AI能力要求",
        source_content,
    )
    starts = [match.start() for match in headings]
    return source_content[min(starts) :] if starts else ""


def _unique_matches(matches: Iterable[SkillMatch]) -> list[SkillMatch]:
    result: list[SkillMatch] = []
    seen: set[str] = set()
    for match in matches:
        if match.canonical in seen:
            continue
        result.append(match)
        seen.add(match.canonical)
    return result


def _unique_labels(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result

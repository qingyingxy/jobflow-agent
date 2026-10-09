"""Bounded local entailment: lexical recall is never proof of a whole clause.

Only explicit affirmative claims qualify. Numeric durations and proficiency
are comparable only with the rest of the same clause preserved. Unrecognised
wording stays unresolved; this module does not ask the user or call a model.
"""

from __future__ import annotations

import re
import unicodedata
from itertools import pairwise

from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord, RequirementItemCheck
from src.domain.skill_normalizer import extract_skill_matches

_NON_FACT = re.compile(
    r"未|不具备|不熟|不会|没有|尚无|缺乏|不足|少于|不到|计划|希望|拟|目标|"
    r"要求|需具备|招聘|如果|假设|团队成员|同事|他人|"
    r"\b(?:no|not|never|without|plan|planned|want|would|require[sd]?)\b",
    re.IGNORECASE,
)
_PROFICIENCY = re.compile(r"精通|熟练掌握|熟练使用|熟练|掌握|熟悉|了解")
_RANK = {
    "了解": 1,
    "熟悉": 2,
    "掌握": 3,
    "熟练": 4,
    "熟练使用": 4,
    "熟练掌握": 4,
    "精通": 5,
}
_NUMBER = r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九十]+|半)"
_DURATION = re.compile(
    rf"(?P<number>{_NUMBER})\s*(?P<unit>年|个月|月)(?:以上|及以上|多)?"
)
_CONNECTORS = re.compile(r"并且|并|以及|而且|和|及|与|、|,|，")


def _number(value: str) -> float:
    if value == "半":
        return 0.5
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    digits = {c: i for i, c in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    if "十" in value:
        tens, units = value.split("十", 1)
        return (digits.get(tens, 1) * 10) + digits.get(units, 0)
    return float(digits.get(value, 0))


def _canonical(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    # Replace non-overlapping known aliases, but never erase a qualifier.
    matches = sorted(extract_skill_matches(text), key=lambda m: (m.start, -m.end))
    end = 0
    parts = []
    for match in matches:
        if match.start < end:
            continue
        canonical = match.canonical.casefold()
        if any(
            q in match.source_text and q not in canonical
            for q in ("经验", "原理", "能力", "基础", "熟练", "独立")
        ):
            continue
        parts.extend([text[end : match.start], canonical])
        end = match.end
    parts.append(text[end:])
    return re.sub(r"\s+", "", "".join(parts))


def _skills(text: str) -> set[str]:
    return {m.canonical.casefold() for m in extract_skill_matches(text)}


def _template(text: str) -> tuple[str, list[float], list[int]]:
    durations, levels = [], []

    def duration(match):
        durations.append(
            _number(match["number"]) * (12 if match["unit"] == "年" else 1)
        )
        return "@duration@"

    def proficiency(match):
        levels.append(_RANK[match[0]])
        return "@proficiency@"

    text = _canonical(text)
    text = _DURATION.sub(duration, text)
    text = _PROFICIENCY.sub(proficiency, text)
    # Bounded grammatical wrappers only; responsibilities/results/context stay.
    text = re.sub(r"^(?:要求|需要|需|应|须|至少|具备|具有|拥有|有)", "", text)
    text = re.sub(r"(?:并且|并|以及|且)?(?:具备|具有|拥有|有)(?=@duration@)", "", text)
    text = _CONNECTORS.sub("", text)
    text = text.strip("。.;；:： ")
    return text, durations, levels


def _contains(needle: str, haystack: str) -> bool:
    # ASCII token boundaries prevent Java matching JavaScript, C matching C++.
    left = r"(?<![a-z0-9_+#])" if needle[:1].isascii() and needle[:1].isalnum() else ""
    right = (
        r"(?![a-z0-9_+#])" if needle[-1:].isascii() and needle[-1:].isalnum() else ""
    )
    return bool(needle and re.search(left + re.escape(needle) + right, haystack))


def _entails(required: str, claim: str) -> bool:
    if _NON_FACT.search(claim):
        return False
    wanted, durations, levels = _template(required)
    actual, actual_durations, actual_levels = _template(claim)
    if not wanted or re.search(r"或|任选|至少.{0,8}种|之一|\bor\b", wanted):
        return False
    # Multiple quantitative predicates need a richer binding structure.
    if durations and (len(durations) != 1 or len(actual_durations) != 1):
        return False
    if durations and re.search(
        rf"(?:约|近|最多|至多|不超过|不到|≤|<)\s*{_NUMBER}", claim
    ):
        return False
    if levels and (len(levels) != 1 or len(actual_levels) != 1):
        return False
    if durations and actual_durations[0] < durations[0]:
        return False
    if levels and actual_levels[0] < levels[0]:
        return False
    if len(_skills(required)) > 1 and (levels or durations):
        return wanted == actual
    return _contains(wanted, actual)


def assess_item(source: str, records: list[EvidenceRecord]) -> RequirementItemCheck:
    target_skills = _skills(source)
    best = RequirementItemCheck(source_text=source, support_level="needs_confirmation")
    for record in records:
        # No title/tag-only proof, cross-record joins or accumulation of years.
        for claim in re.split(r"[。；;\n]|(?<!\d)\.(?!\d)", record.claim):
            if not claim.strip() or _NON_FACT.search(claim):
                continue
            overlap = target_skills & _skills(claim)
            if _entails(source, claim):
                return RequirementItemCheck(
                    source_text=source,
                    support_level="supported",
                    evidence_ids=[record.id],
                    evidence_quotes=[claim.strip()],
                    matched_skills=sorted(overlap),
                )
            if overlap and len(overlap) > len(best.matched_skills):
                best = RequirementItemCheck(
                    source_text=source,
                    support_level="partial",
                    evidence_ids=[record.id],
                    evidence_quotes=[claim.strip()],
                    matched_skills=sorted(overlap),
                )
    best.unresolved = ["尚无完整证据支持原文中的能力程度、年限、职责或其他限定"]
    return best


def requirement_sources(requirement: JobRequirement) -> tuple[list[str], bool]:
    """Return source-complete branches, plus whether their relation is executable.

    Prefer the original description over short model-generated labels. For OR,
    only a literal, contiguous list may be expanded with shared qualifiers.
    Complex/non-contiguous scopes remain unknown instead of dropping content.
    """
    description = _canonical(requirement.description)
    fallback = [
        s.strip() for s in re.split(r"[；;。\n]", requirement.description) if s.strip()
    ]
    if requirement.relation == "uncertain":
        return fallback, False
    options = [_canonical(item) for item in requirement.items or []]
    if len(options) < 2:
        return fallback, requirement.relation == "all_of"
    # Full source branches, or bare alternatives under a shared prefix/suffix.
    positions = [description.find(item) for item in options]
    if any(pos < 0 for pos in positions) or len(set(positions)) != len(positions):
        return (
            (fallback, True)
            if requirement.relation == "all_of"
            else (requirement.items, False)
        )
    spans = sorted(
        (pos, pos + len(item), item) for pos, item in zip(positions, options)
    )
    for previous, current in pairwise(spans):
        connector = (
            r"(?:或者|或|、|/|,|，|\bor\b)+"
            if requirement.relation == "any_of"
            else r"(?:并且|和|以及|及|与|且|、|,|，)+"
        )
        if not re.fullmatch(connector, description[previous[1] : current[0]]):
            return (
                (fallback, True)
                if requirement.relation == "all_of"
                else (requirement.items, False)
            )
    prefix, suffix = description[: spans[0][0]], description[spans[-1][1] :]
    if requirement.relation == "any_of":
        suffix = re.sub(
            r"^(?:中)?(?:的)?(?:至少|任意)?(?:一种|一门|一项|任一|之一)(?:编程语言|语言|技术|框架|技能)?",
            "",
            suffix,
        )
    return [prefix + item + suffix for item in options], True

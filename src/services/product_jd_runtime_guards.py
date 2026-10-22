"""Bounded contradiction checks; models still extract and interpret predicates.

These checks deliberately cover explicit list syntax and mixed clause boundaries,
not all natural-language uses of 'or'. They request repair, never grant eligibility.
"""

from __future__ import annotations

import re
import unicodedata
from itertools import pairwise

from src.domain.graduation import quoted_cohort_years
from src.domain.skill_normalizer import extract_skill_matches


class RuntimeExtractionValidationError(ValueError):
    def __init__(self, errors):
        super().__init__("条件边界需要重新抽取")
        self.validation_errors = errors


def explicit_skill_alternatives(source: str) -> bool:
    """Recognize a closed, explicit choice governed by a skill/experience verb."""
    text = re.sub(r"\s+", "", source).strip("。.;；")
    text = re.sub(r"^\d+[.、．)]", "", text)
    if re.search(
        r"自己的思考|复现(?:或|或者)参与|参与(?:或|或者)复现|分析(?:或|或者)解释|相关方向|研发流程|同一体系|相关科研或项目|或相关经验|实习、项目或竞赛",
        text,
    ):
        return False
    if not re.match(r"(?:熟悉|熟练掌握|掌握|了解|具备|具有|有)", text):
        return False
    # A choice between predicates is not a choice between their skill objects.
    if re.match(
        r"(?:熟悉|熟练掌握|掌握|了解)(?:或者|或)"
        r"(?:熟悉|掌握|了解|使用|学习|对|愿意|有兴趣|感兴趣)",
        text,
    ):
        return False
    if re.search(r"[，,；;](?:并且|并|且)?(?:熟悉|掌握|了解|具备|具有|能够|有)", text):
        return False
    if re.match(r"具备(?:较为)?扎实", text) and text.endswith(("基础", "基础知识")):
        return False
    # A choice inside a modifier or between ways of obtaining the same experience
    # is insufficient for automatic contradiction detection.
    if re.search(
        r"或[^或，,；;]*的|(?:科研|研究|实习|项目|竞赛)或(?:科研|研究|实习|项目|竞赛)(?:经验|经历)|"
        r"(?:设计|实施|操作|使用|理论)(?:或者|或)(?:实践|实施|操作|使用)(?:经验|经历)",
        text,
    ):
        return False
    # Example lists alone and mixed common clauses are not a closed choice.
    if re.search(r"如|例如|包括|等", text) and not re.search(
        r"至少(?:一|1)|任一|任选|其中|之一|一种或多种", text
    ):
        return False
    if re.search(r"至少(?:一|1)|任一|任选|之一|一种或多种", text):
        if re.search(r"、|或|,|，", text):
            return True
        # Slashes may be a compound (CI/CD) or an alias (Kubernetes/K8s).
        # Force repair only when both operands are known, different skills.
        return any(
            left and right and left != right
            for match in re.finditer(r"([A-Za-z0-9.+#_-]+)/([A-Za-z0-9.+#_-]+)", text)
            for left, right in [
                (
                    {s.canonical for s in extract_skill_matches(match[1])},
                    {s.canonical for s in extract_skill_matches(match[2])},
                )
            ]
        )
    return bool(re.fullmatch(r"[^，,；;。]+(?:或者|或)[^，,；;。]+", text))


def requirement_boundary_issue(source: str) -> str | None:
    clauses = [s.strip() for s in re.split(r"[，,；;]|并且", source) if s.strip()]
    if len(clauses) < 2:
        return None
    # A stand-alone mandatory degree followed by a preferred major/background.
    if (
        re.search(r"本科|硕士|博士|学士", clauses[0])
        and not re.search(r"优先|加分|最好", clauses[0])
        and re.search(r"专业|学科|背景", "，".join(clauses[1:]))
        and re.search(r"优先|加分|最好", "，".join(clauses[1:]))
    ):
        return "学历要求与专业优先强度不同，须拆成 required 学历和 preferred 专业条件，各自引用原文"
    # Two independent predicates, one of which explicitly allows a choice.
    # Do not use punctuation alone, or split a multi-line list under one wrapper.
    for left, right in pairwise(clauses):
        if explicit_skill_alternatives(left) != explicit_skill_alternatives(right):
            common = right if explicit_skill_alternatives(left) else left
            if re.match(
                r"(?:并|且|同时)?(?:能够|具备|熟悉|熟练掌握|掌握|了解|有|具有)", common
            ) and not re.search(r"兴趣|热爱|意愿|沟通|责任心|优先|加分", common):
                return "共同要求与明确备选要求须拆成独立条件，不能把共同要求放入 any_of 或合并为 all_of"
    return None


def validate_runtime_extraction_boundaries(extraction) -> None:
    errors = []
    fact = extraction.facts.graduation_years
    if fact and not set(fact.values) <= quoted_cohort_years(fact.source_text):
        errors.append(
            {
                "location": ["facts", "graduation_years", "values"],
                "message": "届别数值必须由原文明示年份或20至49届简称支持，不能猜年份",
                "source_text": fact.source_text,
            }
        )
    for index, requirement in enumerate(extraction.requirements):
        issue = requirement_boundary_issue(requirement.source_text)
        if issue:
            errors.append(
                {
                    "location": ["requirements", index, "source_text"],
                    "message": issue,
                    "source_text": requirement.source_text,
                }
            )
    if errors:
        raise RuntimeExtractionValidationError(errors)


def validate_runtime_skill_relation(requirement, decision) -> None:
    if (
        decision.education is None
        and explicit_skill_alternatives(requirement.source_text)
        and decision.relation != "any_of"
    ):
        raise ValueError(
            "明确的技能或经历备选须用 any_of；preferred 仅表示强度，不改变任选关系"
        )


def validate_reextraction_coverage(previous_output, extraction) -> None:
    """A full boundary repair may split spans, but cannot delete known clauses."""
    previous = previous_output.get("extraction", previous_output)
    for index, original in enumerate(previous.get("requirements", [])):
        source = original["source_text"]
        # A split preference may legitimately correct a previously mixed level.
        mixed_level = requirement_boundary_issue(source) and re.search(
            r"优先|加分|最好", source
        )
        covered = set()
        for requirement in extraction.requirements:
            if not mixed_level and requirement.level != original["level"]:
                continue
            quote = requirement.source_text
            if source in quote:
                covered.update(range(len(source)))
            elif quote in source:
                for match in re.finditer(re.escape(quote), source):
                    covered.update(range(match.start(), match.end()))
        # Formatting and inter-clause connectors need not belong to either quote.
        optional = set()
        for match in re.finditer(
            r"^\s*\d+[.、．)]|并且|(?:并|且|同时)(?=能够|具备|熟悉|掌握|了解|有|具有)",
            source,
        ):
            optional.update(range(match.start(), match.end()))
        if any(
            position not in covered
            and position not in optional
            and not char.isspace()
            and not unicodedata.category(char).startswith("P")
            for position, char in enumerate(source)
        ):
            raise ValueError(
                f"重新抽取不得删除原条件 requirements[{index}] 的实质内容或降低共同要求强度"
            )
        if mixed_level:
            parts = [p.strip() for p in re.split(r"[，,；;]|并且", source) if p.strip()]
            for part_index, part in enumerate(parts):
                degree_is_hard = part_index == 0 and requirement_boundary_issue(
                    source
                ).startswith("学历要求")
                if re.search(r"优先|加分|最好", part) or not (
                    degree_is_hard or original["level"] == "required"
                ):
                    continue
                # Reuse exact coverage on this protected fragment at required strength.
                validate_reextraction_coverage(
                    {"requirements": [{"source_text": part, "level": "required"}]},
                    extraction,
                )

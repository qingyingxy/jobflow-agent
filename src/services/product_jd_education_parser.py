"""Product runtime v6; frozen product extraction/parser contracts stay unchanged."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import Field, model_validator

from src.domain.education import (
    EducationCondition,
    degree_levels,
    validate_condition_grounding,
)
from src.domain.graduation import (
    COHORT_YEAR_PATTERN,
    classify_graduation_condition,
    cohort_conflict_sources,
    cohort_source_fragments,
    quoted_cohort_years,
    simple_cohort_years,
)
from src.domain.job import (
    FieldEvidence,
    RawJobDocument,
    SkillRequirementGroup,
    StructuredJobDescription,
)
from src.domain.product_jd import (
    ProductJDExtractionOutput,
    ProductRelationDecision,
    ProductRelationJudgmentOutput,
    ProductYearListFact,
)
from src.infrastructure.llm_client import StructuredModelClient, StructuredModelRequest
from src.services.jd_parser import JDParserError, ParsedJobDescription
from src.services.product_jd_parser import ProductJDParser as FrozenProductJDParser
from src.services.product_jd_parser import compile_product_jd


def education_relation_items(condition: EducationCondition) -> list[str]:
    """Adapt shared evidence to the frozen display contract, without choosing logic."""
    sources = [b.source_text for b in condition.branches]
    if len(set(sources)) == len(sources):
        return sources
    for quotes in (
        [b.degree.source_text for b in condition.branches],
        [b.major.source_text for b in condition.branches],
        [b.graduation_source_text for b in condition.branches],
    ):
        if all(quotes) and len(set(quotes)) == len(quotes):
            return quotes
    raise ValueError("教育备选分支需要不同的字段证据；整句可以共享，资格谓词不能重复")


class RuntimeRelationDecision(ProductRelationDecision):
    education: EducationCondition | None = None

    @model_validator(mode="before")
    @classmethod
    def shared_education_evidence(cls, value):
        if not isinstance(value, dict) or value.get("relation") != "any_of":
            return value
        items = value.get("items", [])
        if value.get("education") and isinstance(items, list) and len(set(items)) < 2:
            condition = EducationCondition.model_validate(value["education"])
            return {**value, "items": education_relation_items(condition)}
        return value


class RuntimeRelationOutput(ProductRelationJudgmentOutput):
    decisions: list[RuntimeRelationDecision] = Field(
        default_factory=list, max_length=50
    )


def normalize_repeated_cohort(output, extraction):
    """Drop exact copies of a simple global cohort from application branches.

    The independently stated global constraint is still enforced by eligibility.
    Neither scoped years nor historical records are changed.
    """
    fact = extraction.facts.graduation_years
    if fact is None or classify_graduation_condition(fact.source_text) != "simple":
        return output
    decisions = []
    for decision in output.decisions:
        condition = decision.education
        if condition:
            branches = [
                b.model_copy(
                    update={"graduation_years": None, "graduation_source_text": None}
                )
                if b.scope == "application"
                and b.graduation_years is not None
                and set(b.graduation_years) == set(fact.values)
                and b.graduation_source_text == fact.source_text
                and set(fact.values) <= quoted_cohort_years(fact.source_text)
                else b
                for b in condition.branches
            ]
            decision = decision.model_copy(
                update={
                    "education": condition.model_copy(update={"branches": branches})
                }
            )
        decisions.append(decision)
    return output.model_copy(update={"decisions": decisions})


def _cohort_fully_in_education(output, decisions):
    fact = output.facts.graduation_years
    if fact is None:
        return False
    # Only a pure cohort + degree quote is covered. Geographic, date-window,
    # conditional or other unsupported qualifiers retain the global gate.
    source = re.sub(r"\s+", "", fact.source_text).strip("。.;；")
    if not re.fullmatch(
        rf"{COHORT_YEAR_PATTERN}(?:获得|取得)?(?:本科|硕士|博士)(?:研究生)?(?:及其以上|及以上|以上)?(?:学历|学位)?",
        source,
    ):
        return False
    for decision in decisions.decisions:
        requirement = output.requirements[decision.requirement_index]
        condition = decision.education
        if (
            requirement.level != "required"
            or condition is None
            or condition.relation == "uncertain"
            or fact.source_text.rstrip("。.;；") not in requirement.source_text
        ):
            continue
        matching = [
            b.scope == "application"
            and b.graduation_years is not None
            and set(b.graduation_years) == set(fact.values)
            and b.graduation_source_text is not None
            and b.graduation_source_text in fact.source_text
            for b in condition.branches
        ]
        if all(matching) if condition.relation == "any_of" else any(matching):
            return True
    return False


def _cohort_context_sources(output, decisions, document):
    """A recruitment batch cannot override a qualified application cohort.

    Keep both quotes as evidence and make the global gate indeterminate rather
    than converting a project label into an exact, conflicting hard requirement.
    Independently stated '面向2027届毕业生' constraints remain independent.
    """
    fact = output.facts.graduation_years
    if fact is None or classify_graduation_condition(fact.source_text) != "simple":
        return []
    if not re.search(r"校园招聘|校招|应届生招聘", fact.source_text):
        return []
    historical = tuple(
        branch.source_text
        for decision in decisions.decisions
        if decision.education
        for branch in decision.education.branches
        if branch.scope == "historical"
    )
    sources = cohort_conflict_sources(
        fact.source_text,
        document.raw_content,
        title=document.source_metadata.get("title"),
        historical=historical,
    )
    for decision in decisions.decisions:
        if (
            output.requirements[decision.requirement_index].level != "required"
            or not decision.education
        ):
            continue
        for branch in decision.education.branches:
            if branch.scope != "application":
                continue
            quote = branch.graduation_source_text or branch.source_text
            if not quoted_cohort_years(quote):
                continue
            qualified = bool(
                re.search(
                    r"以后|之后|之前|以前|至|到|[-~～]|[月日]|海外|境外|国内|境内",
                    quote,
                )
            )
            different = branch.graduation_years is not None and set(
                branch.graduation_years
            ) != set(fact.values)
            if qualified or different:
                sources.append(quote)
    return list(dict.fromkeys(sources))


class RuntimeEducationValidationError(ValueError):
    def __init__(self, message: str, index: int):
        super().__init__(message)
        self.location = ["decisions", index, "education"]


def validate_runtime_education(
    output: RuntimeRelationOutput,
    document_content: str,
    extraction: ProductJDExtractionOutput | None = None,
) -> None:
    """Shared semantic-shape/quote checks for all runtime execution modes."""
    for index, decision in enumerate(output.decisions):
        condition = decision.education
        if condition is None:
            text = " ".join(decision.items)
            if (
                degree_levels(text)
                or any(
                    term in text
                    for term in (
                        "学历",
                        "专业优先",
                        "专业不限",
                        "不限专业",
                    )
                )
                or re.search(
                    r"相关专业(?!名词|术语|知识|技能|能力|技术)|学科(?!知识|基础|能力)",
                    text,
                )
                or text.endswith("专业")
            ):
                raise RuntimeEducationValidationError(
                    "教育资格不得遗漏 education；无法可靠解释请输出 unknown/unresolved",
                    index,
                )
            continue
        try:
            if condition.relation != decision.relation:
                raise ValueError("教育条件与外层关系必须一致")
            if decision.relation == "any_of" and (
                len(condition.branches) != len(decision.items)
                or any(
                    item not in branch.source_text
                    for item, branch in zip(
                        decision.items, condition.branches, strict=True
                    )
                )
            ):
                raise ValueError(
                    "学历备选 items 必须逐项引用对应分支；不同分支可共享整句"
                )
            source = (
                extraction.requirements[decision.requirement_index].source_text
                if extraction is not None
                else " ".join(b.source_text for b in condition.branches)
            )
            if any(b.source_text not in document_content for b in condition.branches):
                raise ValueError("教育分支必须逐字引用 JD 原文")
            validate_condition_grounding(
                condition, source, document_content=document_content
            )
        except ValueError as error:
            raise RuntimeEducationValidationError(str(error), index) from error


class ProductJDParser(FrozenProductJDParser):
    def __init__(
        self,
        client: StructuredModelClient,
        *,
        prompt_version: str = "product-jd-two-stage-v9",
        parser_version: str = "product-jd-parser-v6",
        validation_retries: int = 1,
    ) -> None:
        super().__init__(
            client,
            prompt_version=prompt_version,
            parser_version=parser_version,
            extraction_prompt_version="product-jd-extraction-v9",
            relation_prompt_version="product-jd-relation-v8",
            validation_retries=validation_retries,
        )

    @property
    def schema_version(self) -> str:
        return "product-job-description-v4"

    def build_request(self, document: RawJobDocument) -> StructuredModelRequest:
        request = super().build_request(document)
        request.messages[0].content += (
            "\n毕业年份的 source_text 必须保留完整适用条件，包括国内/海外分支、"
            "毕业时间区间、学历或身份限定，不能只摘取年份而丢掉限定条件。"
            "\n本运行版本覆盖旧的学历 fact 规则：所有学历、专业资格条件都必须保留为"
            "requirements 中的完整原文，包括本科及以上、专业不限和专业优先。"
            "education_requirements、major_requirements 一律 null，避免丢失适用范围。"
            "只适用于某一学历分支的毕业年份不要写入全局 graduation_years，保留在该分支。"
            "例如‘2027届获得本科及以上学历’，年份只写在该教育分支，全局 graduation_years=null。"
            "同强度的学历与专业放在同一完整 requirement 中；互为备选的本科/硕士分支不要拆成两条。"
            "强度不同必须拆分：‘本科及以上学历，计算机相关专业优先’抽为 required ‘本科及以上学历’"
            "和 preferred ‘计算机相关专业优先’，不得把优先专业放进硬学历条件。"
            "共同要求和备选要求也必须拆开，如‘熟悉深度学习基础，了解NLP或CV中的一种或多种方向’，"
            "前半句保留为共同要求，后半句保留为一组备选要求。"
            "重新抽取修复时，可拆分原条件，但不能删除已抽到的实质要求或降低共同要求强度。"
            "‘27届’可以明确归一为2027，但证据仍逐字保留27届；仅支持20至49届的当代简称，不能给99届猜世纪。"
            "同一句同时约束申请学历和历史本科背景时，保留整句上下文，不能丢掉两者的适用范围。"
        )
        return request

    def build_relation_request(self, document, extraction) -> StructuredModelRequest:
        request = super().build_relation_request(document, extraction)
        request.json_schema = RuntimeRelationOutput.model_json_schema()
        request.max_output_tokens = 8000
        request.messages[0].content += (
            "\n本运行版本扩展 decisions：每条额外输出 education（非教育条件为 null）。"
            "教育资格必须输出可执行 EducationCondition，具体字段服从下列 Schema。"
            "education.relation 与外层 relation 相同。每个 branch 表示存在同一段教育经历，"
            "同时满足该分支的学历、专业、毕业年份和在读/毕业要求。"
            "本科计算机相关专业、硕士不限专业应为 any_of：本科 eq bachelor + related 计算机；"
            "硕士 eq master + major any。不限专业绝不能变成 degree any。"
            "any_of 的 items 必须逐项引用对应 branch；不同分支可以共享完整 source_text。"
            "例如‘计算机相关专业的硕士或博士’，两个 branch 均引用整句以保留共同专业要求，"
            "degree 分别引用硕士、博士，items=[硕士,博士]，不要重复整句作为 items。"
            "all_of 的一个 branch 内可同时限制学历和专业；本科和硕士均须满足则用两个 branch。"
            "同一博士学历下的计算机视觉/VLM/机器学习等相关研究方向不是多个学历路径，"
            "使用单个博士分支、major related 和原文方向 values，不能复制相同博士分支凑 any_of。"
            "只有明确‘及以上/至少’才用 gte；没有学历约束用 degree.operator=not_specified。"
            "没有专业约束用 major.mode=not_specified，明确不限才用 any，"
            "无法解释用 unknown。专业原名写入 values，不推断学科族。"
            "status 只表示申请时的当前状态：明确已毕业/已取得学位才用 graduated，明确在读才用 enrolled。"
            "‘2027届获得本科及以上学历’使用 status=any，年份保存在毕业年份字段；不能推断当前已毕业。"
            "无年份限制 graduation_years=null；‘2027届以后’等区间用 null + unresolved，不得只留2027。"
            "‘27届硕士’的 graduation_years=[2027]，graduation_source_text='27届'，保留简称原文。"
            "‘等理工科专业’无法用具体相关专业名单表达时，major.mode=unknown、values=[]、unresolved=true。"
            "学校层次、同等学历、学历以外的条件、复杂日期区间等本结构无法表达的限定，"
            "必须 unresolved=true，不能丢掉后判通过。不要把技能/项目条件混入可通过的教育分支。"
            "每个字段的 source_text 必须逐字来自该 branch.source_text；分支也必须逐字来自原条件。\n"
            "新增 scope 标明适用范围：application 是本次申请所用学历，historical 是另行要求的"
            "历史学历背景，unknown 是无法确定；scope_source_text 引用完整 JD 中支持这个判断的连续上下文。"
            "例如‘面向2027届毕业生，要求硕士学历，本科为计算机相关专业’，硕士分支为 application，"
            "本科专业分支为 historical，二者均引用含‘要求硕士学历，本科为计算机相关专业’的上下文；"
            "2027届只作用于申请用的硕士经历，不要求历史本科也在2027毕业。"
            "‘本科计算机相关专业，硕士不限专业’若表示申请学历的两条备选路径，两条均为 application。"
            "仅看到‘本科’两个字不足以确定它是历史背景；缺乏上下文时 scope=unknown。"
            "分支明确写出的毕业年份仍只约束本分支。不得为了让候选人通过而选择 scope；不读取候选人信息。\n"
            "已经在全局 facts.graduation_years 保存的独立届别不要重复写入 branch.graduation_years。"
            "branch.graduation_source_text 不得借用 scope_source_text 中、但不属于本分支的年份；全局届别由本地绑定到申请学历。\n"
            + json.dumps(request.json_schema, ensure_ascii=False)
        )
        return request

    async def _run_stage(
        self, request, *, stage: str, validator: Callable[[dict[str, Any]], Any]
    ):
        if stage != "relation_judgment":
            return await super()._run_stage(request, stage=stage, validator=validator)

        def validate_runtime(payload):
            output = RuntimeRelationOutput.model_validate(payload)
            # Reuse the frozen index/quote validation after removing the new field.
            legacy = {
                "decisions": [
                    d.model_dump(exclude={"education"}) for d in output.decisions
                ]
            }
            judgment = validator(legacy)
            validate_runtime_education(output, request.messages[1].content)
            return judgment

        return await super()._run_stage(
            request, stage=stage, validator=validate_runtime
        )

    async def parse(self, document: RawJobDocument) -> ParsedJobDescription:
        try:
            return await self._parse_runtime(document)
        except (TypeError, ValueError) as error:
            raise JDParserError(
                "product_jd_compile_invalid",
                "产品 JD 教育资格无法编译为存储结构",
                {"stage": "compile", "errors": [{"message": str(error)}]},
            ) from error

    async def _parse_runtime(self, document: RawJobDocument) -> ParsedJobDescription:
        result = await self.parse_model_output(document)
        return self.compile_result(document, result)

    def compile_result(self, document, result) -> ParsedJobDescription:
        """Both execution modes compile through the same education/evidence rules."""
        decisions = RuntimeRelationOutput.model_validate(
            result.raw_relation_judgment or {"decisions": []}
        )
        output = result.output
        # Recover only a literal, recognized recruitment-cohort header. Preserve
        # conflicts below; never turn a title or an arbitrary year into a gate.
        if output.facts.graduation_years is None:
            headers = [
                quote
                for quote in cohort_source_fragments(document.raw_content)
                if re.search(r"校园招聘|校招|应届生招聘", quote)
                and simple_cohort_years(quote) is not None
            ]
            if headers:
                output = output.model_copy(
                    update={
                        "facts": output.facts.model_copy(
                            update={
                                "graduation_years": ProductYearListFact(
                                    values=sorted(simple_cohort_years(headers[0])),
                                    source_text=headers[0],
                                )
                            }
                        )
                    }
                )
                decisions = normalize_repeated_cohort(decisions, output)
        if _cohort_fully_in_education(output, decisions):
            output = output.model_copy(
                update={
                    "facts": output.facts.model_copy(update={"graduation_years": None})
                }
            )
        structured = compile_product_jd(output, document)
        requirements = list(structured.requirements or [])
        for decision in decisions.decisions:
            if decision.education:
                validate_condition_grounding(
                    decision.education,
                    requirements[decision.requirement_index].description,
                    document_content=document.raw_content,
                )
                scope_evidence = [
                    FieldEvidence(
                        field_path=f"requirements[{decision.requirement_index}].education.branches[{i}].scope",
                        source_text=branch.scope_source_text,
                    )
                    for i, branch in enumerate(decision.education.branches)
                    if branch.scope_source_text
                ]
                requirements[decision.requirement_index] = requirements[
                    decision.requirement_index
                ].model_copy(
                    update={
                        "education": decision.education,
                        "category": "education",
                        "evidence": [
                            *(requirements[decision.requirement_index].evidence or []),
                            *scope_evidence,
                        ],
                    }
                )
        payload = structured.model_dump()
        payload["requirements"] = [r.model_dump() for r in requirements] or None
        evidence = [
            e
            for e in structured.field_evidence or []
            if not e.field_path.startswith(
                ("required_skills[", "preferred_skills[", "required_skill_groups[")
            )
        ]
        for category, field in (
            ("required_skill", "required_skills"),
            ("preferred_skill", "preferred_skills"),
        ):
            selected = [r for r in requirements if r.category == category]
            payload[field] = [r.name for r in selected] or None
            evidence.extend(
                FieldEvidence(field_path=f"{field}[{i}]", source_text=r.description)
                for i, r in enumerate(selected)
            )
        groups = [
            r
            for r in requirements
            if r.category == "required_skill" and r.relation == "any_of"
        ]
        payload["required_skill_groups"] = [
            SkillRequirementGroup(name=r.name[:80], any_of=r.items).model_dump()
            for r in groups
        ] or None
        evidence.extend(
            FieldEvidence(
                field_path=f"required_skill_groups[{i}]", source_text=r.description
            )
            for i, r in enumerate(groups)
        )
        payload["field_evidence"] = [e.model_dump() for e in evidence]
        context_sources = _cohort_context_sources(output, decisions, document)
        payload["field_evidence"].extend(
            FieldEvidence(
                field_path="graduation_years",
                source_text=source,
                source_kind="body" if source in document.raw_content else "metadata",
            ).model_dump()
            for source in context_sources
        )
        structured = StructuredJobDescription.model_validate(payload)
        for item in [
            *(structured.field_evidence or []),
            *(e for r in structured.requirements or [] for e in r.evidence or []),
        ]:
            if item.source_kind == "body":
                start = document.raw_content.find(item.source_text)
                if start < 0:
                    raise ValueError("编译后引用没有原文依据")
                item.start_char, item.end_char = start, start + len(item.source_text)
        sources = [
            item.source_text
            for item in structured.field_evidence or []
            if item.field_path == "graduation_years"
        ]
        if sources:
            source = "；".join(dict.fromkeys(sources))
            structured = structured.model_copy(
                update={
                    "graduation_condition_kind": "qualified"
                    if context_sources
                    else classify_graduation_condition(source),
                    "graduation_source_text": source,
                }
            )
        return ParsedJobDescription(
            structured_jd=structured,
            input_hash=hashlib.sha256(document.raw_content.encode("utf-8")).hexdigest(),
            schema_version=self.schema_version,
            parser_version=self.parser_version,
            prompt_version=self.prompt_version,
            model=result.model,
        )

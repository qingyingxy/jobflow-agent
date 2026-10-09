"""Product runtime v6; frozen product extraction/parser contracts stay unchanged."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import Field

from src.domain.education import (
    EducationCondition,
    degree_levels,
    validate_condition_grounding,
)
from src.domain.graduation import classify_graduation_condition
from src.domain.job import (
    FieldEvidence,
    RawJobDocument,
    SkillRequirementGroup,
    StructuredJobDescription,
)
from src.domain.product_jd import ProductRelationDecision, ProductRelationJudgmentOutput
from src.infrastructure.llm_client import StructuredModelClient, StructuredModelRequest
from src.services.jd_parser import JDParserError, ParsedJobDescription
from src.services.product_jd_parser import ProductJDParser as FrozenProductJDParser
from src.services.product_jd_parser import compile_product_jd


class RuntimeRelationDecision(ProductRelationDecision):
    education: EducationCondition | None = None


class RuntimeRelationOutput(ProductRelationJudgmentOutput):
    decisions: list[RuntimeRelationDecision] = Field(
        default_factory=list, max_length=50
    )


def validate_runtime_education(
    output: RuntimeRelationOutput, document_content: str
) -> None:
    """Shared semantic-shape/quote checks for all runtime execution modes."""
    for decision in output.decisions:
        condition = decision.education
        if condition is None:
            text = " ".join(decision.items)
            if (
                degree_levels(text)
                or any(
                    term in text
                    for term in (
                        "学历",
                        "相关专业",
                        "专业优先",
                        "专业不限",
                        "不限专业",
                        "学科",
                    )
                )
                or text.endswith("专业")
            ):
                raise ValueError(
                    "教育资格不得遗漏 education；无法可靠解释请输出 unknown/unresolved"
                )
            continue
        if condition.relation != decision.relation:
            raise ValueError("教育条件与外层关系必须一致")
        if (
            decision.relation == "any_of"
            and [b.source_text for b in condition.branches] != decision.items
        ):
            raise ValueError("学历备选分支必须与 items 一一对应")
        validate_condition_grounding(
            condition, " ".join(decision.items), document_content=document_content
        )


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
            extraction_prompt_version="product-jd-extraction-v8",
            relation_prompt_version="product-jd-relation-v7",
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
            "学历与专业必须放在同一完整 requirement 中；互为备选的本科/硕士分支不要拆成两条。"
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
            "any_of 的 items 和 branches.source_text 必须一一相等，保留完整资格分支。"
            "all_of 的一个 branch 内可同时限制学历和专业；本科和硕士均须满足则用两个 branch。"
            "只有明确‘及以上/至少’才用 gte；没有学历约束用 degree.operator=not_specified。"
            "没有专业约束用 major.mode=not_specified，明确不限才用 any，"
            "无法解释用 unknown。专业原名写入 values，不推断学科族。"
            "没有明确已毕业/在读限制时 status=any；无年份限制 graduation_years=null。"
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
        structured = compile_product_jd(result.output, document)
        decisions = RuntimeRelationOutput.model_validate(
            result.raw_relation_judgment or {"decisions": []}
        )
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
                    "graduation_condition_kind": classify_graduation_condition(source),
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

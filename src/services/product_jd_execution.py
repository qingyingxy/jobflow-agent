"""Resumable product parsing and an opt-in single-call comparison path."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from src.domain.job import RawJobDocument
from src.domain.product_jd import (
    ProductJDExtractionOutput,
    ProductJDModelOutput,
    ProductRelationJudgmentOutput,
    ProductRequirement,
    validate_product_jd_extraction,
    validate_product_jd_output,
    validate_product_relation_judgment,
)
from src.domain.product_jd_single_call import (
    SingleCallOutput,
    SingleCallRepairOutput,
    SingleCallRequirement,
)
from src.infrastructure.llm_client import StructuredModelRequest
from src.services.jd_parser import JDParserError, ParsedJobDescription
from src.services.product_jd_education_parser import (
    ProductJDParser as EducationParser,
)
from src.services.product_jd_education_parser import (
    RuntimeRelationDecision,
    RuntimeRelationOutput,
    education_relation_items,
    normalize_repeated_cohort,
    validate_runtime_education,
)
from src.services.product_jd_parser import ProductJDModelParseResult
from src.services.product_jd_recovery import ParseExecutionBudget
from src.services.product_jd_runtime_guards import (
    RuntimeExtractionValidationError,
    validate_reextraction_coverage,
    validate_runtime_extraction_boundaries,
    validate_runtime_skill_relation,
)
from src.services.product_jd_single_call_prompt import SINGLE_CALL_RULES

ParseMode = Literal["two_stage", "single_call"]


class CombinedOutput(BaseModel):
    """Read compatibility for previously recorded v1 outputs, not the new prompt."""

    model_config = ConfigDict(extra="forbid")
    extraction: ProductJDExtractionOutput
    relations: RuntimeRelationOutput


class SingleCallValidationError(ValueError):
    def __init__(self, errors, indices):
        super().__init__("单次输出的部分条件未通过校验")
        self.validation_errors = errors
        self.requirement_indices = indices


@dataclass(frozen=True)
class ExecutionParsedJobDescription(ParsedJobDescription):
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProductJDExecutionParser(EducationParser):
    def __init__(
        self,
        client,
        *,
        mode: ParseMode = "two_stage",
        prompt_version: str | None = None,
        parser_version: str = "product-jd-parser-v10",
        validation_retries: int = 1,
        transport_retries: int = 0,
        retry_backoff_seconds: float = 1.5,
        run_timeout_seconds: float = 300,
        max_model_calls: int = 6,
    ):
        if mode not in {"two_stage", "single_call"}:
            raise ValueError("Unsupported product parse mode")
        self.mode = mode
        if not 0 <= transport_retries <= 3 or retry_backoff_seconds < 0:
            raise ValueError("Invalid product parse retry policy")
        if run_timeout_seconds <= 0 or max_model_calls < 1:
            raise ValueError("Product parse budgets must be positive")
        self.transport_retries = transport_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.run_timeout_seconds = run_timeout_seconds
        self.max_model_calls = max_model_calls
        super().__init__(
            client,
            prompt_version=prompt_version
            or (
                "product-jd-two-stage-v12"
                if mode == "two_stage"
                else "product-jd-single-call-v4-inline"
            ),
            # Invalidate caches even when .env pins an older version label.
            parser_version=parser_version
            + "-execution-v12"
            + ("-single-call" if mode == "single_call" else ""),
            validation_retries=validation_retries,
        )

    def checkpoint_key(self, document: RawJobDocument) -> str:
        # Never persist credentials. The request hash also invalidates changed prompts/schema.
        return _hash(
            {
                "version": "product-extraction-checkpoint-v1",
                "parser": self.parser_version,
                "prompt": self.prompt_version,
                "schema": self.schema_version,
                "mode": self.mode,
                "model": self.model_name,
                "provider": self.client.provider,
                "endpoint": getattr(self.client, "_endpoint", None),
                "reasoning_effort": getattr(self.client, "reasoning_effort", None),
                "thinking_mode": getattr(self.client, "_thinking_mode", None),
                "response_format": getattr(self.client, "response_format", None),
                "request": self.build_request(document).model_dump(mode="json"),
            }
        )

    def build_combined_request(
        self, document: RawJobDocument
    ) -> StructuredModelRequest:
        schema = SingleCallOutput.model_json_schema()
        return StructuredModelRequest(
            schema_name="product_job_inline",
            json_schema=schema,
            messages=[
                {
                    "role": "system",
                    "content": (
                        SINGLE_CALL_RULES
                        + "\n"
                        + json.dumps(schema, ensure_ascii=False)
                    ),
                },
                {
                    "role": "user",
                    "content": f"<job_description>\n{document.raw_content}\n</job_description>",
                },
            ],
            prompt_version=self.prompt_version,
            max_output_tokens=12000,
        )

    @staticmethod
    def _inline_decision(requirement, index):
        value = SingleCallRequirement.model_validate(requirement)
        items = value.items
        if value.education is not None:
            items = (
                education_relation_items(value.education)
                if value.relation == "any_of"
                else [value.source_text]
            )
        return {
            "requirement_index": index,
            "relation": value.relation,
            "items": items,
            "reason": value.reason,
            "education": value.education,
        }

    @staticmethod
    def _validation_errors(error, prefix=()):
        if isinstance(error, ValidationError):
            return [
                {"location": [*prefix, *e["loc"]], "message": e["msg"]}
                for e in error.errors()
            ]
        if isinstance(
            error, (SingleCallValidationError, RuntimeExtractionValidationError)
        ):
            return error.validation_errors
        return [{"location": [*prefix], "message": str(error)}]

    def _single_parts(self, payload, document):
        if not isinstance(payload, dict):
            raise TypeError("单次输出必须为对象")
        if set(payload) == {"extraction", "relations"}:
            extraction = self._extraction(payload["extraction"], document)
            relations = payload["relations"]
            if not isinstance(relations, dict) or set(relations) != {"decisions"}:
                raise ValueError("旧单次输出必须有完整 decisions")
            raw = relations["decisions"]
            if not isinstance(raw, list) or len(raw) != len(extraction.requirements):
                raise ValueError("关系判断必须完整覆盖所有 requirement_index")
            indices = [d.get("requirement_index") for d in raw if isinstance(d, dict)]
            if set(indices) != set(range(len(extraction.requirements))) or len(
                set(indices)
            ) != len(raw):
                raise ValueError("关系判断包含缺失或重复的 requirement_index")
            return extraction, sorted(raw, key=lambda d: d["requirement_index"]), False
        if set(payload) - {"facts", "requirements", "responsibilities"}:
            raise ValueError("单次输出只允许 facts、requirements、responsibilities")
        raw = payload.get("requirements", [])
        if not isinstance(raw, list):
            raise TypeError("requirements 必须为数组")
        extraction = self._extraction(
            {
                "facts": payload.get("facts"),
                "requirements": [
                    {k: r[k] for k in ("source_text", "level") if k in r}
                    if isinstance(r, dict)
                    else r
                    for r in raw
                ],
                "responsibilities": payload.get("responsibilities", []),
            },
            document,
        )
        return extraction, raw, True

    def _single_relations(self, extraction, raw, inline, document):
        decisions, errors, invalid_indices = [], [], []
        for index, requirement in enumerate(raw):
            try:
                value = (
                    self._inline_decision(requirement, index) if inline else requirement
                )
                decision = RuntimeRelationDecision.model_validate(value)
                decision = normalize_repeated_cohort(
                    RuntimeRelationOutput(decisions=[decision]), extraction
                ).decisions[0]
                # Use the frozen quote checks on an isolated, locally indexed span.
                isolated = ProductJDExtractionOutput(
                    facts={}, requirements=[extraction.requirements[index]]
                )
                legacy = decision.model_dump(exclude={"education"})
                legacy["requirement_index"] = 0
                validate_product_relation_judgment(
                    ProductRelationJudgmentOutput(decisions=[legacy]), isolated
                )
                validate_runtime_education(
                    RuntimeRelationOutput(decisions=[decision]),
                    document.raw_content,
                    extraction,
                )
                validate_runtime_skill_relation(
                    extraction.requirements[index], decision
                )
                decisions.append(decision)
            except (ValidationError, TypeError, ValueError) as error:
                invalid_indices.append(index)
                errors.extend(self._validation_errors(error, ("requirements", index)))
        if errors:
            raise SingleCallValidationError(errors, invalid_indices)
        relations = RuntimeRelationOutput(decisions=decisions)
        result = self._result(extraction, relations, [])
        validate_product_jd_output(result.output, document.raw_content)
        self.compile_result(document, result)
        return extraction, relations

    def _single_repair_request(self, document, extraction, raw, inline, error):
        schema = SingleCallRepairOutput.model_json_schema()
        selected = [
            {
                "requirement_index": i,
                "source_text": extraction.requirements[i].source_text,
                "level": extraction.requirements[i].level,
                "previous_output": raw[i],
            }
            for i in error.requirement_indices
        ]
        request = StructuredModelRequest(
            schema_name="product_requirement_repair",
            json_schema=schema,
            messages=[
                {
                    "role": "system",
                    "content": SINGLE_CALL_RULES
                    + "\n本次只返回 repaired_requirements，逐项修复下面指定索引。"
                    "不得更改 source_text、level，不得删除条件或补充其他索引。"
                    "每项 requirement 使用内联条件结构，教育无法确定时用 unknown/unresolved。\n"
                    + json.dumps(schema, ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": f"<job_description>\n{document.raw_content}\n</job_description>\n"
                    + json.dumps(
                        {"requirements": selected, "errors": error.validation_errors},
                        ensure_ascii=False,
                    ),
                },
            ],
            prompt_version=self.prompt_version + "-repair",
            max_output_tokens=8000,
        )

        def validate_repair(payload):
            repaired = SingleCallRepairOutput.model_validate(payload)
            indices = [r.requirement_index for r in repaired.repaired_requirements]
            if len(indices) != len(set(indices)) or set(indices) != set(
                error.requirement_indices
            ):
                raise ValueError("局部修复必须恰好覆盖指定索引，不得遗漏、重复或新增")
            # Preserve all untouched decisions and all stage-one evidence.
            merged = [
                self._inline_decision(value, i)
                if inline and i not in indices
                else value
                for i, value in enumerate(raw)
            ]
            for replacement in repaired.repaired_requirements:
                i, value = replacement.requirement_index, replacement.requirement
                original = extraction.requirements[i]
                if (
                    value.source_text != original.source_text
                    or value.level != original.level
                ):
                    raise ValueError("局部修复不得改写条件原文或条件强度")
                merged[i] = self._inline_decision(value, i)
            return self._single_relations(extraction, merged, False, document)

        return request, validate_repair

    @staticmethod
    def _extraction(payload, document):
        extraction = ProductJDExtractionOutput.model_validate(payload)
        validate_product_jd_extraction(extraction, document.raw_content)
        validate_runtime_extraction_boundaries(extraction)
        return extraction

    @staticmethod
    def _relations(payload, extraction, document):
        output = RuntimeRelationOutput.model_validate(payload)
        output = normalize_repeated_cohort(output, extraction)
        legacy = ProductRelationJudgmentOutput.model_validate(
            {
                "decisions": [
                    d.model_dump(exclude={"education"}) for d in output.decisions
                ]
            }
        )
        validate_product_relation_judgment(legacy, extraction)
        validate_runtime_education(output, document.raw_content, extraction)
        for decision in output.decisions:
            validate_runtime_skill_relation(
                extraction.requirements[decision.requirement_index], decision
            )
        return output

    async def _execute_stage(
        self, request, *, stage, validator, attempts, budget, repair_builder=None
    ):
        for attempt in range(self.validation_retries + 1):
            response, details = await budget.generate(
                self.client,
                request,
                stage=stage,
                attempt=attempt + 1,
                attempts=attempts,
            )
            try:
                value = validator(response.output)
            except (ValidationError, TypeError, ValueError) as error:
                # Exclude Pydantic input/context: these can contain the entire JD.
                errors = self._validation_errors(error)
                details.update(status="validation_failed", errors=errors)
                if attempt < self.validation_retries:
                    if repair_builder and isinstance(error, SingleCallValidationError):
                        request, validator = repair_builder(response.output, error)
                        details["repair_scope"] = "requirements"
                        details["repair_indices"] = error.requirement_indices
                    else:
                        request = self._repair_request(
                            request,
                            {
                                "stage": stage,
                                "errors": errors,
                                **(
                                    {"previous_output": response.output}
                                    if isinstance(
                                        error, RuntimeExtractionValidationError
                                    )
                                    else {}
                                ),
                            },
                        )
                        if isinstance(error, RuntimeExtractionValidationError):
                            previous_output, previous_validator = (
                                response.output,
                                validator,
                            )

                            def validate_reextraction(
                                payload,
                                previous_validator=previous_validator,
                                previous_output=previous_output,
                            ):
                                result = previous_validator(payload)
                                extraction = (
                                    result[0] if isinstance(result, tuple) else result
                                )
                                validate_reextraction_coverage(
                                    previous_output, extraction
                                )
                                return result

                            validator = validate_reextraction
                        details["repair_scope"] = "full_output"
                    continue
                raise JDParserError(
                    "product_jd_output_invalid",
                    f"产品 JD 的 {stage} 阶段未通过结构或原文证据校验",
                    {"stage": stage, "errors": errors},
                ) from error
            details["status"] = "passed"
            return value
        raise AssertionError("unreachable")

    def _result(self, extraction, relations, attempts):
        by_index = {d.requirement_index: d for d in relations.decisions}
        output = ProductJDModelOutput(
            facts=extraction.facts,
            responsibilities=extraction.responsibilities,
            requirements=[
                ProductRequirement(
                    source_text=r.source_text,
                    level=r.level,
                    relation=by_index[i].relation,
                    items=by_index[i].items,
                    relation_reason=by_index[i].reason,
                )
                for i, r in enumerate(extraction.requirements)
            ],
        )
        return ProductJDModelParseResult(
            output=output,
            raw_extraction=extraction.model_dump(mode="json"),
            raw_relation_judgment=relations.model_dump(mode="json"),
            model=self.model_name,
            model_call_count=len(attempts),
            stage_diagnostics=tuple(attempts),
        )

    async def parse(self, document: RawJobDocument) -> ExecutionParsedJobDescription:
        return await self.parse_with_checkpoint(document)

    async def parse_with_checkpoint(
        self,
        document: RawJobDocument,
        *,
        checkpoint: dict | None = None,
        save_checkpoint: Callable[[dict], None] | None = None,
    ) -> ExecutionParsedJobDescription:
        _, compiled, diagnostics = await self._execute(
            document,
            checkpoint=checkpoint,
            save_checkpoint=save_checkpoint,
        )
        return ExecutionParsedJobDescription(
            **compiled.__dict__, diagnostics=diagnostics
        )

    async def parse_model_output(
        self, document: RawJobDocument
    ) -> ProductJDModelParseResult:
        result, _, _ = await self._execute(document)
        return result

    async def _execute(
        self,
        document: RawJobDocument,
        *,
        checkpoint: dict | None = None,
        save_checkpoint: Callable[[dict], None] | None = None,
    ):
        attempts: list[dict[str, Any]] = []
        budget = ParseExecutionBudget(
            timeout_seconds=self.run_timeout_seconds,
            max_calls=self.max_model_calls,
            transport_retries=self.transport_retries,
            backoff_seconds=self.retry_backoff_seconds,
        )
        resumed = False
        extraction = None
        if (
            self.mode == "two_stage"
            and checkpoint
            and checkpoint.get("key") == self.checkpoint_key(document)
        ):
            try:
                extraction = self._extraction(checkpoint.get("extraction"), document)
                resumed = True
            except (ValidationError, ValueError, TypeError):
                pass  # Never trust a stale/corrupt intermediate JSON snapshot.
        try:
            if self.mode == "single_call":

                def validate_combined(payload):
                    extracted, raw, inline = self._single_parts(payload, document)
                    return self._single_relations(extracted, raw, inline, document)

                def repair_combined(payload, error):
                    extracted, raw, inline = self._single_parts(payload, document)
                    return self._single_repair_request(
                        document, extracted, raw, inline, error
                    )

                extraction, relations = await self._execute_stage(
                    self.build_combined_request(document),
                    stage="combined",
                    validator=validate_combined,
                    attempts=attempts,
                    budget=budget,
                    repair_builder=repair_combined,
                )
            else:
                if extraction is None:
                    extraction = await self._execute_stage(
                        self.build_request(document),
                        stage="extraction",
                        validator=lambda payload: self._extraction(payload, document),
                        attempts=attempts,
                        budget=budget,
                    )
                if save_checkpoint:
                    save_checkpoint(
                        {
                            "key": self.checkpoint_key(document),
                            "extraction": extraction.model_dump(mode="json"),
                            "origin_attempts": checkpoint.get("origin_attempts", [])
                            if resumed
                            else list(attempts),
                            "origin_run_id": checkpoint.get("origin_run_id")
                            if resumed
                            else None,
                        }
                    )
                relations = RuntimeRelationOutput()
                if extraction.requirements:

                    def validate_relations(payload):
                        relations = self._relations(payload, extraction, document)
                        self.compile_result(
                            document, self._result(extraction, relations, [])
                        )
                        return relations

                    relations = await self._execute_stage(
                        self.build_relation_request(document, extraction),
                        stage="relation_judgment",
                        validator=validate_relations,
                        attempts=attempts,
                        budget=budget,
                    )
            result = self._result(extraction, relations, attempts)
            validate_product_jd_output(result.output, document.raw_content)
            compiled = self.compile_result(document, result)
            budget.check_time("compile")
        except (TypeError, ValueError) as error:
            raise JDParserError(
                "product_jd_compile_invalid",
                "产品 JD 结果无法编译",
                {
                    "stage": "compile",
                    "mode": self.mode,
                    "model_call_count": len(attempts),
                    "resumed_extraction": resumed,
                    "attempts": attempts,
                },
            ) from error
        except JDParserError as error:
            raise JDParserError(
                error.code,
                str(error),
                {
                    **error.details,
                    "mode": self.mode,
                    "model_call_count": len(attempts),
                    "resumed_extraction": resumed,
                    "attempts": attempts,
                },
            ) from error
        return (
            result,
            compiled,
            {
                "mode": self.mode,
                "model_call_count": len(attempts),
                "resumed_extraction": resumed,
                "resumed_from_run_id": checkpoint.get("origin_run_id")
                if resumed
                else None,
                "attempts": attempts,
            },
        )

"""Resumable product parsing and an opt-in single-call comparison path."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
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
from src.infrastructure.llm_client import ModelClientError, StructuredModelRequest
from src.services.jd_parser import JDParserError, ParsedJobDescription
from src.services.product_jd_education_parser import (
    ProductJDParser as EducationParser,
)
from src.services.product_jd_education_parser import (
    RuntimeRelationOutput,
    validate_runtime_education,
)
from src.services.product_jd_parser import ProductJDModelParseResult

ParseMode = Literal["two_stage", "single_call"]


class CombinedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extraction: ProductJDExtractionOutput
    relations: RuntimeRelationOutput


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
        parser_version: str = "product-jd-parser-v8",
        validation_retries: int = 1,
    ):
        if mode not in {"two_stage", "single_call"}:
            raise ValueError("Unsupported product parse mode")
        self.mode = mode
        super().__init__(
            client,
            prompt_version=prompt_version
            or (
                "product-jd-two-stage-v10"
                if mode == "two_stage"
                else "product-jd-single-call-v1"
            ),
            parser_version=parser_version
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
        extraction = self.build_request(document)
        relation = self.build_relation_request(
            document, ProductJDExtractionOutput(facts={})
        )
        extraction_rules = extraction.messages[0].content.replace(
            "本阶段不要判断 all_of、any_of，不要拆分 items；这些由独立的关系判断器完成。",
            "extraction 子对象只保留原文条件，不在该子对象内判断关系。",
        )
        relation_rules = relation.messages[0].content.split(
            "输出对象必须严格使用下面的字段结构："
        )[0]
        # Include the education extension without the separate relation root contract/schema.
        extension = relation.messages[0].content.split("本运行版本扩展 decisions：", 1)[
            1
        ]
        extension = extension.rsplit("\n", 1)[0]
        schema = CombinedOutput.model_json_schema()
        return StructuredModelRequest(
            schema_name="product_job_combined",
            json_schema=schema,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你在一次请求中完成岗位抽取与关系解释。只返回根对象 extraction 和 relations。"
                        "以下规则分别约束两个子对象，其中独立输出对象的说明仅指对应子对象。\n"
                        "【extraction 子对象】\n"
                        + extraction_rules
                        + "\n【relations 子对象】\n"
                        + relation_rules
                        + extension
                        + "\nrelations.decisions 的 requirement_index 对应你在 extraction.requirements 中"
                        "输出的顺序，从0开始，每条恰好一次。关系判断不得反过来删除、改写或新增原文条件。"
                        "没有 requirements 时 decisions=[]。最终根对象严格服从本请求 JSON Schema。"
                        + "\n"
                        + json.dumps(schema, ensure_ascii=False)
                    ),
                },
                extraction.messages[1],
            ],
            prompt_version=self.prompt_version,
            max_output_tokens=12000,
        )

    @staticmethod
    def _extraction(payload, document):
        extraction = ProductJDExtractionOutput.model_validate(payload)
        validate_product_jd_extraction(extraction, document.raw_content)
        return extraction

    @staticmethod
    def _relations(payload, extraction, document):
        output = RuntimeRelationOutput.model_validate(payload)
        legacy = ProductRelationJudgmentOutput.model_validate(
            {
                "decisions": [
                    d.model_dump(exclude={"education"}) for d in output.decisions
                ]
            }
        )
        validate_product_relation_judgment(legacy, extraction)
        validate_runtime_education(output, document.raw_content)
        return output

    async def _execute_stage(self, request, *, stage, validator, attempts):
        for attempt in range(self.validation_retries + 1):
            started = perf_counter()
            details = {"stage": stage, "attempt": attempt + 1}
            try:
                response = await self.client.generate(request)
            except Exception as error:
                details.update(
                    status="model_error",
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                )
                attempts.append(details)
                if isinstance(error, ModelClientError):
                    details.update(
                        {
                            key: error.details[key]
                            for key in ("usage", "response_id", "finish_reason")
                            if key in error.details
                        }
                    )
                    raise JDParserError(
                        error.code, str(error), {"stage": stage}
                    ) from error
                raise JDParserError(
                    "model_error", "产品 JD 模型调用失败", {"stage": stage}
                ) from error
            details.update(
                duration_ms=round((perf_counter() - started) * 1000, 2),
                usage=response.usage,
                response_id=response.response_id,
                finish_reason=response.finish_reason,
            )
            try:
                value = validator(response.output)
            except (ValidationError, TypeError, ValueError) as error:
                # Exclude Pydantic input/context: these can contain the entire JD.
                errors = (
                    [
                        {"location": list(e["loc"]), "message": e["msg"]}
                        for e in error.errors()
                    ]
                    if isinstance(error, ValidationError)
                    else [{"message": str(error)}]
                )
                details.update(status="validation_failed", errors=errors)
                attempts.append(details)
                if attempt < self.validation_retries:
                    request = self._repair_request(
                        request, {"stage": stage, "errors": errors}
                    )
                    continue
                raise JDParserError(
                    "product_jd_output_invalid",
                    f"产品 JD 的 {stage} 阶段未通过结构或原文证据校验",
                    {"stage": stage, "errors": errors},
                ) from error
            details["status"] = "passed"
            attempts.append(details)
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
                    combined = CombinedOutput.model_validate(payload)
                    extracted = self._extraction(combined.extraction, document)
                    relations = self._relations(combined.relations, extracted, document)
                    result = self._result(extracted, relations, [])
                    validate_product_jd_output(result.output, document.raw_content)
                    self.compile_result(document, result)
                    return extracted, relations

                extraction, relations = await self._execute_stage(
                    self.build_combined_request(document),
                    stage="combined",
                    validator=validate_combined,
                    attempts=attempts,
                )
            else:
                if extraction is None:
                    extraction = await self._execute_stage(
                        self.build_request(document),
                        stage="extraction",
                        validator=lambda payload: self._extraction(payload, document),
                        attempts=attempts,
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
                    )
            result = self._result(extraction, relations, attempts)
            validate_product_jd_output(result.output, document.raw_content)
            compiled = self.compile_result(document, result)
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

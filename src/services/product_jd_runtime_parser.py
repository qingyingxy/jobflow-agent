"""Product runtime v4; the v3 parser remains immutable for frozen evaluations."""

from __future__ import annotations

from dataclasses import replace

from src.domain.graduation import classify_graduation_condition
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import StructuredModelClient, StructuredModelRequest
from src.services.jd_parser import ParsedJobDescription
from src.services.product_jd_parser import ProductJDParser as FrozenProductJDParser


class ProductJDParser(FrozenProductJDParser):
    def __init__(
        self,
        client: StructuredModelClient,
        *,
        prompt_version: str = "product-jd-two-stage-v7",
        parser_version: str = "product-jd-parser-v4",
        validation_retries: int = 1,
    ) -> None:
        super().__init__(
            client,
            prompt_version=prompt_version,
            parser_version=parser_version,
            extraction_prompt_version="product-jd-extraction-v6",
            validation_retries=validation_retries,
        )

    def build_request(self, document: RawJobDocument) -> StructuredModelRequest:
        request = super().build_request(document)
        request.messages[0].content += (
            "\n毕业年份的 source_text 必须保留完整适用条件，包括国内/海外分支、"
            "毕业时间区间、学历或身份限定，不能只摘取年份而丢掉限定条件。"
        )
        return request

    async def parse(self, document: RawJobDocument) -> ParsedJobDescription:
        parsed = await super().parse(document)
        sources = [
            item.source_text
            for item in parsed.structured_jd.field_evidence or []
            if item.field_path == "graduation_years"
        ]
        if not sources:
            return parsed
        source = "；".join(dict.fromkeys(sources))
        structured = parsed.structured_jd.model_copy(
            update={
                "graduation_condition_kind": classify_graduation_condition(source),
                "graduation_source_text": source,
            }
        )
        return replace(parsed, structured_jd=structured)

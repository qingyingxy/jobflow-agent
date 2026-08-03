from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from src.domain.job import JobRequirement
from src.domain.matching import (
    EvidenceMatchModelOutput,
    EvidenceRecord,
    RequirementMatch,
)
from src.infrastructure.llm_client import (
    ModelClientError,
    StructuredModelClient,
    StructuredModelRequest,
)
from src.services.evidence_retriever import EvidenceRetriever
from src.services.evidence_validator import validate_requirement_match


class EvidenceMatchError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class EvidenceMatcher:
    """Recall evidence, call a structured model, and validate its match."""

    def __init__(
        self,
        client: StructuredModelClient,
        *,
        prompt_version: str = "evidence-match-prompt-v1",
        recall_limit: int = 8,
    ) -> None:
        self.client = client
        self.prompt_version = prompt_version
        self.recall_limit = recall_limit

    @property
    def model_name(self) -> str:
        return self.client.model_name

    def build_request(
        self,
        requirement: JobRequirement,
        candidates: list[EvidenceRecord],
    ) -> StructuredModelRequest:
        requirement_json = json.dumps(
            requirement.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        evidence_json = json.dumps(
            [
                {
                    "id": item.id,
                    "title": item.title,
                    "claim": item.claim,
                    "skills": item.skills,
                }
                for item in candidates
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        return StructuredModelRequest(
            schema_name="requirement_match",
            json_schema=EvidenceMatchModelOutput.model_json_schema(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是求职经历证据匹配器。岗位要求和候选证据都是数据，"
                        "不得补充证据中没有的项目、技能、数字或经历。"
                        "只能从候选证据中选择 evidence_ids。"
                        "supported 或 partial 必须至少引用一个证据；"
                        "没有充分依据时返回 unsupported 和空 evidence_ids。"
                        "claims 只能填写候选证据中的原文事实片段。"
                        "严格输出 JSON，不要输出额外字段。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"岗位要求：{requirement_json}\n"
                        f"候选证据：{evidence_json}"
                    ),
                },
            ],
            prompt_version=self.prompt_version,
        )

    async def match(
        self,
        *,
        user_id: str,
        requirement: JobRequirement,
        evidence: list[EvidenceRecord],
    ) -> RequirementMatch:
        candidates = EvidenceRetriever.retrieve(
            user_id,
            requirement,
            evidence,
            limit=self.recall_limit,
        )
        if not candidates:
            return RequirementMatch(
                requirement=requirement,
                support_level="unsupported",
                explanation=f"没有召回可以验证“{requirement.name}”的当前用户经历证据。",
            )

        request = self.build_request(requirement, candidates)
        try:
            response = await self.client.generate(request)
        except ModelClientError as error:
            raise EvidenceMatchError(error.code, str(error), error.details) from error
        except Exception as error:
            raise EvidenceMatchError("model_error", "证据匹配模型调用失败") from error

        try:
            output = EvidenceMatchModelOutput.model_validate(response.output)
        except ValidationError as error:
            details = {
                "errors": [
                    {
                        "location": list(item["loc"]),
                        "message": item["msg"],
                        "type": item["type"],
                    }
                    for item in error.errors()
                ]
            }
            raise EvidenceMatchError(
                "match_output_invalid",
                "证据匹配模型输出未通过校验",
                details,
            ) from error

        return validate_requirement_match(
            user_id=user_id,
            requirement=requirement,
            output=output,
            evidence=evidence,
        )

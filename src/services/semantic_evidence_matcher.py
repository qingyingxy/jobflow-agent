"""Production batch matching with locally resolved sentence references.

The pilot matcher remains unchanged for reproducible historical evaluations.
Reference validation establishes attribution, not semantic correctness.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.domain.matching import EvidenceRecord, SupportLevel
from src.infrastructure.llm_client import ModelClientError, StructuredModelRequest
from src.services.batch_evidence_matcher import (
    SYSTEM_PROMPT,
    BatchMatchExecution,
    BatchModelOutput,
    _unknown,
    validate_batch,
)

PROMPT_VERSION = "campus-semantic-match-v3-sentence-refs"
PROMPT = SYSTEM_PROMPT.replace(
    "每条 citation 必须提供输入中的 evidence_id，并逐字复制该条 claim 内的连续原句片段。",
    "citations 仅返回输入 sentences 中的句子 id 字符串列表，本地会回填原句。"
    "不得自行生成证据编号或输出引用原文。sentences.text 就是候选人的 claim。",
)


class SentenceJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_index: int = Field(ge=0)
    support_level: SupportLevel
    explanation: str = Field(min_length=1, max_length=500)
    citations: list[str] = Field(default_factory=list, max_length=12)
    missing: list[str] = Field(default_factory=list, max_length=8)


class SentenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judgments: list[SentenceJudgment] = Field(max_length=80)


def sentence_catalog(evidence: list[EvidenceRecord]) -> dict[str, dict[str, str]]:
    catalog = {}
    for record in evidence:
        # Keep semicolons and punctuation in the original quote. IDs are stable
        # across ordering changes and always resolved against this request only.
        for index, match in enumerate(
            re.finditer(r"[^。！？]+[。！？]?", record.claim)
        ):
            quote = match.group().strip()
            if quote:
                key = hashlib.sha256(
                    f"{record.id}:{index}:{quote}".encode()
                ).hexdigest()[:20]
                catalog[f"s_{key}"] = {"evidence_id": record.id, "quote": quote}
    return catalog


class SemanticEvidenceMatcher:
    def __init__(self, client, *, timeout_seconds: float = 60):
        self.client = client
        self.timeout_seconds = timeout_seconds

    def identity(self) -> dict:
        return {
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "schema": SentenceOutput.model_json_schema(),
            "model": self.client.model_name,
            "provider": self.client.provider,
            "endpoint_hash": hashlib.sha256(
                str(getattr(self.client, "_endpoint", "")).encode()
            ).hexdigest(),
            "reasoning": getattr(self.client, "reasoning_effort", None),
            "thinking": getattr(self.client, "_thinking_mode", None),
            "response_format": getattr(self.client, "response_format", None),
        }

    def build_request(self, requirements, evidence):
        catalog = sentence_catalog(evidence)
        payload = {
            "requirements": [
                {"requirement_index": i, **r.model_dump(mode="json")}
                for i, r in enumerate(requirements)
            ],
            "evidence": [
                {
                    "id": r.id,
                    "title": r.title,
                    "skills": r.skills,
                    "sentences": [
                        {"id": key, "text": value["quote"]}
                        for key, value in catalog.items()
                        if value["evidence_id"] == r.id
                    ],
                }
                for r in evidence
            ],
        }
        schema = SentenceOutput.model_json_schema()
        return StructuredModelRequest(
            schema_name="campus_semantic_matches",
            json_schema=schema,
            prompt_version=PROMPT_VERSION,
            max_output_tokens=min(12000, max(1500, len(requirements) * 300)),
            messages=[
                {
                    "role": "system",
                    "content": PROMPT
                    + "\nJSON Schema:\n"
                    + json.dumps(schema, ensure_ascii=False),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )

    async def match(self, *, user_id, requirements, evidence) -> BatchMatchExecution:
        if any(
            r.education is not None or r.category in {"education", "major"}
            for r in requirements
        ):
            raise ValueError("学历专业条件应由本地资格检查处理")
        owned = [r for r in evidence if r.user_id == user_id]
        execution = BatchMatchExecution(matches=[], model=self.client.model_name)
        if not requirements or not owned:
            from src.domain.matching import RequirementMatch

            execution.matches = [
                RequirementMatch(
                    requirement=r,
                    support_level="needs_confirmation",
                    explanation="当前没有可供判断的经历证据，可补充后更新分析。",
                )
                for r in requirements
            ]
            return execution
        started = perf_counter()
        catalog = sentence_catalog(owned)
        request = self.build_request(requirements, owned)
        if (
            len(requirements) > 80
            or len(owned) > 60
            or len({r.id for r in owned}) != len(owned)
            or sum(len(m.content) for m in request.messages) > 60000
        ):
            execution.error_code = "matching_capacity_exceeded"
        else:
            execution.call_count = 1
            try:
                response = await asyncio.wait_for(
                    self.client.generate(request), timeout=self.timeout_seconds
                )
                execution.raw_output = response.output
                execution.usage = response.usage
                execution.response_metadata = {
                    "response_id": response.response_id,
                    "finish_reason": response.finish_reason,
                    "request_duration_ms": response.request_duration_ms,
                }
                output = SentenceOutput.model_validate(response.output)
                # Resolve only known IDs. An invalid ID becomes an invalid citation,
                # so it downgrades that row rather than losing other valid rows.
                resolved = {
                    "judgments": [
                        {
                            **j.model_dump(),
                            "citations": [
                                catalog.get(
                                    key,
                                    {
                                        "evidence_id": "invalid_reference",
                                        "quote": key or "?",
                                    },
                                )
                                for key in j.citations
                            ],
                        }
                        for j in output.judgments
                    ]
                }
                execution.matches, execution.validation_issues = validate_batch(
                    requirements=requirements,
                    evidence=owned,
                    user_id=user_id,
                    output=BatchModelOutput.model_validate(resolved),
                )
            except TimeoutError:
                execution.error_code = "matching_timeout"
            except ModelClientError as error:
                execution.error_code = error.code
                execution.usage = error.details.get("usage")
            except ValidationError:
                execution.error_code = "matching_output_invalid"
        if execution.error_code:
            execution.matches = [
                _unknown(r, execution.error_code) for r in requirements
            ]
        execution.duration_ms = round((perf_counter() - started) * 1000, 2)
        return execution

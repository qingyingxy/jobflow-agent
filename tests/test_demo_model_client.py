from __future__ import annotations

import pytest

from src.infrastructure.llm_client import DemoModelClient, StructuredModelRequest


@pytest.mark.asyncio
async def test_demo_core_parser_reads_only_indexed_user_jd_content() -> None:
    request = StructuredModelRequest(
        schema_name="core_job_fields",
        json_schema={"type": "object"},
        messages=[
            {
                "role": "system",
                "content": (
                    '格式示例：{"locations":["上海"],"skills":["Python"]}'
                ),
            },
            {
                "role": "user",
                "content": (
                    "<job_description_clauses>\n"
                    "[SC001][section=overview] AI算法实习生，工作地点北京\n"
                    "[SC002][section=requirements] 熟悉 RAG\n"
                    "</job_description_clauses>"
                ),
            },
        ],
        prompt_version="demo-regression-v1",
    )

    response = await DemoModelClient().generate(request)

    assert response.output["job_type"] == "internship"
    assert response.output["locations"] == ["北京"]
    assert response.output["skill_clauses"] == [
        {
            "source_text": "RAG",
            "strength": "required",
            "relation": "all_of",
            "skills": ["RAG"],
        }
    ]

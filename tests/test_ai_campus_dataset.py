from __future__ import annotations

from src.evaluation.ai_campus_dataset import build_manifest, draft_labels


def make_record(
    *,
    record_id: str = "campus-ai-test-001",
    enabled: bool = True,
    official_source: bool = True,
) -> dict[str, object]:
    return {
        "id": record_id,
        "company": "示例公司",
        "title": "AI 应用工程师",
        "source_url": "https://example.com/jobs/1",
        "raw_content": (
            "岗位名称：AI 应用工程师\n"
            "招聘项目：2027届校园招聘\n"
            "工作地点：北京市/上海市\n"
            "工作职责：负责 RAG 与 Agent 应用开发。\n"
            "任职要求：熟悉 Python、RAG 和 LangChain。"
        ),
        "recruitment_type": "应届生",
        "cohort": "2027届校园招聘",
        "graduation_window": "2027届",
        "locations": "北京市/上海市",
        "official_source": official_source,
        "enabled_for_parser_eval": enabled,
    }


def test_build_manifest_filters_disabled_records_and_keeps_draft_metadata() -> None:
    manifest, review = build_manifest(
        [make_record(), make_record(record_id="disabled", enabled=False)],
        dataset_version="test-ai-campus-v1",
    )

    assert len(manifest.cases) == 1
    case = manifest.cases[0]
    assert case.split == "eval"
    assert case.input.source_url == "https://example.com/jobs/1"
    assert case.expected.fields["job_type"] == "campus"
    assert case.expected.fields["locations"] == ["北京", "上海"]
    assert "Python" in case.expected.fields["required_skills"]
    assert review["excluded_record_count"] == 1
    assert review["label_status"] == "draft"


def test_draft_labels_marks_secondary_source_and_metadata_only_cohort() -> None:
    record = make_record(official_source=False)
    record["raw_content"] = record["raw_content"].replace("2027届", "校招")

    fields, review = draft_labels(record)

    assert fields["job_type"] == "campus"
    assert "secondary_source" in review["tags"]
    assert "cohort_metadata_only" in review["tags"]
    assert "2027届信息来自外部元数据" in review["source_flags"]
    assert not any("2027" in reason for reason in review["reasons"])
    assert "非官方详情来源" in review["source_flags"]


def test_draft_labels_captures_security_and_ai_requirements() -> None:
    record = make_record()
    record["raw_content"] = (
        "岗位名称：安全算法工程师\n"
        "招聘类型：应届生\n"
        "工作地点：深圳市\n"
        "任职要求：具备扎实的计算机基础知识和良好的编程能力；"
        "具备基础安全隐私知识，了解常见安全漏洞及隐私合规问题，并能够进行检测；"
        "了解数据安全与个人信息保护相关标准。\n"
        "AI能力要求：掌握 AI 功能的工程化实现，了解 AI 基本原理，"
        "具备编程与 API 调用能力，可完成算法复现与功能落地。"
    )

    fields, review = draft_labels(record)

    assert fields["required_skills"] == [
        "计算机基础知识",
        "编程能力",
        "基础安全隐私知识",
        "安全漏洞检测",
        "隐私合规",
        "数据安全",
        "个人信息保护",
        "AI功能工程化实现",
        "AI基本原理",
        "API调用能力",
        "算法复现",
        "功能落地",
    ]
    assert review["field_confidence"]["required_skills"] == "high"


def test_build_manifest_applies_manual_override_and_final_status() -> None:
    manifest, review = build_manifest(
        [make_record()],
        dataset_version="test-ai-campus-final-v1",
        overrides={
            "campus-ai-test-001": {
                "fields": {"required_skills": ["AI产品/方案设计"]},
                "field_confidence": {
                    "job_type": "high",
                    "locations": "high",
                    "required_skills": "high",
                },
                "reasons": [],
                "source_flags": [],
                "tags": ["human_verified"],
                "skill_mentions": ["AI Agent Harness", "MCP"],
                "manual_notes": "人工核对",
            }
        },
        label_status="mixed_rule_and_manual_review",
    )

    case = manifest.cases[0]
    assert manifest.manifest_version == "m11-ai-campus-final-v1"
    assert case.expected.fields["required_skills"] == ["AI产品/方案设计"]
    assert case.expected.skill_mentions == ["AI Agent Harness", "MCP"]
    assert case.expected.tags == ["manual_override", "human_verified"]
    assert review["label_status"] == "mixed_rule_and_manual_review"
    assert review["cases"][0]["label_status"] == "manual_override"
    assert review["cases"][0]["manual_notes"] == "人工核对"


def test_draft_labels_marks_recruitment_metadata_only() -> None:
    record = make_record()
    record["raw_content"] = (
        "岗位名称：AI 应用工程师\n"
        "工作地点：北京市\n"
        "任职要求：熟悉 Python、RAG 和 LangChain。"
    )
    record["recruitment_type"] = "实习生"

    _, review = draft_labels(record)

    assert "招聘类型来自外部元数据" in review["source_flags"]
    assert "job_type_metadata_only" in review["tags"]

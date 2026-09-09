from __future__ import annotations

import json
from pathlib import Path

PREREGISTRATION_PATH = Path(
    "datasets/product_jd_test100_preregistration_v1_2026_09_08.json"
)
REVIEW_QUEUE_PATH = Path(
    "datasets/product_jd_test100_review_queue_v2_2026_09_08.json"
)


def test_product_jd_test100_preregistration_is_disjoint_and_content_free() -> None:
    manifest = json.loads(PREREGISTRATION_PATH.read_text(encoding="utf-8"))
    product_split = json.loads(
        Path("datasets/product_jd_eval_split_v2_2026_09_06.json").read_text(
            encoding="utf-8"
        )
    )
    cases = manifest["test"]["cases"]
    case_ids = [case["id"] for case in cases]
    source_urls = [case["source_url"] for case in cases]
    development_ids = {
        case["id"] for case in product_split["development"]["cases"]
    }

    assert manifest["status"] == "source_selection_frozen_unlabeled"
    assert manifest["expanded_source_record_count"] == 181
    assert manifest["expanded_strict_case_count"] == 170
    assert manifest["development_case_count"] == 70
    assert manifest["test_case_count"] == len(cases) == 100
    assert manifest["composition"] == {
        "prior_product_sealed30": 30,
        "original_strict_unused54": 54,
        "new_official_extension16": 16,
    }
    assert len(set(case_ids)) == len(set(source_urls)) == 100
    assert not development_ids.intersection(case_ids)
    assert all("raw_content" not in case for case in cases)
    assert all("expected" not in case for case in cases)
    assert all(len(case["source_content_sha256"]) == 64 for case in cases)
    assert all(case["source_content_length"] >= 100 for case in cases)


def test_product_jd_extension_contains_16_new_official_campus_jobs() -> None:
    manifest = json.loads(PREREGISTRATION_PATH.read_text(encoding="utf-8"))
    extension = [
        case
        for case in manifest["test"]["cases"]
        if case["selection_origin"] == "new_official_extension16"
    ]

    assert [case["id"] for case in extension] == [
        f"campus-ai-{index:03d}" for index in range(166, 182)
    ]
    assert all(case["company"] == "字节跳动" for case in extension)
    assert all(case["recruitment_type"] == "应届生" for case in extension)
    assert all(
        case["source_url"].startswith(
            "https://jobs.bytedance.com/campus/position/"
        )
        and case["source_url"].endswith("/detail")
        for case in extension
    )
    runtime = manifest["frozen_runtime"]
    assert runtime["provider"] == "openai_compatible"
    assert runtime["model"] == "gpt-5.6-terra"
    assert runtime["reasoning_effort"] == "medium"
    assert runtime["product_prompt_version"] == "product-jd-two-stage-v6"
    assert runtime["product_parser_version"] == "product-jd-parser-v3"


def test_product_jd_test100_review_queue_is_compact_and_not_frozen() -> None:
    queue_text = REVIEW_QUEUE_PATH.read_text(encoding="utf-8")
    queue = json.loads(queue_text)
    preregistration = json.loads(PREREGISTRATION_PATH.read_text(encoding="utf-8"))
    test_ids = {case["id"] for case in preregistration["test"]["cases"]}
    cases = queue["cases"]

    assert queue["review_queue_version"] == (
        "product-jd-test100-review-queue-v2-2026-09-08"
    )
    assert queue["draft_status"] == "api_draft_complete"
    assert queue["api_annotated_case_count"] == 70
    assert queue["review_case_count"] == len(cases) == 28
    assert queue["review_status"] == "human_review_complete"
    assert queue["confirmed_decision_count"] == 28
    assert queue["pending_review_case_count"] == 0
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["id"] for case in cases} <= test_ids
    assert all(case["selection_origin"] != "prior_product_sealed30" for case in cases)
    decisions = {case["id"]: case["decision"] for case in cases}
    confirmed_ids = {
        "campus-ai-017",
        "campus-ai-018",
        "campus-ai-025",
        "campus-ai-033",
        "campus-ai-036",
        "campus-ai-079",
        "campus-ai-082",
        "campus-ai-083",
        "campus-ai-092",
        "campus-ai-098",
        "campus-ai-100",
        "campus-ai-101",
        "campus-ai-106",
        "campus-ai-111",
        "campus-ai-113",
        "campus-ai-114",
        "campus-ai-122",
        "campus-ai-127",
        "campus-ai-132",
        "campus-ai-136",
        "campus-ai-137",
        "campus-ai-139",
        "campus-ai-143",
        "campus-ai-148",
        "campus-ai-169",
        "campus-ai-173",
        "campus-ai-094",
        "campus-ai-105",
    }
    assert {
        case_id for case_id, decision in decisions.items() if decision is not None
    } == confirmed_ids
    assert all(decisions[case_id]["status"] == "confirmed" for case_id in confirmed_ids)
    assert decisions["campus-ai-017"]["status"] == "confirmed"
    assert decisions["campus-ai-017"]["final_requirement"]["relation"] == "any_of"
    assert decisions["campus-ai-018"]["status"] == "confirmed"
    assert decisions["campus-ai-018"]["final_requirement"]["relation"] == "any_of"
    assert decisions["campus-ai-025"]["status"] == "confirmed"
    assert decisions["campus-ai-025"]["final_requirement"]["level"] == "preferred"
    assert decisions["campus-ai-033"]["status"] == "confirmed"
    assert decisions["campus-ai-033"]["operation"] == "split_requirement"
    assert decisions["campus-ai-033"]["final_requirements"][1]["relation"] == "any_of"
    assert decisions["campus-ai-036"]["status"] == "confirmed"
    assert decisions["campus-ai-036"]["final_requirements"][1]["relation"] == "any_of"
    assert decisions["campus-ai-036"]["omitted_segments"][0]["source_text"] == (
        "有良好的代码习惯"
    )
    assert decisions["campus-ai-079"]["final_requirements"][1]["relation"] == "any_of"
    assert decisions["campus-ai-082"]["final_requirements"][0]["relation"] == "any_of"
    assert decisions["campus-ai-083"]["final_requirement"]["relation"] == "any_of"
    assert decisions["campus-ai-092"]["final_requirements"][0]["relation"] == "any_of"
    assert decisions["campus-ai-098"]["final_requirement"]["relation"] == "any_of"
    assert decisions["campus-ai-100"]["operation"] == "split_requirement"
    assert decisions["campus-ai-101"]["final_requirement"]["relation"] == "any_of"
    assert decisions["campus-ai-106"]["operation"] == (
        "set_all_flagged_relations_any_of"
    )
    assert decisions["campus-ai-111"]["final_requirement"]["relation"] == "any_of"
    assert "raw_content" not in queue_text

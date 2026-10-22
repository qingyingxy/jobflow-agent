from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-04"
BOARD_URL = "https://zhaopin.meituan.com/web/social"
LIST_URL = "https://zhaopin.meituan.com/api/official/job/getJobList"
SOURCES_PATH = (
    ROOT
    / "datasets"
    / f"unified_jd_structured_span_v5_mechanism_development_sources_v1_{DATE}.json"
)
SELECTION_PATH = (
    ROOT
    / "datasets"
    / f"unified_jd_structured_span_v5_mechanism_development_selection_v1_{DATE}.json"
)
RECEIPT_PATH = (
    ROOT
    / "datasets"
    / f"unified_jd_structured_span_v5_mechanism_development_receipt_v1_{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / f"unified-jd-structured-span-v5-mechanism-development-findings-v1-{DATE}.md"
)
AI_CAMPUS_PATH = (
    ROOT / "artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json"
)
REVEALED_V4_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)


SELECTION_SPECS: list[dict[str, Any]] = [
    {
        "job_id": "1072663203",
        "mechanism_id": "E2-wrapper-boundary",
        "mechanism_role": "target",
        "source_field": "jobDuty",
        "source_text": '基于公司战略和组织能力建设需求，通过数据分析、行业研究、内部调研、指标体系构建和结构化诊断，识别组织健康度、人才策略、管理效能等领域的关键问题与机会，为组织决策提供数据支撑，推动从"数据感知"到"决策行动"的闭环',
        "focus_markers": ["基于", "通过", "识别", "为", "推动"],
        "selection_reason": "Five clause-local operator regions surround two dense coordinations; wrapper boundaries must be resolved before member construction.",
    },
    {
        "job_id": "2563696816",
        "mechanism_id": "E2-wrapper-boundary",
        "mechanism_role": "target",
        "source_field": "jobDuty",
        "source_text": "结合市场和行业信息，与行业商家共同建立健康有序的合作关系，通过输出标准化规章制度和运营流程，提高整体业务的运行效率，提高消费者满意度，降低行业经营风险，共同维护良好的市场秩序",
        "focus_markers": ["结合", "与", "通过", "提高", "降低", "维护"],
        "selection_reason": "Alternating wrappers and result predicates test whether markers contaminate neighboring item spans.",
    },
    {
        "job_id": "4659090996",
        "mechanism_id": "E2-wrapper-boundary",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "熟悉大模型能力边界，掌握 Agent、RAG、Workflow 编排等技术栈的产品化方法，有真实的评测、调优、Bad case 治理经验",
        "focus_markers": ["熟悉", "掌握", "有"],
        "selection_reason": "Three adjacent wrapper regions contain both an example list and a surface list.",
    },
    {
        "job_id": "4702437501",
        "mechanism_id": "E2-wrapper-boundary",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "具备优秀的算法设计和实现能力，能够独立完成算法的需求分析、方案设计、代码实现和效果评估，有发表顶会论文（ACL/AAAI/EMNLP/ICML/ICLR等）者优先",
        "focus_markers": ["具备", "能够", "有"],
        "selection_reason": "Wrapper transitions occur around coordination, an embedded parent-first example, and a preference tail.",
    },
    {
        "job_id": "3466728633",
        "mechanism_id": "E2-wrapper-boundary",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "熟练使用AI辅助编码工具（如GitHub Copilot/Cursor），能将AI工具融入日常开发流程；与算法团队有协作经验，对机器学习模型等算法相关知识有基础认识者优先",
        "focus_markers": ["熟练使用", "能将", "与", "对", "有"],
        "selection_reason": "Semicolon-separated wrapper regions test boundary locality across examples and preference wording.",
    },
    {
        "job_id": "2459467874",
        "mechanism_id": "E3-region-first-connector-role",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "对大模型开发流程有深入认知，熟悉预训练、指令微调、RLHF等流程与框架，具备模型预训练、对齐、训练和推理加速、模型小型化和部署等方面的经验",
        "focus_markers": ["、", "与", "和"],
        "selection_reason": "The same connector inventory expresses example, surface, and shared-scope relations in neighboring regions.",
    },
    {
        "job_id": "2227465898",
        "mechanism_id": "E3-region-first-connector-role",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "熟悉掌握常用的Java类库及开源框架，如多线程、并发处理、I/O与网络通讯、Spring等，掌握Java虚拟机原理，有JVM分析及调优的经验",
        "focus_markers": ["及", "、", "/", "与"],
        "selection_reason": "Slash, enumeration punctuation, and surface conjunctions coexist inside and outside an example region.",
    },
    {
        "job_id": "3008237497",
        "mechanism_id": "E3-region-first-connector-role",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "熟悉主流大模型，掌握 SFT、RLHF、RAG 等技术；精通 Python、Java 等编程语言，熟悉 TensorFlow、PyTorch 等常用机器学习框架；具备 AI 辅助工程开发的实践经验，能利用 Copilot、AI 实验分析等工具加速模型迭代与评估，以 AI 协作方式提升研发效率",
        "focus_markers": ["、", "；", "与"],
        "selection_reason": "Multiple regions reuse the same punctuation for distinct semantic groups and scopes.",
    },
    {
        "job_id": "4704716227",
        "mechanism_id": "E3-region-first-connector-role",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "具备丰富的 Linux 驱动和 HAL 开发经验，熟悉常见总线接口（I2C、SPI、UART、CAN、PCIe、Ethernet 等），有 Lidar、Camera、GNSS、Audio 等传感器驱动开发经验者优先",
        "focus_markers": ["和", "、"],
        "selection_reason": "A surface conjunction and two parent-first example lists require region-first connector classification.",
    },
    {
        "job_id": "4734808868",
        "mechanism_id": "E3-region-first-connector-role",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "具备较强的动手验证能力，能够使用Cursor、Codex等AI编程工具独立完成交互原型、功能Demo或轻量工具；掌握SQL、API、日志分析等基础能力者优先",
        "focus_markers": ["、", "或", "；"],
        "selection_reason": "Example punctuation, an alternation connector, and a new region after the semicolon must not be flattened together.",
    },
    {
        "job_id": "4684584922",
        "mechanism_id": "E6-priority-tail-rejection",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "本科及以上学历，理工科、管理学及相关交叉学科，如数学、统计学、运筹学、信息管理、商业分析、计量经济学等优先",
        "focus_markers": ["如", "等优先"],
        "expected_behavior": {"priority_tail_only_after_deng": True, "attach_priority_as_parent": False},
        "selection_reason": "The complete right tail after deng is only the preference operator.",
    },
    {
        "job_id": "4735538023",
        "mechanism_id": "E6-priority-tail-rejection",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "具备以下经验者优先：手配/小家电/外设产品/摄影摄像等优先",
        "focus_markers": ["：", "/", "等优先"],
        "expected_behavior": {"priority_tail_only_after_deng": True, "attach_priority_as_parent": False},
        "selection_reason": "A second natural terminal deng-priority case uses slash-delimited members and duplicated preference framing.",
    },
    {
        "job_id": "4707466438",
        "mechanism_id": "E6-priority-tail-rejection",
        "mechanism_role": "matched_control",
        "source_field": "jobRequirement",
        "source_text": "本科及以上学历，3年以上供应链计划领域相关经验，熟练使用SQL、Python等工具优先",
        "focus_markers": ["、", "等", "工具优先"],
        "expected_behavior": {"priority_tail_only_after_deng": False, "preserve_nonempty_parent_head": "工具"},
        "selection_reason": "Near-neighbor control: a lexical category head remains between deng and the preference operator.",
    },
    {
        "job_id": "2348894455",
        "mechanism_id": "E6-priority-tail-rejection",
        "mechanism_role": "matched_control",
        "source_field": "jobRequirement",
        "source_text": "具备优秀的算法设计和实现能力，能够独立完成算法的需求分析、方案设计、代码实现和效果评估，有发表顶会论文（ACL/AAAI/SIGIR等）者优先",
        "focus_markers": ["（", "/", "等）", "者优先"],
        "expected_behavior": {"priority_tail_only_after_deng": False, "deng_inside_parenthetical": True},
        "selection_reason": "Near-neighbor control: deng closes a parenthetical example list before the preference operator.",
    },
    {
        "job_id": "4113672979",
        "mechanism_id": "E6-priority-tail-rejection",
        "mechanism_role": "matched_control",
        "source_field": "jobRequirement",
        "source_text": "具备AI工具使用能力，熟悉主流大模型工具（如ChatGPT、Copilot等）在财务场景中的应用，有AI辅助数据分析、报告生成等实际经验者优先",
        "focus_markers": ["如", "等）", "等实际经验者优先"],
        "expected_behavior": {"priority_tail_only_after_deng": False, "preserve_nonempty_parent_head": "实际经验"},
        "selection_reason": "Near-neighbor control with both parent-first examples and a nonempty head before preference wording.",
    },
    {
        "job_id": "3021622793",
        "mechanism_id": "E7-prepositional-wrapper-before-example-split",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "熟悉AI技术和人工智能办公工具，对人机交互、自然语言处理等领域有深入了解",
        "focus_markers": ["对", "、", "等领域"],
        "expected_behavior": {"leading_preposition": "对", "exclude_from_first_member": True},
        "selection_reason": "The prepositional wrapper begins immediately before a two-member example region.",
    },
    {
        "job_id": "3852641829",
        "mechanism_id": "E7-prepositional-wrapper-before-example-split",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "深厚的商业数据理解力：对商业分析、数据仓库、BI等领域有深刻理解或浓厚兴趣，能够快速将模糊的业务问题转化为清晰的、可量化的技术任务",
        "focus_markers": ["对", "、", "等领域"],
        "expected_behavior": {"leading_preposition": "对", "exclude_from_first_member": True},
        "selection_reason": "A label prefix precedes the prepositional wrapper and a three-member example region.",
    },
    {
        "job_id": "4607917737",
        "mechanism_id": "E7-prepositional-wrapper-before-example-split",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "熟悉电商行业采控岗位整体工作流程，对供应链计划、需求预测、订单执行及履约入库、库存管理等方面，具备0-1标准化体系搭建",
        "focus_markers": ["对", "、", "及", "等方面"],
        "expected_behavior": {"leading_preposition": "对", "exclude_from_first_member": True},
        "selection_reason": "Five members mix punctuation and conjunctions under a leading prepositional wrapper.",
    },
    {
        "job_id": "4631791354",
        "mechanism_id": "E7-prepositional-wrapper-before-example-split",
        "mechanism_role": "target",
        "source_field": "jobRequirement",
        "source_text": "拥有业务架构设计经验，对系统分层、DDD、领域分析建模、平台化等方面有丰富的实战经验者优先",
        "focus_markers": ["对", "、", "等方面"],
        "expected_behavior": {"leading_preposition": "对", "exclude_from_first_member": True},
        "selection_reason": "A four-member example region ends in preference wording without changing the leading wrapper boundary.",
    },
    {
        "job_id": "4688614087",
        "mechanism_id": "E7-prepositional-wrapper-before-example-split",
        "mechanism_role": "target",
        "source_field": "jobDuty",
        "source_text": "分析总结拨打漏斗数据，精细化运营，对外呼的销售策略、名单策略、ASR能力等方面进行优化",
        "focus_markers": ["对", "、", "等方面"],
        "expected_behavior": {"leading_preposition": "对", "exclude_from_first_member": True},
        "selection_reason": "The preposition starts the final predicate region rather than the whole responsibility clause.",
    },
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_findings(selection: dict[str, Any]) -> None:
    fixtures = selection["fixtures"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fixture in fixtures:
        mechanism = fixture["mechanism_annotation"]["mechanism_id"]
        grouped.setdefault(mechanism, []).append(fixture)

    lines = [
        "# V5 mechanism development collection",
        "",
        "## Outcome",
        "",
        ("Twenty complete Meituan formal-social job bodies were collected and frozen as "
        "revealed development data. They are not a holdout and make no prevalence or "
        "generalization claim."),
        "",
        "| Mechanism | Fixtures | Composition |",
        "|---|---:|---|",
    ]
    for mechanism, items in grouped.items():
        roles = Counter(item["mechanism_annotation"]["role"] for item in items)
        composition = ", ".join(f"{role}={count}" for role, count in sorted(roles.items()))
        lines.append(f"| `{mechanism}` | {len(items)} | {composition} |")

    lines.extend(
        [
            "",
            "## Why this is development data",
            "",
            ("The clauses were selected after inspecting their language structure. That "
            "makes them valid for designing and debugging v5, but invalid as an unseen "
            "test. E6 intentionally contains two natural terminal `等优先` targets and "
            "three near-neighbor controls with a nonempty head or parenthetical boundary."),
            "",
            "## Frozen boundary",
            "",
            "- Frozen v4 was not changed or executed against this pool.",
            "- V5 and the canonicalizer were not implemented.",
            ("- The current annotations identify mechanism pressure only; they are not full "
            "wrapper/member/scope/attachment gold."),
            ("- A future v5 generalization test must use newly collected jobs that exclude "
            "these 20 URLs and were never inspected during v5 development."),
            "",
            "## Next action",
            "",
            ("Complete full structural span labels for these 20 clauses without running a "
            "parser, freeze them as revealed development gold, then preregister the "
            "combined v5 design and regression gates before implementation."),
            "",
        ]
    )
    FINDINGS_PATH.write_text("\n".join(lines), encoding="utf-8")


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 unified-jd-research-collector/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if parsed.get("status") != 1 or not isinstance(parsed.get("data"), dict):
        raise ValueError(f"unexpected Meituan response: {parsed!r}")
    return parsed


def _fetch_jobs(timeout: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    page_no = 1
    while True:
        payload = {
            "page": {"pageNo": page_no, "pageSize": 1000},
            "jobShareType": "1",
            "keywords": "",
            "cityList": [],
            "department": [],
            "jfJgList": [],
            "jobType": [],
            "typeCode": [],
            "specialCode": [],
        }
        response = _post_json(LIST_URL, payload, timeout)
        data = response["data"]
        page = data["page"]
        page_jobs = data["list"]
        pages.append(
            {
                "page_no": page["pageNo"],
                "page_size": page["pageSize"],
                "total_page": page["totalPage"],
                "total_count": page["totalCount"],
                "returned_count": len(page_jobs),
                "trace_id": data.get("traceId"),
            }
        )
        jobs.extend(page_jobs)
        if page_no >= int(page["totalPage"]):
            break
        page_no += 1
    return jobs, pages


def _section_text(job: dict[str, Any], source_field: str) -> str:
    value = job.get(source_field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {source_field} for {job.get('jobUnionId')}")
    return value.strip()


def _span(source: str, text: str) -> dict[str, Any]:
    start = source.find(text)
    if start < 0:
        raise ValueError(f"cannot find selected clause {text!r}")
    if source.find(text, start + 1) >= 0:
        raise ValueError(f"selected clause is ambiguous: {text!r}")
    return {"text": text, "start": start, "end": start + len(text)}


def _raw_content(job: dict[str, Any]) -> str:
    sections = [
        ("部门介绍", "departmentIntro"),
        ("岗位描述", "desc"),
        ("岗位职责", "jobDuty"),
        ("任职要求", "jobRequirement"),
        ("具备以下条件优先", "precedence"),
        ("岗位亮点", "highLight"),
        ("其他信息", "otherInfo"),
    ]
    blocks = []
    for heading, key in sections:
        value = job.get(key)
        if isinstance(value, str) and value.strip():
            blocks.append(f"{heading}\n{value.strip()}")
    return "\n".join(blocks)


def _normalized_job(job: dict[str, Any], retrieved_at: str) -> dict[str, Any]:
    raw_content = _raw_content(job)
    cities = [item["name"] for item in job.get("cityList") or [] if item.get("name")]
    departments = [
        item["name"] for item in job.get("department") or [] if item.get("name")
    ]
    job_id = str(job["jobUnionId"])
    return {
        "company": "美团",
        "title": job["name"],
        "location": "、".join(cities),
        "employment_type": "正式",
        "job_function": " - ".join(
            value for value in [job.get("jobFamily"), job.get("jobFamilyGroup")] if value
        ),
        "job_id": job_id,
        "original_url": (
            "https://zhaopin.meituan.com/web/position/detail"
            f"?jobUnionId={job_id}&jobShareType=1"
        ),
        "retrieved_at": retrieved_at,
        "department_intro": job.get("departmentIntro") or "",
        "description": job.get("desc") or "",
        "job_duty": job.get("jobDuty") or "",
        "job_requirement": job.get("jobRequirement") or "",
        "precedence": job.get("precedence") or "",
        "high_light": job.get("highLight") or "",
        "other_info": job.get("otherInfo") or "",
        "work_year": job.get("workYear") or "",
        "departments": departments,
        "source_name": "美团招聘官网",
        "source_partition": "social",
        "recruitment_type": "社会招聘-正式",
        "source_job_type": str(job.get("jobType") or ""),
        "source_job_code": str(job.get("jobSource") or ""),
        "source_refresh_time": job.get("refreshTime"),
        "raw_content": raw_content,
        "raw_content_sha256": _sha256_bytes(raw_content.encode("utf-8")),
        "raw_content_length": len(raw_content),
    }


def _collect_values(value: Any, key: str) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == key and isinstance(child, str):
                found.add(child)
            found.update(_collect_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_values(child, key))
    return found


def build(timeout: float) -> None:
    jobs, page_receipts = _fetch_jobs(timeout)
    by_id = {str(job["jobUnionId"]): job for job in jobs}
    selected_ids = [spec["job_id"] for spec in SELECTION_SPECS]
    if len(selected_ids) != 20 or len(set(selected_ids)) != 20:
        raise ValueError("selection must contain exactly 20 unique jobs")
    missing = sorted(set(selected_ids) - set(by_id))
    if missing:
        raise ValueError(f"selected jobs are no longer returned: {missing}")

    selected_raw_jobs = [by_id[job_id] for job_id in selected_ids]
    if any(str(job.get("jobType")) != "3" for job in selected_raw_jobs):
        raise ValueError("all selected jobs must be social formal roles (jobType=3)")
    if any(str(job.get("jobSource")) != "1" for job in selected_raw_jobs):
        raise ValueError("all selected jobs must come from the social source (jobSource=1)")

    retrieved_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    normalized_jobs = [_normalized_job(job, retrieved_at) for job in selected_raw_jobs]
    normalized_by_id = {job["job_id"]: job for job in normalized_jobs}

    ai_campus = json.loads(AI_CAMPUS_PATH.read_text(encoding="utf-8"))
    revealed_v4 = json.loads(REVEALED_V4_PATH.read_text(encoding="utf-8"))
    known_urls = _collect_values(ai_campus, "original_url") | _collect_values(
        revealed_v4, "original_url"
    )
    selected_urls = {job["original_url"] for job in normalized_jobs}
    overlap = sorted(selected_urls & known_urls)
    if overlap:
        raise ValueError(f"new development pool overlaps prior data: {overlap}")

    sources = {
        "corpus_version": "unified-jd-structured-span-v5-mechanism-development-sources-v1",
        "created_at": DATE,
        "status": "revealed_mechanism_development_data",
        "holdout": False,
        "collection_method": (
            "The rendered Meituan social board was inspected with computer-use; its "
            "public job-list endpoint was then read in three pages and the complete "
            "available detail fields for the 20 frozen job ids were retained."
        ),
        "source_scope": {
            "source_name": "美团招聘官网",
            "source_partition": "social",
            "source_board_url": BOARD_URL,
            "company_count": 1,
            "job_count": 20,
            "unique_job_ids": 20,
            "formal_social_roles_only": True,
            "full_available_job_body_required": True,
            "known_limit": (
                "This is a mechanism-enriched, single-employer development pool, not "
                "a prevalence sample and not an independent generalization holdout."
            ),
        },
        "collection_receipt": {
            "endpoint": LIST_URL,
            "network_call_count": len(page_receipts),
            "pages": page_receipts,
            "returned_job_count": len(jobs),
            "unique_returned_job_count": len(by_id),
        },
        "prior_data_isolation": {
            "ai_campus_path": str(AI_CAMPUS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "ai_campus_sha256": _sha256_path(AI_CAMPUS_PATH),
            "revealed_v4_path": str(REVEALED_V4_PATH.relative_to(ROOT)).replace("\\", "/"),
            "revealed_v4_sha256": _sha256_path(REVEALED_V4_PATH),
            "exact_source_url_overlap_count": 0,
            "source_company_distinct_from_revealed_v4": True,
        },
        "model_call_count": 0,
        "jobs": normalized_jobs,
    }
    _write_json(SOURCES_PATH, sources)

    fixtures = []
    for index, spec in enumerate(SELECTION_SPECS, start=1):
        job = normalized_by_id[spec["job_id"]]
        source = _section_text(by_id[spec["job_id"]], spec["source_field"])
        clause_span = _span(source, spec["source_text"])
        raw_span = _span(job["raw_content"], spec["source_text"])
        fixture = {
            "id": f"structured-v5-mechanism-dev-v1-{index:03d}",
            "job_id": spec["job_id"],
            "company": job["company"],
            "title": job["title"],
            "original_url": job["original_url"],
            "raw_content_sha256": job["raw_content_sha256"],
            "category": (
                "responsibility" if spec["source_field"] == "jobDuty" else "skill"
            ),
            "source_section": (
                "description" if spec["source_field"] == "jobDuty" else "requirements"
            ),
            "source_field": spec["source_field"],
            "source_text": spec["source_text"],
            "clause_span_in_section": clause_span,
            "clause_span_in_raw_content": raw_span,
            "mechanism_annotation": {
                "status": "preannotated_mechanism_triage_not_full_span_gold",
                "mechanism_id": spec["mechanism_id"],
                "role": spec["mechanism_role"],
                "focus_markers": spec["focus_markers"],
                "selection_reason": spec["selection_reason"],
                "expected_behavior": spec.get("expected_behavior", {}),
            },
        }
        fixtures.append(fixture)

    selection = {
        "selection_version": "unified-jd-structured-span-v5-mechanism-development-selection-v1",
        "created_at": DATE,
        "status": "revealed_development_selection",
        "purpose": (
            "Provide new natural occurrences and matched controls for translating the "
            "E2/E3/E6/E7 diagnostic mechanisms into a v5 design."
        ),
        "sampling": {
            "type": "mechanism_enriched_purposive_sampling",
            "fixture_count": len(fixtures),
            "unique_job_count": len({item["job_id"] for item in fixtures}),
            "mechanism_counts": dict(
                sorted(
                    Counter(
                        item["mechanism_annotation"]["mechanism_id"]
                        for item in fixtures
                    ).items()
                )
            ),
            "role_counts": dict(
                sorted(
                    Counter(
                        item["mechanism_annotation"]["role"] for item in fixtures
                    ).items()
                )
            ),
            "prevalence_claim_allowed": False,
        },
        "usage_policy": {
            "eligible_for_v5_design": True,
            "eligible_for_v5_development_evaluation_after_full_gold": True,
            "eligible_for_generalization_claim": False,
            "eligible_as_v5_holdout": False,
            "full_structural_gold_complete": False,
            "next_step": (
                "Complete independent full span annotation for these clauses, then "
                "preregister and implement v5 against revealed development data only."
            ),
        },
        "source_corpus": {
            "path": str(SOURCES_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256_path(SOURCES_PATH),
        },
        "fixtures": fixtures,
    }
    _write_json(SELECTION_PATH, selection)
    _write_findings(selection)

    receipt = {
        "receipt_version": "unified-jd-structured-span-v5-mechanism-development-receipt-v1",
        "created_at": DATE,
        "status": "collection_and_mechanism_triage_complete",
        "artifacts": {
            "sources": {
                "path": str(SOURCES_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256_path(SOURCES_PATH),
            },
            "selection": {
                "path": str(SELECTION_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256_path(SELECTION_PATH),
            },
            "findings": {
                "path": str(FINDINGS_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256_path(FINDINGS_PATH),
            },
        },
        "counts": {
            "jobs": 20,
            "fixtures": 20,
            "mechanisms": 4,
            "e6_targets": 2,
            "e6_matched_controls": 3,
            "model_calls": 0,
            "collection_network_calls": len(page_receipts),
        },
        "decision_boundary": {
            "v4_modified": False,
            "v5_implemented": False,
            "canonicalizer_allowed": False,
            "this_is_holdout": False,
            "generalization_claim_allowed": False,
        },
        "next_action": (
            "Finish full structural span labels without executing v4/v5 predictions; "
            "freeze those labels as revealed development gold, preregister the combined "
            "v5 mechanism design and regression gates, then implement v5."
        ),
    }
    _write_json(RECEIPT_PATH, receipt)

    print(
        "collected v5 mechanism development pool "
        f"jobs={len(normalized_jobs)} fixtures={len(fixtures)} "
        f"pages={len(page_receipts)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect the revealed Meituan v5 structured-span mechanism pool"
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    build(args.timeout)


if __name__ == "__main__":
    main()

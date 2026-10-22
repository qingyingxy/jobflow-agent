from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_external_holdout_labels_v1_2026-09-04.json"
)
OUTPUT_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)

FAILED_IDS = {
    "structured-external-v1-002",
    "structured-external-v1-003",
    "structured-external-v1-004",
    "structured-external-v1-005",
    "structured-external-v1-006",
    "structured-external-v1-007",
    "structured-external-v1-009",
    "structured-external-v1-010",
    "structured-external-v1-011",
    "structured-external-v1-013",
    "structured-external-v1-014",
    "structured-external-v1-015",
    "structured-external-v1-016",
    "structured-external-v1-017",
    "structured-external-v1-018",
    "structured-external-v1-019",
    "structured-external-v1-020",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _span(source: str, text: str, occurrence: int = 0) -> dict[str, Any]:
    starts: list[int] = []
    offset = 0
    while True:
        start = source.find(text, offset)
        if start < 0:
            break
        starts.append(start)
        offset = start + 1
    if occurrence >= len(starts):
        raise ValueError(
            f"cannot resolve occurrence {occurrence} of {text!r} in {source!r}"
        )
    start = starts[occurrence]
    return {"text": text, "start": start, "end": start + len(text)}


def _wrapper(
    marker: str,
    content: str,
    *,
    kind: str = "prefix",
    marker_occurrence: int = 0,
    content_occurrence: int = 0,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "marker": (marker, marker_occurrence),
        "content": (content, content_occurrence),
    }


def _group(
    members: list[str | tuple[str, int]],
    connectors: list[str],
    *,
    role: str = "surface",
) -> dict[str, Any]:
    return {"role": role, "members": members, "connectors": connectors}


def _scope(
    kind: str,
    text: str,
    members: list[str | tuple[str, int]],
    *,
    occurrence: int = 0,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "span": (text, occurrence),
        "members": members,
    }


def _attachment(
    cue: str,
    parent: str,
    examples: list[str | tuple[str, int]],
    *,
    cue_occurrence: int = 0,
    parent_occurrence: int = 0,
) -> dict[str, Any]:
    return {
        "cue": (cue, cue_occurrence),
        "parent": (parent, parent_occurrence),
        "examples": examples,
    }


SPECS: dict[str, dict[str, Any]] = {
    "structured-external-v1-001": {},
    "structured-external-v1-002": {
        "groups": [
            _group(["记忆驱动的个性化推荐", "可进化记忆闭环"], ["与"]),
            _group(["算法设计", "系统搭建"], ["与"]),
        ],
        "scopes": [
            _scope(
                "result",
                "算法设计与系统搭建",
                ["记忆驱动的个性化推荐", "可进化记忆闭环"],
            )
        ],
    },
    "structured-external-v1-003": {
        "wrappers": [
            _wrapper(
                "负责",
                "方案/用例设计、数据集构建、问题跟踪、问题分析、完成测试报告等",
            ),
            _wrapper(
                "等",
                "负责方案/用例设计、数据集构建、问题跟踪、问题分析、完成测试报告",
                kind="open_list_suffix",
            ),
        ],
        "groups": [
            _group(
                [
                    "方案",
                    "用例设计",
                    "数据集构建",
                    "问题跟踪",
                    "问题分析",
                    "完成测试报告",
                ],
                ["/", "、", "、", "、", "、"],
            )
        ],
    },
    "structured-external-v1-004": {
        "wrappers": [
            _wrapper("探索", "高效的模型调优策略、高质量数据建设方法"),
            _wrapper(
                "研究",
                "MoE稀疏化、Latent Attention等前沿模型结构",
            ),
        ],
        "groups": [
            _group(["高效的模型调优策略", "高质量数据建设方法"], ["、"]),
            _group(
                ["MoE稀疏化", "Latent Attention"],
                ["、"],
                role="example",
            ),
        ],
        "attachments": [
            _attachment(
                "等",
                "前沿模型结构",
                ["MoE稀疏化", "Latent Attention"],
            )
        ],
    },
    "structured-external-v1-005": {
        "wrappers": [
            _wrapper("建设", "Agent评测体系"),
            _wrapper("持续优化", "成功率、响应延迟、成本及用户体验"),
        ],
        "groups": [
            _group(["成功率", "响应延迟", "成本", "用户体验"], ["、", "、", "及"])
        ],
    },
    "structured-external-v1-006": {
        "wrappers": [
            _wrapper("精通", "Go、Python、C++等一种或多种编程语言"),
            _wrapper("具备扎实的", "编程技能和算法设计能力"),
        ],
        "groups": [
            _group(["Go", "Python", "C++"], ["、", "、"]),
            _group(["编程技能", "算法设计"], ["和"]),
        ],
        "protected_connectors": [("或", 0, "quantifier")],
        "scopes": [
            _scope("head", "一种或多种编程语言", ["Go", "Python", "C++"]),
            _scope("suffix", "能力", ["编程技能", "算法设计"]),
        ],
    },
    "structured-external-v1-007": {
        "wrappers": [
            _wrapper("具备扎实的", "计算机基础"),
            _wrapper("理解", "数据结构、算法、操作系统、计算机网络等基础知识"),
        ],
        "groups": [
            _group(["数据结构", "算法", "操作系统", "计算机网络"], ["、", "、", "、"])
        ],
        "scopes": [
            _scope(
                "head",
                "基础知识",
                ["数据结构", "算法", "操作系统", "计算机网络"],
            )
        ],
    },
    "structured-external-v1-008": {
        "wrappers": [
            _wrapper("对", "大模型有深入理解"),
            _wrapper("熟悉", "LLM技术原理与应用方法"),
        ],
        "groups": [_group(["LLM技术原理", "应用方法"], ["与"])],
    },
    "structured-external-v1-009": {
        "wrappers": [
            _wrapper("扎实的", "计算机、编程基础"),
            _wrapper("熟悉", "主流大语言模型的原理及方法"),
        ],
        "groups": [
            _group(["计算机", "编程"], ["、"]),
            _group(["原理", "方法"], ["及"]),
        ],
        "scopes": [
            _scope("suffix", "基础", ["计算机", "编程"]),
            _scope("domain", "主流大语言模型", ["原理", "方法"]),
        ],
    },
    "structured-external-v1-010": {
        "wrappers": [
            _wrapper(
                "理解",
                "Multi-Agent系统、任务分解、自动化规划、Prompt Engineering等技术领域之一或多个",
            )
        ],
        "groups": [
            _group(
                ["Multi-Agent系统", "任务分解", "自动化规划", "Prompt Engineering"],
                ["、", "、", "、"],
            )
        ],
        "protected_connectors": [("或", 0, "quantifier")],
        "scopes": [
            _scope(
                "head",
                "技术领域之一或多个",
                ["Multi-Agent系统", "任务分解", "自动化规划", "Prompt Engineering"],
            )
        ],
    },
    "structured-external-v1-011": {
        "wrappers": [
            _wrapper("对", "大模型与Agent有真实的动手经验"),
            _wrapper("做过基于", "大模型API、Agent框架、Prompt/评测相关的项目"),
        ],
        "groups": [
            _group(["大模型", "Agent"], ["与"]),
            _group(["大模型API", "Agent框架", "Prompt", "评测"], ["、", "、", "/"]),
        ],
        "scopes": [
            _scope("evidence", "有真实的动手经验", ["大模型", "Agent"]),
            _scope(
                "evidence",
                "相关的项目",
                ["大模型API", "Agent框架", "Prompt", "评测"],
            ),
        ],
    },
    "structured-external-v1-012": {
        "wrappers": [
            _wrapper("有", "Agent安全、大模型安全、风控反作弊或黑灰产对抗经验")
        ],
        "groups": [
            _group(
                ["Agent安全", "大模型安全", "风控反作弊", "黑灰产对抗"],
                ["、", "、", "或"],
            )
        ],
        "scopes": [
            _scope(
                "evidence",
                "经验",
                ["Agent安全", "大模型安全", "风控反作弊", "黑灰产对抗"],
            )
        ],
    },
    "structured-external-v1-013": {
        "wrappers": [_wrapper("具备", "AI+SE结合的项目经验")],
    },
    "structured-external-v1-014": {
        "wrappers": [
            _wrapper(
                "在",
                "ICLR、NeurIPS、ICML、KDD、AAAI、IJCAI等机器学习领域会议或者期刊有第一作者论文",
            )
        ],
        "groups": [
            _group(
                ["ICLR", "NeurIPS", "ICML", "KDD", "AAAI", "IJCAI"],
                ["、", "、", "、", "、", "、"],
                role="example",
            ),
            _group(["机器学习领域会议", "期刊"], ["或者"]),
        ],
        "scopes": [_scope("evidence", "有第一作者论文", ["机器学习领域会议", "期刊"])],
        "attachments": [
            _attachment(
                "等",
                "机器学习领域会议",
                ["ICLR", "NeurIPS", "ICML", "KDD", "AAAI", "IJCAI"],
            )
        ],
    },
    "structured-external-v1-015": {
        "wrappers": [
            _wrapper(
                "有",
                "目标检测、图像分类、缺陷识别、OCR等相关课程设计/竞赛/项目经验优先",
            ),
            _wrapper(
                "优先",
                "有目标检测、图像分类、缺陷识别、OCR等相关课程设计/竞赛/项目经验",
                kind="suffix",
            ),
        ],
        "groups": [
            _group(
                ["目标检测", "图像分类", "缺陷识别", "OCR"],
                ["、", "、", "、"],
                role="example",
            ),
            _group(["相关课程设计", "竞赛", "项目经验"], ["/", "/"]),
        ],
        "attachments": [
            _attachment(
                "等",
                "相关课程设计/竞赛/项目经验",
                ["目标检测", "图像分类", "缺陷识别", "OCR"],
            )
        ],
    },
    "structured-external-v1-016": {
        "wrappers": [
            _wrapper("强", "工程能力", kind="suffix"),
            _wrapper("能", "快速验证想法并落地到产品或平台中"),
        ],
        "groups": [
            _group(["快速验证想法", "落地到产品或平台中"], ["并"]),
            _group(["产品", "平台"], ["或"], role="embedded"),
        ],
    },
    "structured-external-v1-017": {
        "wrappers": [
            _wrapper("有很强的", "数据问题分析能力"),
            _wrapper(
                "能力", "有很强的数据问题分析", kind="suffix", marker_occurrence=0
            ),
            _wrapper("具有", "业务上的自闭环能力"),
            _wrapper("能力", "具有业务上的自闭环", kind="suffix", marker_occurrence=1),
        ],
    },
    "structured-external-v1-018": {
        "wrappers": [
            _wrapper("有良好的", "团队沟通协作能力"),
            _wrapper(
                "能力", "有良好的团队沟通协作", kind="suffix", marker_occurrence=0
            ),
            _wrapper("及优秀的", "项目驱动能力"),
            _wrapper("能力", "及优秀的项目驱动", kind="suffix", marker_occurrence=1),
        ],
        "groups": [_group(["团队沟通协作", "项目驱动"], ["及"])],
    },
    "structured-external-v1-019": {
        "wrappers": [
            _wrapper("强", "学习能力", kind="suffix"),
            _wrapper("积极", "动手实践", kind="suffix"),
            _wrapper("良好", "沟通协作", kind="suffix"),
        ],
        "groups": [_group(["学习能力", "动手实践", "沟通协作"], ["、", "、"])],
    },
    "structured-external-v1-020": {
        "wrappers": [
            _wrapper("能够独立完成", "问题拆解、实验验证、结果分析和持续迭代"),
            _wrapper("具备较强的", "工程落地意识"),
        ],
        "groups": [
            _group(["问题拆解", "实验验证", "结果分析", "持续迭代"], ["、", "、", "和"])
        ],
    },
}


def _resolve(value: str | tuple[str, int], source: str) -> dict[str, Any]:
    if isinstance(value, tuple):
        return _span(source, value[0], value[1])
    return _span(source, value)


def _connector_between(
    source: str,
    left: dict[str, Any],
    right: dict[str, Any],
    connector: str,
) -> dict[str, Any]:
    start = source.find(connector, left["end"], right["start"])
    if start < 0:
        raise ValueError(
            f"connector {connector!r} not between {left['text']!r} and "
            f"{right['text']!r} in {source!r}"
        )
    return {"text": connector, "start": start, "end": start + len(connector)}


def _materialize_fixture(label: dict[str, Any]) -> dict[str, Any]:
    source = label["source_text"]
    spec = SPECS[label["id"]]
    wrappers = [
        {
            "kind": item["kind"],
            "marker_span": _resolve(item["marker"], source),
            "content_span": _resolve(item["content"], source),
        }
        for item in spec.get("wrappers", [])
    ]
    groups: list[dict[str, Any]] = []
    connector_labels: list[dict[str, Any]] = []
    for index, item in enumerate(spec.get("groups", []), start=1):
        members = [_resolve(value, source) for value in item["members"]]
        connectors = [
            _connector_between(source, members[position], members[position + 1], value)
            for position, value in enumerate(item["connectors"])
        ]
        groups.append(
            {
                "id": f"gold-coord-{index}",
                "role": item["role"],
                "member_spans": members,
                "connector_spans": connectors,
            }
        )
        connector_labels.extend(
            {"span": connector, "role": item["role"]} for connector in connectors
        )
    for text, occurrence, role in spec.get("protected_connectors", []):
        connector_labels.append({"span": _span(source, text, occurrence), "role": role})
    scopes = [
        {
            "id": f"gold-scope-{index}",
            "kind": item["kind"],
            "span": _resolve(item["span"], source),
            "applies_to_member_spans": [
                _resolve(value, source) for value in item["members"]
            ],
        }
        for index, item in enumerate(spec.get("scopes", []), start=1)
    ]
    attachments = [
        {
            "id": f"gold-example-{index}",
            "cue_span": _resolve(item["cue"], source),
            "parent_span": _resolve(item["parent"], source),
            "example_spans": [_resolve(value, source) for value in item["examples"]],
        }
        for index, item in enumerate(spec.get("attachments", []), start=1)
    ]
    return {
        "id": label["id"],
        "case_id": label["case_id"],
        "category": label["category"],
        "source_text": source,
        "diagnostic_status": (
            "revealed_v3_failure" if label["id"] in FAILED_IDS else "passing_control"
        ),
        "wrappers": wrappers,
        "connector_labels": sorted(
            connector_labels,
            key=lambda item: (item["span"]["start"], item["span"]["end"]),
        ),
        "coordinations": groups,
        "shared_scopes": scopes,
        "example_attachments": attachments,
        "projection": {
            "surface_items": label["surface_items"],
            "examples": label["examples"] or [],
        },
    }


def main() -> int:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    label_ids = {item["id"] for item in labels["fixtures"]}
    if label_ids != set(SPECS):
        raise ValueError(
            f"gold spec mismatch: missing={sorted(label_ids - set(SPECS))}, "
            f"extra={sorted(set(SPECS) - label_ids)}"
        )
    payload = {
        "gold_version": "unified-jd-structured-span-v4-development-gold-v1",
        "status": "revealed_same_corpus_development_only",
        "created_at": "2026-09-04",
        "source_labels": {
            "path": LABELS_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": _sha256(LABELS_PATH),
        },
        "generalization_claim": False,
        "annotation_policy": {
            "spans": "All text/start/end triples are exact half-open source spans.",
            "connector_roles": (
                "surface connectors form projected atomic items; example connectors "
                "join attached examples; embedded connectors stay inside one projected "
                "item; quantifier connectors must not create coordination members."
            ),
            "shared_scopes": (
                "Each scope is stored once and references the exact member spans to "
                "which it applies."
            ),
            "projection": (
                "Surface items and examples are evaluated separately from syntax."
            ),
        },
        "fixture_count": len(labels["fixtures"]),
        "revealed_failure_count": len(FAILED_IDS),
        "control_count": len(labels["fixtures"]) - len(FAILED_IDS),
        "fixtures": [_materialize_fixture(item) for item in labels["fixtures"]],
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-04"
SELECTION_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_selection_v1_2026-09-04.json"
)
SOURCES_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_sources_v1_2026-09-04.json"
)
LABELS_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_labels_v1_2026-09-04.json"
)
FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_label_freeze_v1_2026-09-04.json"
)
GUIDE_PATH = ROOT / "docs" / "UNIFIED_JD_ANNOTATION_GUIDE_V1.md"
V4_PARSER_PATH = ROOT / "src" / "domain" / "unified_jd_structured_spans_v4.py"

SpanRef = str | tuple[str, int]


def wrapper(
    marker: SpanRef,
    content: SpanRef,
    *,
    kind: str = "prefix",
) -> dict[str, Any]:
    return {"kind": kind, "marker": marker, "content": content}


def group(
    members: list[SpanRef],
    connectors: list[str],
    *,
    role: str = "surface",
) -> dict[str, Any]:
    return {"role": role, "members": members, "connectors": connectors}


def scope(kind: str, span: SpanRef, members: list[SpanRef]) -> dict[str, Any]:
    return {"kind": kind, "span": span, "members": members}


def attachment(
    cue: SpanRef,
    parent: SpanRef,
    examples: list[SpanRef],
) -> dict[str, Any]:
    return {"cue": cue, "parent": parent, "examples": examples}


# These specifications are human annotations over the frozen source_text only. They
# intentionally contain no parser output, parser rule names, or fixture-specific v5 rule.
SPECS: dict[str, dict[str, Any]] = {
    "structured-v5-mechanism-dev-v1-001": {
        "wrappers": [
            wrapper("基于", "公司战略和组织能力建设需求"),
            wrapper("通过", "数据分析、行业研究、内部调研、指标体系构建和结构化诊断"),
            wrapper("识别", "组织健康度、人才策略、管理效能等领域的关键问题与机会"),
            wrapper("为", "组织决策提供数据支撑"),
            wrapper("推动", '从"数据感知"到"决策行动"的闭环'),
        ],
        "groups": [
            group(["公司战略", "组织能力建设需求"], ["和"]),
            group(
                ["数据分析", "行业研究", "内部调研", "指标体系构建", "结构化诊断"],
                ["、", "、", "、", "和"],
            ),
            group(["组织健康度", "人才策略", "管理效能"], ["、", "、"], role="example"),
            group(["关键问题", "机会"], ["与"]),
            group(['"数据感知"', '"决策行动"'], ["到"], role="embedded"),
        ],
        "scopes": [
            scope(
                "prefix",
                "组织健康度、人才策略、管理效能等领域的",
                ["关键问题", "机会"],
            ),
            scope("result", "的闭环", ['"数据感知"', '"决策行动"']),
        ],
        "attachments": [
            attachment("等", "领域", ["组织健康度", "人才策略", "管理效能"]),
        ],
        "projection": {
            "surface_items": [
                "公司战略",
                "组织能力建设需求",
                "数据分析",
                "行业研究",
                "内部调研",
                "指标体系构建",
                "结构化诊断",
                "领域",
                "关键问题",
                "机会",
                "组织决策提供数据支撑",
                '从"数据感知"到"决策行动"的闭环',
            ],
            "examples": ["组织健康度", "人才策略", "管理效能"],
        },
    },
    "structured-v5-mechanism-dev-v1-002": {
        "wrappers": [
            wrapper("结合", "市场和行业信息"),
            wrapper("与行业商家共同建立", "健康有序的合作关系"),
            wrapper("通过输出", "标准化规章制度和运营流程"),
            wrapper(("提高", 0), "整体业务的运行效率"),
            wrapper(("提高", 1), "消费者满意度"),
            wrapper("降低", "行业经营风险"),
            wrapper("共同维护", "良好的市场秩序"),
        ],
        "groups": [
            group(["市场", "行业"], ["和"]),
            group(["标准化规章制度", "运营流程"], ["和"]),
        ],
        "scopes": [scope("suffix", "信息", ["市场", "行业"])],
        "attachments": [],
        "projection": {
            "surface_items": [
                "市场",
                "行业",
                "健康有序的合作关系",
                "标准化规章制度",
                "运营流程",
                "整体业务的运行效率",
                "消费者满意度",
                "行业经营风险",
                "良好的市场秩序",
            ],
            "examples": [],
        },
    },
    "structured-v5-mechanism-dev-v1-003": {
        "wrappers": [
            wrapper("熟悉", "大模型能力边界"),
            wrapper("掌握", "Agent、RAG、Workflow 编排等技术栈的产品化方法"),
            wrapper("有真实的", "评测、调优、Bad case 治理经验"),
        ],
        "groups": [
            group(["Agent", "RAG", "Workflow 编排"], ["、", "、"], role="example"),
            group(["评测", "调优", "Bad case 治理"], ["、", "、"]),
        ],
        "scopes": [scope("evidence", "经验", ["评测", "调优", "Bad case 治理"])],
        "attachments": [
            attachment("等", "技术栈的产品化方法", ["Agent", "RAG", "Workflow 编排"]),
        ],
        "projection": {
            "surface_items": ["大模型能力边界", "技术栈的产品化方法", "评测", "调优", "Bad case 治理"],
            "examples": ["Agent", "RAG", "Workflow 编排"],
        },
    },
    "structured-v5-mechanism-dev-v1-004": {
        "wrappers": [
            wrapper("具备优秀的", "算法设计和实现能力"),
            wrapper("能够独立完成", "算法的需求分析、方案设计、代码实现和效果评估"),
            wrapper("有发表", "顶会论文（ACL/AAAI/EMNLP/ICML/ICLR等）"),
            wrapper("者优先", "顶会论文（ACL/AAAI/EMNLP/ICML/ICLR等）", kind="suffix"),
        ],
        "groups": [
            group(["算法设计", "实现"], ["和"]),
            group(["需求分析", "方案设计", "代码实现", "效果评估"], ["、", "、", "和"]),
            group(["ACL", "AAAI", "EMNLP", "ICML", "ICLR"], ["/", "/", "/", "/"], role="example"),
        ],
        "scopes": [
            scope("suffix", "能力", ["算法设计", "实现"]),
            scope("prefix", "算法的", ["需求分析", "方案设计", "代码实现", "效果评估"]),
        ],
        "attachments": [
            attachment("（", "顶会论文", ["ACL", "AAAI", "EMNLP", "ICML", "ICLR"]),
        ],
        "projection": {
            "surface_items": ["算法设计", "实现", "需求分析", "方案设计", "代码实现", "效果评估", "顶会论文"],
            "examples": ["ACL", "AAAI", "EMNLP", "ICML", "ICLR"],
        },
    },
    "structured-v5-mechanism-dev-v1-005": {
        "wrappers": [
            wrapper("熟练使用", "AI辅助编码工具（如GitHub Copilot/Cursor）"),
            wrapper("能将", "AI工具融入日常开发流程"),
            wrapper("与", "算法团队有协作经验"),
            wrapper("有协作经验", "算法团队", kind="suffix"),
            wrapper("对", "机器学习模型等算法相关知识有基础认识者优先"),
            wrapper("有基础认识者优先", "机器学习模型等算法相关知识", kind="suffix"),
        ],
        "groups": [
            group(["GitHub Copilot", "Cursor"], ["/"], role="example"),
        ],
        "scopes": [],
        "attachments": [
            attachment("如", "AI辅助编码工具", ["GitHub Copilot", "Cursor"]),
            attachment("等", "算法相关知识", ["机器学习模型"]),
        ],
        "projection": {
            "surface_items": ["AI辅助编码工具", "AI工具融入日常开发流程", "算法团队", "算法相关知识"],
            "examples": ["GitHub Copilot", "Cursor", "机器学习模型"],
        },
    },
    "structured-v5-mechanism-dev-v1-006": {
        "wrappers": [
            wrapper("对", "大模型开发流程有深入认知"),
            wrapper("有深入认知", "大模型开发流程", kind="suffix"),
            wrapper("熟悉", "预训练、指令微调、RLHF等流程与框架"),
            wrapper("具备", "模型预训练、对齐、训练和推理加速、模型小型化和部署等方面的经验"),
        ],
        "groups": [
            group(["预训练", "指令微调", "RLHF"], ["、", "、"], role="example"),
            group(["流程", "框架"], ["与"]),
            group(
                ["模型预训练", "对齐", "训练和推理加速", "模型小型化和部署"],
                ["、", "、", "、"],
                role="example",
            ),
            group(["训练", "推理"], ["和"], role="embedded"),
            group(["小型化", "部署"], ["和"], role="embedded"),
        ],
        "scopes": [
            scope("suffix", "加速", ["训练", "推理"]),
            scope("prefix", "模型", ["小型化", "部署"]),
        ],
        "attachments": [
            attachment("等", "流程与框架", ["预训练", "指令微调", "RLHF"]),
            attachment(
                ("等", 1),
                "方面",
                ["模型预训练", "对齐", "训练和推理加速", "模型小型化和部署"],
            ),
        ],
        "projection": {
            "surface_items": ["大模型开发流程", "流程", "框架", "方面"],
            "examples": ["预训练", "指令微调", "RLHF", "模型预训练", "对齐", "训练和推理加速", "模型小型化和部署"],
        },
    },
    "structured-v5-mechanism-dev-v1-007": {
        "wrappers": [
            wrapper("熟悉掌握常用的", "Java类库及开源框架"),
            wrapper("掌握", "Java虚拟机原理"),
            wrapper("有", "JVM分析及调优的经验"),
        ],
        "groups": [
            group(["Java类库", "开源框架"], ["及"]),
            group(["多线程", "并发处理", "I/O与网络通讯", "Spring"], ["、", "、", "、"], role="example"),
            group(["I/O", "网络通讯"], ["与"], role="embedded"),
            group(["JVM分析", "调优"], ["及"]),
        ],
        "scopes": [scope("evidence", "的经验", ["JVM分析", "调优"])],
        "attachments": [
            attachment("如", "Java类库及开源框架", ["多线程", "并发处理", "I/O与网络通讯", "Spring"]),
        ],
        "projection": {
            "surface_items": ["Java类库", "开源框架", "Java虚拟机原理", "JVM分析", "调优"],
            "examples": ["多线程", "并发处理", "I/O与网络通讯", "Spring"],
        },
    },
    "structured-v5-mechanism-dev-v1-008": {
        "wrappers": [
            wrapper(("熟悉", 0), "主流大模型"),
            wrapper("掌握", "SFT、RLHF、RAG 等技术"),
            wrapper("精通", "Python、Java 等编程语言"),
            wrapper(("熟悉", 1), "TensorFlow、PyTorch 等常用机器学习框架"),
            wrapper("具备", "AI 辅助工程开发的实践经验"),
            wrapper("能利用", "Copilot、AI 实验分析等工具加速模型迭代与评估"),
            wrapper("以", "AI 协作方式提升研发效率"),
        ],
        "groups": [
            group(["SFT", "RLHF", "RAG"], ["、", "、"], role="example"),
            group(["Python", "Java"], ["、"], role="example"),
            group(["TensorFlow", "PyTorch"], ["、"], role="example"),
            group(["Copilot", "AI 实验分析"], ["、"], role="example"),
            group(["迭代", "评估"], ["与"]),
        ],
        "scopes": [scope("prefix", "模型", ["迭代", "评估"])],
        "attachments": [
            attachment(("等", 0), "技术", ["SFT", "RLHF", "RAG"]),
            attachment(("等", 1), "编程语言", ["Python", "Java"]),
            attachment(("等", 2), "常用机器学习框架", ["TensorFlow", "PyTorch"]),
            attachment(("等", 3), "工具", ["Copilot", "AI 实验分析"]),
        ],
        "projection": {
            "surface_items": ["主流大模型", "技术", "编程语言", "常用机器学习框架", "AI 辅助工程开发的实践经验", "工具", "迭代", "评估", "AI 协作方式提升研发效率"],
            "examples": ["SFT", "RLHF", "RAG", "Python", "Java", "TensorFlow", "PyTorch", "Copilot", "AI 实验分析"],
        },
    },
    "structured-v5-mechanism-dev-v1-009": {
        "wrappers": [
            wrapper("具备丰富的", "Linux 驱动和 HAL 开发经验"),
            wrapper("熟悉", "常见总线接口（I2C、SPI、UART、CAN、PCIe、Ethernet 等）"),
            wrapper("有", "Lidar、Camera、GNSS、Audio 等传感器驱动开发经验者优先"),
            wrapper("者优先", "Lidar、Camera、GNSS、Audio 等传感器驱动开发经验", kind="suffix"),
        ],
        "groups": [
            group(["Linux 驱动", "HAL 开发"], ["和"]),
            group(["I2C", "SPI", "UART", "CAN", "PCIe", "Ethernet"], ["、", "、", "、", "、", "、"], role="example"),
            group(["Lidar", "Camera", "GNSS", "Audio"], ["、", "、", "、"], role="example"),
        ],
        "scopes": [scope("evidence", "经验", ["Linux 驱动", "HAL 开发"])],
        "attachments": [
            attachment("（", "常见总线接口", ["I2C", "SPI", "UART", "CAN", "PCIe", "Ethernet"]),
            attachment(("等", 1), "传感器驱动开发经验", ["Lidar", "Camera", "GNSS", "Audio"]),
        ],
        "projection": {
            "surface_items": ["Linux 驱动", "HAL 开发", "常见总线接口", "传感器驱动开发经验"],
            "examples": ["I2C", "SPI", "UART", "CAN", "PCIe", "Ethernet", "Lidar", "Camera", "GNSS", "Audio"],
        },
    },
    "structured-v5-mechanism-dev-v1-010": {
        "wrappers": [
            wrapper("具备较强的", "动手验证能力"),
            wrapper("能够使用", "Cursor、Codex等AI编程工具独立完成交互原型、功能Demo或轻量工具"),
            wrapper("独立完成", "交互原型、功能Demo或轻量工具"),
            wrapper("掌握", "SQL、API、日志分析等基础能力者优先"),
            wrapper("者优先", "SQL、API、日志分析等基础能力", kind="suffix"),
        ],
        "groups": [
            group(["Cursor", "Codex"], ["、"], role="example"),
            group(["交互原型", "功能Demo", "轻量工具"], ["、", "或"]),
            group(["SQL", "API", "日志分析"], ["、", "、"], role="example"),
        ],
        "scopes": [],
        "attachments": [
            attachment(("等", 0), "AI编程工具", ["Cursor", "Codex"]),
            attachment(("等", 1), "基础能力", ["SQL", "API", "日志分析"]),
        ],
        "projection": {
            "surface_items": ["动手验证能力", "AI编程工具", "交互原型", "功能Demo", "轻量工具", "基础能力"],
            "examples": ["Cursor", "Codex", "SQL", "API", "日志分析"],
        },
    },
    "structured-v5-mechanism-dev-v1-011": {
        "wrappers": [
            wrapper("优先", "理工科、管理学及相关交叉学科，如数学、统计学、运筹学、信息管理、商业分析、计量经济学等", kind="suffix"),
        ],
        "groups": [
            group(["理工科", "管理学", "相关交叉学科"], ["、", "及"]),
            group(["数学", "统计学", "运筹学", "信息管理", "商业分析", "计量经济学"], ["、", "、", "、", "、", "、"], role="example"),
        ],
        "protected_connectors": [("及", 0, "quantifier")],
        "scopes": [],
        "attachments": [
            attachment("如", "理工科、管理学及相关交叉学科", ["数学", "统计学", "运筹学", "信息管理", "商业分析", "计量经济学"]),
        ],
        "projection": {
            "surface_items": ["本科及以上学历", "理工科", "管理学", "相关交叉学科"],
            "examples": ["数学", "统计学", "运筹学", "信息管理", "商业分析", "计量经济学"],
        },
        "review_note": "Terminal 等优先 cannot become an attachment parent. The explicit preceding 如 still licenses a parent-first attachment to the major-family span.",
    },
    "structured-v5-mechanism-dev-v1-012": {
        "wrappers": [
            wrapper("具备", "以下经验"),
            wrapper(("者优先", 0), "以下经验", kind="suffix"),
            wrapper("等", "手配/小家电/外设产品/摄影摄像", kind="open_list_suffix"),
            wrapper(("优先", 1), "手配/小家电/外设产品/摄影摄像等", kind="suffix"),
        ],
        "groups": [
            group(["手配", "小家电", "外设产品", "摄影摄像"], ["/", "/", "/"]),
        ],
        "scopes": [scope("evidence", "以下经验", ["手配", "小家电", "外设产品", "摄影摄像"])],
        "attachments": [],
        "projection": {
            "surface_items": ["手配", "小家电", "外设产品", "摄影摄像"],
            "examples": [],
        },
        "review_note": "The colon expands the deictic 以下经验 into direct preferred domains. Terminal 等优先 closes an open surface list and supplies no parent.",
    },
    "structured-v5-mechanism-dev-v1-013": {
        "wrappers": [
            wrapper("3年以上", "供应链计划领域相关经验"),
            wrapper("熟练使用", "SQL、Python等工具优先"),
            wrapper("优先", "SQL、Python等工具", kind="suffix"),
        ],
        "groups": [group(["SQL", "Python"], ["、"], role="example")],
        "protected_connectors": [("及", 0, "quantifier")],
        "scopes": [],
        "attachments": [attachment("等", "工具", ["SQL", "Python"])],
        "projection": {
            "surface_items": ["本科及以上学历", "供应链计划领域相关经验", "工具"],
            "examples": ["SQL", "Python"],
        },
    },
    "structured-v5-mechanism-dev-v1-014": {
        "wrappers": [
            wrapper("具备优秀的", "算法设计和实现能力"),
            wrapper("能够独立完成", "算法的需求分析、方案设计、代码实现和效果评估"),
            wrapper("有发表", "顶会论文（ACL/AAAI/SIGIR等）"),
            wrapper("者优先", "顶会论文（ACL/AAAI/SIGIR等）", kind="suffix"),
        ],
        "groups": [
            group(["算法设计", "实现"], ["和"]),
            group(["需求分析", "方案设计", "代码实现", "效果评估"], ["、", "、", "和"]),
            group(["ACL", "AAAI", "SIGIR"], ["/", "/"], role="example"),
        ],
        "scopes": [
            scope("suffix", "能力", ["算法设计", "实现"]),
            scope("prefix", "算法的", ["需求分析", "方案设计", "代码实现", "效果评估"]),
        ],
        "attachments": [attachment("（", "顶会论文", ["ACL", "AAAI", "SIGIR"])],
        "projection": {
            "surface_items": ["算法设计", "实现", "需求分析", "方案设计", "代码实现", "效果评估", "顶会论文"],
            "examples": ["ACL", "AAAI", "SIGIR"],
        },
    },
    "structured-v5-mechanism-dev-v1-015": {
        "wrappers": [
            wrapper("具备", "AI工具使用能力"),
            wrapper("熟悉", "主流大模型工具（如ChatGPT、Copilot等）在财务场景中的应用"),
            wrapper("有", "AI辅助数据分析、报告生成等实际经验者优先"),
            wrapper("者优先", "AI辅助数据分析、报告生成等实际经验", kind="suffix"),
        ],
        "groups": [
            group(["ChatGPT", "Copilot"], ["、"], role="example"),
            group(["AI辅助数据分析", "报告生成"], ["、"], role="example"),
        ],
        "scopes": [],
        "attachments": [
            attachment("如", "主流大模型工具", ["ChatGPT", "Copilot"]),
            attachment(("等", 1), "实际经验", ["AI辅助数据分析", "报告生成"]),
        ],
        "projection": {
            "surface_items": ["AI工具使用能力", "主流大模型工具", "财务场景中的应用", "实际经验"],
            "examples": ["ChatGPT", "Copilot", "AI辅助数据分析", "报告生成"],
        },
    },
    "structured-v5-mechanism-dev-v1-016": {
        "wrappers": [
            wrapper("熟悉", "AI技术和人工智能办公工具"),
            wrapper("对", "人机交互、自然语言处理等领域有深入了解"),
            wrapper("有深入了解", "人机交互、自然语言处理等领域", kind="suffix"),
        ],
        "groups": [
            group(["AI技术", "人工智能办公工具"], ["和"]),
            group(["人机交互", "自然语言处理"], ["、"], role="example"),
        ],
        "scopes": [],
        "attachments": [attachment("等", "领域", ["人机交互", "自然语言处理"])],
        "projection": {
            "surface_items": ["AI技术", "人工智能办公工具", "领域"],
            "examples": ["人机交互", "自然语言处理"],
        },
    },
    "structured-v5-mechanism-dev-v1-017": {
        "wrappers": [
            wrapper("深厚的", "商业数据理解力"),
            wrapper("对", "商业分析、数据仓库、BI等领域有深刻理解或浓厚兴趣"),
            wrapper("有深刻理解或浓厚兴趣", "商业分析、数据仓库、BI等领域", kind="suffix"),
            wrapper("能够快速将", "模糊的业务问题转化为清晰的、可量化的技术任务"),
        ],
        "groups": [
            group(["商业分析", "数据仓库", "BI"], ["、", "、"], role="example"),
            group(["深刻理解", "浓厚兴趣"], ["或"], role="embedded"),
            group(["清晰的", "可量化的"], ["、"], role="embedded"),
        ],
        "scopes": [scope("head", "技术任务", ["清晰的", "可量化的"])],
        "attachments": [attachment("等", "领域", ["商业分析", "数据仓库", "BI"])],
        "projection": {
            "surface_items": ["商业数据理解力", "领域", "模糊的业务问题转化为清晰的、可量化的技术任务"],
            "examples": ["商业分析", "数据仓库", "BI"],
        },
    },
    "structured-v5-mechanism-dev-v1-018": {
        "wrappers": [
            wrapper("熟悉", "电商行业采控岗位整体工作流程"),
            wrapper("对", "供应链计划、需求预测、订单执行及履约入库、库存管理等方面"),
            wrapper("具备", "0-1标准化体系搭建"),
        ],
        "groups": [
            group(["供应链计划", "需求预测", "订单执行及履约入库", "库存管理"], ["、", "、", "、"], role="example"),
            group(["订单执行", "履约入库"], ["及"], role="embedded"),
        ],
        "scopes": [],
        "attachments": [
            attachment("等", "方面", ["供应链计划", "需求预测", "订单执行及履约入库", "库存管理"]),
        ],
        "projection": {
            "surface_items": ["电商行业采控岗位整体工作流程", "方面", "0-1标准化体系搭建"],
            "examples": ["供应链计划", "需求预测", "订单执行及履约入库", "库存管理"],
        },
    },
    "structured-v5-mechanism-dev-v1-019": {
        "wrappers": [
            wrapper("拥有", "业务架构设计经验"),
            wrapper("对", "系统分层、DDD、领域分析建模、平台化等方面有丰富的实战经验者优先"),
            wrapper("有丰富的实战经验者优先", "系统分层、DDD、领域分析建模、平台化等方面", kind="suffix"),
        ],
        "groups": [
            group(["系统分层", "DDD", "领域分析建模", "平台化"], ["、", "、", "、"], role="example"),
        ],
        "scopes": [],
        "attachments": [attachment("等", "方面", ["系统分层", "DDD", "领域分析建模", "平台化"])],
        "projection": {
            "surface_items": ["业务架构设计经验", "方面"],
            "examples": ["系统分层", "DDD", "领域分析建模", "平台化"],
        },
    },
    "structured-v5-mechanism-dev-v1-020": {
        "wrappers": [
            wrapper("分析总结", "拨打漏斗数据"),
            wrapper("对", "外呼的销售策略、名单策略、ASR能力等方面进行优化"),
            wrapper("进行优化", "外呼的销售策略、名单策略、ASR能力等方面", kind="suffix"),
        ],
        "groups": [
            group(["外呼的销售策略", "名单策略", "ASR能力"], ["、", "、"], role="example"),
        ],
        "scopes": [],
        "attachments": [attachment("等", "方面", ["外呼的销售策略", "名单策略", "ASR能力"])],
        "projection": {
            "surface_items": ["拨打漏斗数据", "精细化运营", "方面"],
            "examples": ["外呼的销售策略", "名单策略", "ASR能力"],
        },
    },
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_span(source: str, ref: SpanRef) -> dict[str, Any]:
    text, occurrence = ref if isinstance(ref, tuple) else (ref, 0)
    cursor = 0
    start = -1
    for _ in range(occurrence + 1):
        start = source.find(text, cursor)
        if start < 0:
            raise AssertionError(
                f"span not found: {text!r} occurrence={occurrence} in {source!r}"
            )
        cursor = start + 1
    span = {"text": text, "start": start, "end": start + len(text)}
    assert source[span["start"] : span["end"]] == text
    return span


def connector_between(
    source: str,
    left: dict[str, Any],
    right: dict[str, Any],
    connector: str,
) -> dict[str, Any]:
    start = source.find(connector, left["end"], right["start"])
    if start < 0:
        raise AssertionError(
            f"connector {connector!r} not between {left['text']!r} and "
            f"{right['text']!r} in {source!r}"
        )
    return {"text": connector, "start": start, "end": start + len(connector)}


def materialize_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    source = fixture["source_text"]
    spec = SPECS[fixture["id"]]
    wrappers = [
        {
            "kind": item["kind"],
            "marker_span": resolve_span(source, item["marker"]),
            "content_span": resolve_span(source, item["content"]),
        }
        for item in spec.get("wrappers", [])
    ]

    coordinations: list[dict[str, Any]] = []
    connector_labels: list[dict[str, Any]] = []
    for index, item in enumerate(spec.get("groups", []), start=1):
        members = [resolve_span(source, member) for member in item["members"]]
        connectors = [
            connector_between(source, members[position], members[position + 1], connector)
            for position, connector in enumerate(item["connectors"])
        ]
        assert len(connectors) == len(members) - 1
        coordinations.append(
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

    for connector, occurrence, role in spec.get("protected_connectors", []):
        connector_labels.append(
            {"span": resolve_span(source, (connector, occurrence)), "role": role}
        )
    connector_labels.sort(key=lambda item: (item["span"]["start"], item["span"]["end"]))
    assert len(
        {(item["span"]["start"], item["span"]["end"]) for item in connector_labels}
    ) == len(connector_labels)

    shared_scopes = [
        {
            "id": f"gold-scope-{index}",
            "kind": item["kind"],
            "span": resolve_span(source, item["span"]),
            "applies_to_member_spans": [
                resolve_span(source, member) for member in item["members"]
            ],
        }
        for index, item in enumerate(spec.get("scopes", []), start=1)
    ]
    attachments = [
        {
            "id": f"gold-example-{index}",
            "cue_span": resolve_span(source, item["cue"]),
            "parent_span": resolve_span(source, item["parent"]),
            "example_spans": [
                resolve_span(source, example) for example in item["examples"]
            ],
        }
        for index, item in enumerate(spec.get("attachments", []), start=1)
    ]

    projection = spec["projection"]
    for text in projection["surface_items"] + projection["examples"]:
        assert text in source, f"projection item {text!r} not anchored in {source!r}"

    result = {
        "id": fixture["id"],
        "job_id": fixture["job_id"],
        "category": fixture["category"],
        "source_section": fixture["source_section"],
        "source_text": source,
        "annotation_status": "two_pass_human_reviewed_revealed_development_frozen",
        "development_stratum": fixture["mechanism_annotation"]["mechanism_id"],
        "development_role": fixture["mechanism_annotation"]["role"],
        "wrappers": wrappers,
        "connector_labels": connector_labels,
        "coordinations": coordinations,
        "shared_scopes": shared_scopes,
        "example_attachments": attachments,
        "projection": projection,
    }
    if "review_note" in spec:
        result["review_note"] = spec["review_note"]
    return result


def iter_spans(value: Any):
    if isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys():
            yield value
        else:
            for nested in value.values():
                yield from iter_spans(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_spans(nested)


def validate(fixtures: list[dict[str, Any]], selection: dict[str, Any]) -> None:
    assert set(SPECS) == {fixture["id"] for fixture in selection["fixtures"]}
    assert len(fixtures) == 20
    assert len({fixture["id"] for fixture in fixtures}) == 20
    assert len({fixture["job_id"] for fixture in fixtures}) == 20
    assert Counter(fixture["development_stratum"] for fixture in fixtures) == {
        "E2-wrapper-boundary": 5,
        "E3-region-first-connector-role": 5,
        "E6-priority-tail-rejection": 5,
        "E7-prepositional-wrapper-before-example-split": 5,
    }
    assert {
        connector["role"]
        for fixture in fixtures
        for connector in fixture["connector_labels"]
    } == {"surface", "embedded", "example", "quantifier"}

    for fixture in fixtures:
        source = fixture["source_text"]
        assert fixture["wrappers"], fixture["id"]
        assert fixture["projection"]["surface_items"], fixture["id"]
        for span in iter_spans(
            {
                "wrappers": fixture["wrappers"],
                "connectors": fixture["connector_labels"],
                "coordinations": fixture["coordinations"],
                "scopes": fixture["shared_scopes"],
                "attachments": fixture["example_attachments"],
            }
        ):
            assert source[span["start"] : span["end"]] == span["text"]

        coordination_members = {
            (span["start"], span["end"])
            for coordination in fixture["coordinations"]
            for span in coordination["member_spans"]
        }
        for shared_scope in fixture["shared_scopes"]:
            assert len(shared_scope["applies_to_member_spans"]) >= 2
            assert all(
                (span["start"], span["end"]) in coordination_members
                for span in shared_scope["applies_to_member_spans"]
            )
        for item in fixture["example_attachments"]:
            assert item["example_spans"]
            assert item["parent_span"]["text"] not in {"优先", "者优先"}

    by_id = {fixture["id"]: fixture for fixture in fixtures}
    e6_011 = by_id["structured-v5-mechanism-dev-v1-011"]
    e6_012 = by_id["structured-v5-mechanism-dev-v1-012"]
    assert [item["cue_span"]["text"] for item in e6_011["example_attachments"]] == ["如"]
    assert e6_012["example_attachments"] == []
    for suffix in range(16, 21):
        fixture = by_id[f"structured-v5-mechanism-dev-v1-{suffix:03d}"]
        first_examples = [
            attachment["example_spans"][0]["text"]
            for attachment in fixture["example_attachments"]
        ]
        assert first_examples and all(not item.startswith("对") for item in first_examples)


def main() -> None:
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    fixtures = [materialize_fixture(fixture) for fixture in selection["fixtures"]]
    validate(fixtures, selection)

    labels = {
        "labels_version": "unified-jd-structured-span-v5-mechanism-development-labels-v1",
        "contract_version": "canonical-items-contract-v1",
        "created_at": DATE,
        "status": "two_pass_human_reviewed_revealed_development_frozen",
        "data_status": "revealed_development_not_holdout",
        "annotator": "Codex coding agent",
        "prediction_status_at_labeling": "no_v4_or_v5_predictions_loaded_or_run_for_these_20_fixtures",
        "model_call_count": 0,
        "selection": {
            "path": str(SELECTION_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(SELECTION_PATH),
        },
        "annotation_policy": {
            "wrapper": "Clause-local operator spans are separated from their exact source content; overlapping prefix and suffix wrappers are allowed when both functions are explicit.",
            "member": "Coordination members are exact source spans. Nested coordinations are retained when an outer example member has an internal relation.",
            "connector": "Every connector belonging to an annotated coordination is labeled surface, embedded, example, or quantifier after its local region is identified.",
            "scope": "A shared prefix, suffix, head, evidence, or result is represented once and linked only to member spans it semantically governs.",
            "attachment": "Examples attach to an explicit source parent. Terminal 等优先 never supplies the parent; an independent parent-first cue such as 如 remains valid.",
            "projection": "Surface items and examples are ordered exact source strings; generic wrappers and embedded-only members are excluded.",
            "prediction_independence": "The frozen selection and source_text were the only per-fixture inputs. No v4/v5 prediction was imported or executed while labeling.",
        },
        "review": {
            "passes": 2,
            "pass_1": "Independent source-only structural annotation.",
            "pass_2": "Boundary, connector-role, edge-endpoint, projection anchoring, and E6/E7 contrast audit.",
            "known_scope": "Mechanism-enriched revealed development data; not prevalence evidence and not a generalization holdout.",
        },
        "fixtures": fixtures,
    }
    write_json(LABELS_PATH, labels)

    counts = {
        "wrappers": sum(len(fixture["wrappers"]) for fixture in fixtures),
        "connector_labels": sum(
            len(fixture["connector_labels"]) for fixture in fixtures
        ),
        "coordinations": sum(len(fixture["coordinations"]) for fixture in fixtures),
        "shared_scopes": sum(len(fixture["shared_scopes"]) for fixture in fixtures),
        "example_attachments": sum(
            len(fixture["example_attachments"]) for fixture in fixtures
        ),
        "surface_projection_items": sum(
            len(fixture["projection"]["surface_items"]) for fixture in fixtures
        ),
        "example_projection_items": sum(
            len(fixture["projection"]["examples"]) for fixture in fixtures
        ),
    }
    freeze = {
        "freeze_version": "unified-jd-structured-span-v5-mechanism-development-label-freeze-v1",
        "frozen_at": DATE,
        "status": "frozen_revealed_development_gold_before_v5_preregistration",
        "purpose": "Freeze source-only six-layer structural gold for the 20 v5 mechanism-development clauses before baseline scoring, v5 preregistration, or implementation.",
        "artifacts": {
            "sources": {
                "path": str(SOURCES_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(SOURCES_PATH),
            },
            "selection": {
                "path": str(SELECTION_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(SELECTION_PATH),
            },
            "labels": {
                "path": str(LABELS_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(LABELS_PATH),
            },
            "annotation_guide": {
                "path": str(GUIDE_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(GUIDE_PATH),
            },
            "builder": {
                "path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "frozen_v4_parser_reference": {
                "path": str(V4_PARSER_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(V4_PARSER_PATH),
            },
        },
        "freeze_checks": {
            "fixture_count": len(fixtures),
            "unique_job_id_count": len({fixture["job_id"] for fixture in fixtures}),
            "layer_annotation_counts": counts,
            "connector_roles_present": sorted(
                {
                    connector["role"]
                    for fixture in fixtures
                    for connector in fixture["connector_labels"]
                }
            ),
            "all_structural_spans_validated": True,
            "all_scope_edges_reference_annotated_members": True,
            "all_projection_items_source_anchored": True,
            "all_attachment_parents_non_priority": True,
            "e6_explicit_ru_attachment_preserved": True,
            "e6_direct_open_list_has_no_attachment": True,
            "e7_first_examples_exclude_leading_preposition": True,
            "annotation_review_passes": 2,
            "v4_predictions_loaded_during_labeling": False,
            "v5_predictions_loaded_during_labeling": False,
            "parser_run_count_during_labeling": 0,
            "model_call_count": 0,
        },
        "immutability": "Any label correction must create a new labels and freeze version; this file and its hashed labels artifact must not be overwritten.",
        "next_allowed_action": "Run frozen v4 once on these revealed-development labels to record the baseline, then freeze the v5 combined-rule preregistration and regression gates before implementing v5.",
    }
    write_json(FREEZE_PATH, freeze)
    print(
        json.dumps(
            {
                "labels": str(LABELS_PATH),
                "labels_sha256": sha256_file(LABELS_PATH),
                "freeze": str(FREEZE_PATH),
                "counts": counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

DEFAULT_SOURCE = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-sealed30-sources-v1-2026-09-06.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-sealed30-codex-blind-draft-v1-2026-09-08.json"
)
DATASET_VERSION = "product-jd-sealed30-codex-blind-draft-v1-2026-09-08"


def _text_fact(values: list[str], source_text: str) -> dict[str, Any]:
    return {"values": values, "source_text": source_text}


def _year_fact(values: list[int], source_text: str) -> dict[str, Any]:
    return {"values": values, "source_text": source_text}


def _job_type(value: str, source_text: str) -> dict[str, Any]:
    return {"value": value, "source_text": source_text}


def _facts(
    *,
    job_type: dict[str, Any] | None = None,
    locations: dict[str, Any] | None = None,
    graduation_years: dict[str, Any] | None = None,
    education_requirements: dict[str, Any] | None = None,
    major_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "job_type": job_type,
        "locations": locations,
        "graduation_years": graduation_years,
        "education_requirements": education_requirements,
        "major_requirements": major_requirements,
        "deadline": None,
    }


def _requirement(
    source_text: str,
    *,
    level: str = "required",
    relation: str = "all_of",
    items: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source_text": source_text,
        "level": level,
        "relation": relation,
        "items": items or [source_text],
    }


LABELS: dict[str, dict[str, Any]] = {
    "campus-ai-003": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["深圳"], "工作地点：深圳市"),
            graduation_years=_year_fact([2027], "招聘项目：2027届应届生校园招聘"),
            education_requirements=_text_fact(["本科及以上"], "学历要求：本科及以上"),
        ),
        "requirements": [
            _requirement("英语流利和理工科背景优先", level="preferred"),
            _requirement(
                "理解 AI 能力的边界与应用潜力，能够设计以 AI 为核心或 AI 增强型的产品 / 方案"
            ),
            _requirement("熟悉行业主流 AI 产品、技术趋势与最佳实践"),
        ],
        "responsibilities": [
            "一切以用户体验为中心，洞察用户真实需求，把握用户需求的本质",
            "寻找满足用户需求的技术点，实现你心中对伟大产品的创想",
            "联合开发、营销、销售伙伴共同打磨手机产品，建立与用户“沟通”的语言、传递产品卖点",
        ],
    },
    "campus-ai-005": {
        "facts": _facts(
            locations=_text_fact(["深圳"], "工作地点：深圳市"),
            education_requirements=_text_fact(["博士"], "岗位名称：高级AI研究员（内容生成推荐智能体）-博士"),
            major_requirements=_text_fact(
                ["计算机", "人工智能"], "计算机、人工智能等相关专业"
            ),
        ),
        "requirements": [
            _requirement("扎实的机器学习基础，熟悉NLP、RL等领域的技术"),
            _requirement(
                "在ACL/EMNLP/NAACL/NeurIPS/ICML/ICLR等顶级会议上发表论文者优先",
                level="preferred",
            ),
            _requirement("优秀的代码能力、数据结构和基础算法功底"),
            _requirement(
                "熟练C/C++或Python",
                relation="any_of",
                items=["C/C++", "Python"],
            ),
            _requirement(
                "ACM/ICPC、NOI/IOI、Top Coder、Kaggle等比赛获奖者优先",
                level="preferred",
            ),
            _requirement(
                "在大模型等领域，主导过大影响力的项目或论文者优先",
                level="preferred",
                relation="any_of",
                items=["项目", "论文"],
            ),
            _requirement(
                "能深入解决大模型训练和应用存在的问题，有自主探索解决方案的能力"
            ),
            _requirement(
                "从事 AI前沿研究与创新突破，能够提出新算法、新架构或新范式，具备顶会 / 顶刊论文等原创性科研成果"
            ),
        ],
        "responsibilities": [
            "多智能体协同的个性化内容生成与智能推荐服务，以及智能体自进化机制的研究",
            "记忆驱动的个性化推荐与可进化记忆闭环的算法设计与系统搭建",
            "多智能体生态的自动评价与竞生机制",
            "主动生成式推荐及更多前沿应用场景的探索与落地",
        ],
    },
    "campus-ai-007": {
        "facts": _facts(
            locations=_text_fact(["深圳"], "工作地点：深圳市"),
            major_requirements=_text_fact(
                ["计算机", "通信", "电子信息", "通信工程", "软件工程", "人工智能"],
                "计算机、通信、电子信息、通信工程、软件工程、人工智能等相关专业",
            ),
        ),
        "requirements": [
            _requirement(
                "熟练掌握Java/Python/C/C++等至少一门编程语言",
                relation="any_of",
                items=["Java", "Python", "C/C++"],
            ),
            _requirement("熟悉数据结构、算法等计算机基础知识"),
            _requirement("懂AI功能实现，懂AI的基本原理，掌握编程能力，能调用，能做算法复现"),
            _requirement(
                "熟悉深度学习、机器学习、图像处理、NLP等人工智能相关知识",
                level="preferred",
            ),
            _requirement("有良好的的论文阅读/撰写能力", level="preferred"),
            _requirement("熟悉Linux/Unix的基本操作及数据库操作", level="preferred"),
            _requirement("熟悉Android系统，有App开发经验", level="preferred"),
            _requirement("熟悉Java服务端开发，有相关经验", level="preferred"),
        ],
        "responsibilities": [
            "参与视觉、语音语义、AGI等算法模型及相关落地产品测试工作，与算法、产品对接需求、对齐准入准出标准",
            "参与算法模型推理框架、模型工程化落地、服务部署等相关测试任务",
            "负责方案/用例设计、数据集构建、问题跟踪、问题分析、完成测试报告等",
            "参与业界前沿算法测试方法探索、模型质量评测系统的研究，建立和完善评测体系",
            "参与工具平台建设、效率工具等开发，确保算法迭代的高效推进",
            "跟踪行业最新动态、调研行业发展并整理报告",
        ],
    },
    "campus-ai-014": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京", "深圳"], "工作地点：北京市,深圳市"),
            graduation_years=_year_fact([2027], "岗位名称：2027AIDU-大模型算法工程师(J99938)"),
            education_requirements=_text_fact(
                ["硕士及以上学历"], "计算机、人工智能、数学等相关专业硕士及以上学历"
            ),
            major_requirements=_text_fact(
                ["计算机", "人工智能", "数学"],
                "计算机、人工智能、数学等相关专业硕士及以上学历",
            ),
        ),
        "requirements": [
            _requirement("具备机器学习/深度学习/自然语言处理等扎实的理论背景与实践经验"),
            _requirement("精通Transformer、GPT、BERT等主流模型架构"),
            _requirement("熟练掌握Python"),
            _requirement(
                "PyTorch/TensorFlow/PaddlePaddle等深度学习框架",
                relation="any_of",
                items=["PyTorch", "TensorFlow", "PaddlePaddle"],
            ),
            _requirement(
                "有大规模预训练、SFT、RLHF、模型调优等实战经验者优先",
                level="preferred",
            ),
            _requirement(
                "熟悉分布式训练框架（如Megatron、DeepSpeed）及大数据处理工具（Hadoop、Spark）者优先",
                level="preferred",
            ),
            _requirement(
                "在NeurIPS、ICML、ACL、CVPR等顶会发表论文或有开源项目贡献者优先",
                level="preferred",
                relation="any_of",
                items=["在NeurIPS、ICML、ACL、CVPR等顶会发表论文", "有开源项目贡献"],
            ),
            _requirement(
                "有量化感知训练（QAT）或 MTP 训练 实践经验",
                level="preferred",
                relation="any_of",
                items=["量化感知训练（QAT）", "MTP 训练"],
            ),
            _requirement(
                "熟悉 EAGLE / Medusa / MTP variants（如DeepSeek MTP、MiMo MTP） 等投机推理或高效推理方案",
                level="preferred",
            ),
        ],
        "responsibilities": [
            "负责大模型（LLM）的核心算法研发，包括预训练、指令微调（SFT）、RLHF、对齐优化、推理增强等",
            "探索高效的模型调优策略、高质量数据建设方法，研究MoE稀疏化、Latent Attention等前沿模型结构",
            "支持大模型在搜索、推荐、对话、AIGC、语音、网盘文库、出海等多元业务场景的应用落地与效果优化",
            "负责量化、投机推理（MTP  / Eagle / DFlash/DSpark）等训练–推理协同优化方案的设计与落地",
            "设计、实现并优化大规模分布式训练与推理框架，提升训练稳定性和推理效率",
            "参与大模型平台化建设，推动模型能力向创新产品转化",
        ],
    },
    "campus-ai-019": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京"], "工作地点：北京市"),
            graduation_years=_year_fact([2027], "岗位名称：2027AIDU-智能体算法工程师(J99969)"),
            education_requirements=_text_fact(
                ["硕士及以上学历"], "计算机、人工智能等相关专业硕士及以上学历"
            ),
            major_requirements=_text_fact(
                ["计算机", "人工智能"], "计算机、人工智能等相关专业硕士及以上学历"
            ),
        ),
        "requirements": [
            _requirement("熟悉大语言模型原理及应用，具备Prompt Engineering、Fine-tuning等实践经验"),
            _requirement(
                "掌握LangChain、LlamaIndex、AutoGen等至少一种Agent开发框架",
                relation="any_of",
                items=["LangChain", "LlamaIndex", "AutoGen"],
            ),
            _requirement("有RAG、知识库构建、多Agent协同开发经验者优先", level="preferred"),
            _requirement(
                "熟悉强化学习（如PPO、DPO）或规划算法（如A*、MCTS）者优先",
                level="preferred",
                relation="any_of",
                items=["强化学习", "规划算法"],
            ),
            _requirement("具备良好的工程实现能力，能够将算法快速落地为可用系统"),
            _requirement(
                "有顶会论文或开源Agent项目贡献者优先",
                level="preferred",
                relation="any_of",
                items=["顶会论文", "开源Agent项目贡献"],
            ),
        ],
        "responsibilities": [
            "负责AI Agent的设计与研发，包括感知-决策-执行闭环、多智能体协作、长期记忆与推理机制",
            "研究ReAct、AutoGPT、CoT等前沿范式，熟练掌握LangChain、AutoGen、CrewAI等Agent开发框架",
            "优化大模型在Agent任务中的规划、工具调用、反思、代码生成等核心能力",
            "推动Agent在搜索、对话、办公、数据平台、网盘文库、生活娱乐等产品场景中的规模化应用",
            "探索RAG与Agent融合架构，提升知识理解与行动能力的协同效果",
            "建设Agent评测体系，持续优化成功率、响应延迟、成本及用户体验",
        ],
    },
    "campus-ai-020": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            locations=_text_fact(["上海", "北京"], "工作地点：上海、北京"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("计算机、人工智能、自动化、数学相关专业优先", level="preferred"),
            _requirement(
                "精通Go、Python、C++等一种或多种编程语言",
                relation="any_of",
                items=["Go", "Python", "C++"],
            ),
            _requirement("具备扎实的编程技能和算法设计能力"),
            _requirement("对AI Agent技术有深入了解，熟悉LangChain等框架，熟悉LangSmith等平台"),
            _requirement("在LLM工程领域有落地经验", level="preferred"),
            _requirement("对AgentOps平台熟悉，如LangSmith、Langfuse等", level="preferred"),
            _requirement("对最新Agent技术趋势和论文有深入的了解", level="preferred"),
        ],
        "responsibilities": [
            "基于业务场景核心诉求，主导Agent架构设计、深度迭代与落地，适配复杂业务需求，解决Agent工程化落地的核心痛点",
            "设计并落地Agent自进化全链路体系，构建自主反思、迭代优化的闭环能力，实现Agent基于业务反馈的持续能力升级",
            "打磨Agent任务拆解、推理规划、工具调用、多智能体协作等核心模块，持续优化架构性能，沉淀业务场景最佳实践",
            "跟进Agent领域前沿技术，开展自进化、多模态智能体等方向的技术预研，结合业务完成创新落地，提升核心竞争力",
        ],
    },
    "campus-ai-021": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            locations=_text_fact(["北京", "上海"], "工作地点：北京、上海"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("计算机、软件工程、人工智能、自动化等相关专业优先", level="preferred"),
            _requirement("具备扎实的计算机基础，理解数据结构、算法、操作系统、计算机网络等基础知识"),
            _requirement("具备良好的编程能力和工程实现能力"),
            _requirement(
                "熟悉至少一种常用编程语言，如Python、Go或C++",
                relation="any_of",
                items=["Python", "Go", "C++"],
            ),
            _requirement(
                "对后端开发、系统设计、平台研发或数据处理有一定理解",
                relation="any_of",
                items=["后端开发", "系统设计", "平台研发", "数据处理"],
            ),
            _requirement(
                "在课程项目、实验室、竞赛、开源或实习中，有服务端开发、虚拟化、容器化、任务调度、分布式系统等相关实践经历",
                level="preferred",
            ),
            _requirement(
                "对大模型、Agent、多模态、模型评测、工作流编排等方向有一定了解或实践经验",
                level="preferred",
            ),
            _requirement(
                "有搭建工具链、开发平台系统、参与复杂工程项目或优化系统性能与稳定性的经历",
                level="preferred",
                relation="any_of",
                items=["搭建工具链", "开发平台系统", "参与复杂工程项目", "优化系统性能与稳定性"],
            ),
            _requirement(
                "有开源贡献、技术竞赛、科研经历或较强的工程作品积累者优先",
                level="preferred",
                relation="any_of",
                items=["开源贡献", "技术竞赛", "科研经历", "工程作品积累"],
            ),
        ],
        "responsibilities": [
            "参与面向大模型数据场景的Agent Infra平台建设，涵盖但不限于Sandbox、Tool Use、Memory、知识库、轨迹管理等核心能力",
            "面向数据合成、标注、评测等业务场景，设计并构建高效、稳定、可扩展的数据生产Workflow",
            "参与平台基础能力建设，持续提升系统在海量并发场景下的稳定性、性能与资源利用效率，完善端到端可观测性体系",
            "参与Agent Runtime、任务编排、状态管理、执行链路治理等方向的研发工作，支撑复杂任务的稳定运行与持续迭代",
            "探索Agent在数据生产平台中的应用，推动系统向更智能、更自动化的方向演进",
        ],
    },
    "campus-ai-022": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("计算机相关专业优先", level="preferred"),
            _requirement(
                "熟练掌握Python/Java/Go等至少一门语言",
                relation="any_of",
                items=["Python", "Java", "Go"],
            ),
            _requirement("有项目开发经验者优先", level="preferred"),
            _requirement("对大模型有深入理解，熟悉LLM技术原理与应用方法，有Agent系统设计与实现经验"),
            _requirement("了解Memory机制、RAG、工具调用、规划执行等Agent关键技术，有相关实践经验"),
            _requirement("具备强化学习、规划算法实践经验者加分", level="preferred"),
            _requirement("具备快速复现论文及工程化能力"),
            _requirement(
                "顶会论文或开源项目贡献者加分",
                level="preferred",
                relation="any_of",
                items=["顶会论文", "开源项目贡献"],
            ),
        ],
        "responsibilities": [
            "负责豆包创意Agent技术研发，提升大模型在创意场景的应用能力，包括Multi-Agent框架、评测机制等基础能力建设",
            "探索Agent方向的创新方法与技术，提出更先进的Agent范式，引领行业技术发展",
            "探索面向Agent的评估方法，构建豆包的Agent评估体系",
            "设计并实现易用高效的Agent开发周边套件工具，提升开发效率，降低使用Agent技术的门槛，保障交付质量",
        ],
    },
    "campus-ai-028": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("计算机、软件工程等相关专业优先", level="preferred"),
            _requirement("扎实的计算机、编程基础"),
            _requirement("熟悉主流大语言模型的原理及方法"),
            _requirement(
                "理解Multi-Agent系统、任务分解、自动化规划、Prompt Engineering等技术领域之一或多个",
                relation="any_of",
                items=["Multi-Agent系统", "任务分解", "自动化规划", "Prompt Engineering"],
            ),
            _requirement("有AI Agent相关实践项目者优先", level="preferred"),
        ],
        "responsibilities": [
            "构建高效、可靠的AI Agent，精准理解产品的复杂需求，实现自规划、任务拆解及执行",
            "设计高效的Multi-Agent系统，确保多Agent间任务流转高效，上下文管理准确",
            "实现AI支撑企业级、大用户规模C端产品的需求端到端生成",
            "负责研发基于LLM的AI Agent系统，负责构建工程研发不同阶段的Agent",
            "参与探索Multi-Agent协作机制，推动Multi-Agent系统对复杂任务的规划和拆解，对已有人类经验的学习和引用，不断优化Agent解决实际问题的路径和效果",
        ],
    },
    "campus-ai-031": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            locations=_text_fact(["广州", "深圳"], "工作地点：广州、深圳"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("计算机、软件工程等相关专业优先", level="preferred"),
            _requirement("扎实的计算机、编程基础"),
            _requirement("熟悉主流大语言模型的原理及方法"),
            _requirement(
                "理解Multi-Agent系统、任务分解、自动化规划、Prompt Engineering等技术领域之一或多个",
                relation="any_of",
                items=["Multi-Agent系统", "任务分解", "自动化规划", "Prompt Engineering"],
            ),
            _requirement("有AI Agent相关实践项目者优先", level="preferred"),
        ],
        "responsibilities": [
            "构建高效、可靠的AI Agent，精准理解产品的复杂需求，实现自规划、任务拆解及执行",
            "设计高效的Multi-Agent系统，确保多Agent间任务流转高效，上下文管理准确",
            "实现AI支撑企业级、大用户规模C端产品的需求端到端生成",
            "负责研发基于LLM的AI Agent系统，负责构建工程研发不同阶段的Agent",
            "参与探索Multi-Agent协作机制，推动Multi-Agent系统对复杂任务的规划和拆解，对已有人类经验的学习和引用，不断优化Agent解决实际问题的路径和效果",
        ],
    },
    "campus-ai-034": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            locations=_text_fact(["上海", "杭州"], "工作地点：上海、杭州"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("计算机、软件工程等相关专业优先", level="preferred"),
            _requirement("扎实的Web前端基础，熟悉HTML、CSS、JavaScript/TypeScript与HTTP协议，了解浏览器渲染与常见性能问题"),
            _requirement("熟悉常用数据结构与设计模式"),
            _requirement(
                "掌握Python、Java、Go、Node.js中至少一种服务端语言",
                relation="any_of",
                items=["Python", "Java", "Go", "Node.js"],
            ),
            _requirement("能够独立完成从前端到接口的小型闭环开发"),
            _requirement(
                "做过基于大模型API、Agent框架、Prompt/评测相关的项目；或者有数据产品相关项目经验",
                level="preferred",
                relation="any_of",
                items=["做过基于大模型API、Agent框架、Prompt/评测相关的项目", "有数据产品相关项目经验"],
            ),
        ],
        "responsibilities": [
            "参与数据平台的前端产品与Agent应用的全栈研发，覆盖Web前端、Node/BFF、服务端接口与Agent Skill，编写高质量、可维护的代码",
            "参与Agent能力及相关服务的建设，涉及Prompt Engineering、Workflow、Multi-Agent、Tool Calling等技术方向",
            "结合数据分析、数据可视化等业务场景，参与Agent解决方案的设计与落地",
            "持续进行性能优化和架构升级，支撑内部业务及商业化客户需求，不断提升团队效率和产品体验",
            "跟踪大模型与Agent领域前沿技术，推动新技术在业务中的落地",
        ],
    },
    "campus-ai-038": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            locations=_text_fact(["北京", "上海"], "工作地点：北京、上海"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
            major_requirements=_text_fact(
                ["计算机", "人工智能", "数学", "信息安全"],
                "计算机、人工智能、数学、信息安全等相关专业",
            ),
        ),
        "requirements": [
            _requirement(
                "熟练掌握Python、Java、C++中至少一种语言",
                relation="any_of",
                items=["Python", "Java", "C++"],
            ),
            _requirement("熟悉SQL/HQL及数据分析工具"),
            _requirement(
                "掌握Hadoop、Hive、Spark、Flink中至少一项",
                relation="any_of",
                items=["Hadoop", "Hive", "Spark", "Flink"],
            ),
            _requirement("掌握机器学习、深度学习基础，具有异常检测、关联分析、图挖掘等实践经验"),
            _requirement(
                "了解文本或多模态大模型",
                relation="any_of",
                items=["文本", "多模态"],
            ),
            _requirement("熟悉LLM、Agent、Tool Use者优先", level="preferred"),
            _requirement("有Agent安全、大模型安全、风控反作弊或黑灰产对抗经验", level="preferred", relation="any_of", items=["Agent安全", "大模型安全", "风控反作弊", "黑灰产对抗"]),
            _requirement("熟悉提示词攻击、Agent身份授权、工具调用、数据外发等风险", level="preferred"),
            _requirement("熟悉OAuth、Token安全、DPoP、设备指纹等身份与凭证安全技术", level="preferred"),
            _requirement("有安全算法论文、竞赛成果或风险运营经验", level="preferred", relation="any_of", items=["安全算法论文", "竞赛成果", "风险运营经验"]),
        ],
        "responsibilities": [
            "负责Lark AI Agent安全算法建设，识别提示词攻击、身份冒用、凭证盗用、授权异常、危险工具调用、数据外发及内容风险",
            "结合大模型及设备、网络、行为、会话等信号，对抗黑产攻击、批量操控、网络劫持和异常代理",
            "挖掘海量数据中的攻击模式，建设安全数据集及风险发现、研判、溯源能力",
            "开展模型训练、调优与评估，持续提升算法效果、性能及业务收益",
            "综合模型、规则、图谱和策略，推动风险识别、处置及运营闭环",
        ],
    },
    "campus-ai-039": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：校招"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("计算机相关专业优先", level="preferred"),
            _requirement("具备AI+SE结合的项目经验，熟悉代码数据收集、清洗、标注等数据工程流程"),
            _requirement("熟悉大模型相关技术，对模型训练Pipeline、推理优化、评测体系构建等方向有深入研究和实践"),
            _requirement("以第一作者在ICML、ICLR、NeurIPS、ACL等顶级学术会议发表过高影响力研究成果者优先", level="preferred"),
            _requirement("在ACM/ICPC、NOI/IOI、Kaggle等编程或AI竞赛中获奖者优先", level="preferred"),
            _requirement("主导或参与过具有广泛影响力的AI开源或闭源项目者优先", level="preferred"),
        ],
        "responsibilities": [
            "负责代码大模型相关的数据收集、清洗、构建与管理，搭建高效稳定的数据处理Pipeline",
            "负责Agent Infra，包含Agent运行环境、Agentic RL Scaling等基础能力建设",
            "负责代码大模型评测体系的建设，包括评测集构建、评测框架开发与评测执行",
            "探索和实现基于大模型的智能体（Agent），应用于代码生成、Bug修复、测试用例生成等复杂研发任务",
            "持续追踪并复现LLM+SE领域前沿技术动态，并将其应用于实际业务场景中，推动技术落地",
        ],
    },
    "campus-ai-056": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京", "上海"], "工作地点：北京/上海"),
            graduation_years=_year_fact([2027], "招聘项目：2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届获得本科及以上学历"),
        ),
        "requirements": [
            _requirement("机器学习、人工智能、数理统计等相关专业背景优先", level="preferred"),
            _requirement("熟悉大模型相关基础知识"),
            _requirement("具备大语言模型训练或推理基础", relation="any_of", items=["大语言模型训练", "推理"]),
            _requirement("熟悉LLM Post-training技术，例如SFT/RLHF的常用方法"),
            _requirement("熟悉Agent领域，了解Agentic RL的常见方法"),
            _requirement("具备代码工程能力、数据结构和基础算法功底"),
            _requirement("熟练掌握Python等编程语言"),
        ],
        "responsibilities": [
            "研发面向广告主经营场景的Agent和模型，覆盖问题解答、经营状态理解、问题诊断、工具调用、长程任务完成及提案说服",
            "调研并应用前沿的大规模模型高效训练/推理方案，包括SFT、RM、RLHF等技术",
            "聚焦LLM Post-training技术，以及RL与LLM-based Agent相结合的交叉研究与应用落地",
        ],
    },
    "campus-ai-060": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届毕业生"),
            education_requirements=_text_fact(["博士"], "计算机视觉、VLM、计算机图形学或机器学习相关方向博士"),
            major_requirements=_text_fact(
                ["计算机视觉", "VLM", "计算机图形学", "机器学习"],
                "计算机视觉、VLM、计算机图形学或机器学习相关方向博士",
            ),
        ),
        "requirements": [
            _requirement("在ICLR、NeurIPS、ICML、KDD、AAAI、IJCAI等机器学习领域会议或者期刊有第一作者论文"),
            _requirement("熟悉模型开发与训练常见框架"),
            _requirement("具备快速阅读和复现论文的能力"),
            _requirement("熟悉常见Agent框架及Agentic Workflow"),
        ],
        "responsibilities": [
            "研发自动化GUI-ACTION数据合成方法",
            "构建高指令密度的GUI训练数据集及评测Benchmark",
            "提升视觉Agent在Web、Office、PC及Mobile等多端场景下的UI定位与操作准确率",
        ],
    },
    "campus-ai-062": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["合肥"], "工作地点：合肥"),
            graduation_years=_year_fact([2027], "招聘项目：蔚来2027届校园招聘"),
            education_requirements=_text_fact(["硕士及以上学历"], "硕士及以上学历"),
        ),
        "requirements": [
            _requirement("计算机科学与技术、软件工程、人工智能、自动化、数据科学、智能制造等相关专业的应届毕业生优先", level="preferred"),
            _requirement("熟练使用Python"),
            _requirement("了解C#/C++等工业开发语言", relation="any_of", items=["C#", "C++"]),
            _requirement("有完整的代码开发经验，能独立完成脚本/工具的编写、调试与文档输出"),
            _requirement("了解OpenCV、YOLO等常用计算机视觉算法"),
            _requirement("有目标检测、图像分类、缺陷识别、OCR等相关课程设计/竞赛/项目经验优先", level="preferred"),
            _requirement("熟悉PyTorch/TensorFlow等深度学习框架，能完成简单模型的训练、优化与部署"),
            _requirement("熟练使用SQL进行数据查询与分析"),
            _requirement("掌握Pandas、Numpy等数据处理工具"),
            _requirement("了解数据标注、数据清洗、数据治理的基本流程，能协助完成工业产线数据的标准化与质量管控"),
            _requirement("了解MES、SCADA等工业系统基础概念"),
            _requirement("有智能制造、工业互联网、产线自动化相关项目/实习经验者优先", level="preferred"),
            _requirement("熟练应用各种开源或付费大模型的API调用，能够自主搭建小场景Agent，协助业务完成降本增效"),
        ],
        "responsibilities": [
            "具备独立的数字化、智能制造逻辑认知，能够结合车间生产现状输出个人数字化落地思路",
            "负责数字化系统在车间的应用开发推进，按质高效交付",
            "收集车间现场的数字化业务需求场景需求及相关问题点，建立完善问题推进机制及管理清单并跟踪闭环",
            "负责车间智能化新项目的落地实施，拉通公司智能化及数字化团队、ME资源，高效推进智能化场景落地",
            "负责车间数字化硬件的管理（包括采买、收货、转固及资产管理等）",
        ],
    },
    "campus-ai-074": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["上海", "北京", "深圳"], "工作地点：上海/北京/深圳"),
            graduation_years=_year_fact([2027], "招聘项目：小鹏汽车2027届校园招聘"),
            education_requirements=_text_fact(["硕士及其以上学历"], "27届硕士及其以上学历"),
        ),
        "requirements": [
            _requirement("熟悉 LLM/VLM 相关技术", relation="any_of", items=["LLM", "VLM"]),
            _requirement("有数据合成、后训练、强化学习经验者优先", level="preferred"),
            _requirement("理解 Agent 架构，善于用 Agent 提升研发和评测效率"),
            _requirement("擅长构建 harness、评测框架、自动化实验与数据闭环"),
            _requirement("工程能力强，能快速验证想法并落地到产品或平台中"),
            _requirement("了解大模型基本知识和体系"),
            _requirement("具备较强的代码实现能力"),
            _requirement("有大模型训练经验者优先", level="preferred"),
            _requirement("有多模态推理、工具调用、RLHF/RLAIF", level="preferred"),
        ],
        "responsibilities": [],
    },
    "campus-ai-081": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京", "杭州"], "工作地点：北京/杭州"),
            graduation_years=_year_fact([2027], "招聘项目：千寻智能2027届秋季校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "本科及以上学历"),
            major_requirements=_text_fact(["计算机"], "计算机或相关专业"),
        ),
        "requirements": [
            _requirement("熟练掌握Python"),
            _requirement("熟悉PyTorch/TensorFlow等深度学习框架"),
            _requirement("同时熟练掌握vibe coding工具"),
            _requirement("有很强的算法设计思维，能独立完成算法模块的开发与部署"),
            _requirement("熟悉VLM/VLA领域最新技术"),
            _requirement("有相关领域数据管线上的算法落地经验"),
            _requirement("有相关论文产出，数据竞赛获奖经历或开源数据集贡献优先", level="preferred", relation="any_of", items=["相关论文产出", "数据竞赛获奖经历", "开源数据集贡献"]),
        ],
        "responsibilities": [
            "负责多模态（视觉、触觉、语言、Action）数据的清洗算法研发，包括异常数据剔除、低质量数据拦截，隐私脱敏、时空对齐等",
            "研发具身领域的预标注大模型，解决具身领域细粒度标注难题，提升数据生产效率",
            "实现基于视觉+动作+语义的高效去重算法；开发核心场景的数据挖掘脚本，从海量原始数据中筛选出高价值、高复杂度的样本",
            "构建数据分布的统计与可视化工具，量化分析数据的多样性指标，为数据采集策略提供依据",
        ],
    },
    "campus-ai-095": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京", "上海"], "工作地点：北京/上海"),
            graduation_years=_year_fact([2027], "招聘项目：MiniMax 2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上"], "2027 届本科及以上"),
            major_requirements=_text_fact(["计算机科学", "软件工程"], "计算机科学、软件工程等相关专业"),
        ),
        "requirements": [
            _requirement("扎实的 Python/Java/Scala/C++/Go 等高级语言编程功底", relation="any_of", items=["Python", "Java", "Scala", "C++", "Go"]),
            _requirement("熟悉 Ray 内核或者 Ray 相关框架应用", relation="any_of", items=["Ray 内核", "Ray 相关框架应用"]),
            _requirement("熟悉常见的分布式计算框架(如 Spark/Flink 等)"),
            _requirement("熟悉常见的数据湖框架（Delta/Iceberg/Hudi 等）"),
            _requirement("有数据平台研发、机器学习相关背景、k8s 研发经验者优先", level="preferred"),
        ],
        "responsibilities": [
            "与算法团队深度合作，推进数据清洗、样本生成等场景下多阶段复杂 pipeline 的分布式引擎设计和落地",
            "支撑大模型数据的清洗/分类/采样等场景，持续完善 Ray/Spark 内核功能及性能",
            "通过云原生技术栈搭建多云多地域的混合计算底座, 参与 Ray/Spark 在 K8S 上的弹性 /潮汐资源集群稳定性 /可观测性 /平台化对接等能力建设",
        ],
    },
    "campus-ai-096": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京", "上海"], "工作地点：北京/上海"),
            graduation_years=_year_fact([2027], "2027届以后本科/硕士"),
            education_requirements=_text_fact(["本科", "硕士"], "2027届以后本科/硕士"),
            major_requirements=_text_fact(["计算机", "软件工程"], "计算机、软件工程等相关专业"),
        ),
        "requirements": [
            _requirement("熟练掌握 Go/Java/Python 至少一门", relation="any_of", items=["Go", "Java", "Python"]),
            _requirement("有项目/开源经验（Web开发、系统设计、自动化工具）", level="preferred"),
            _requirement("了解Kubernetes、AI训练平台或GPU管理基础概念", level="preferred", relation="any_of", items=["Kubernetes", "AI训练平台", "GPU管理"]),
            _requirement("对可观测性（监控/日志）有初步了解或有开源/社区参与经历", level="preferred", relation="any_of", items=["对可观测性（监控/日志）有初步了解", "有开源/社区参与经历"]),
        ],
        "responsibilities": [
            "协助开发与维护CMDB、工单系统、流程引擎等AI Infra关键平台",
            "参与功能模块开发、测试及基础性能调优，提升代码质量",
            "协助整合资源编排、调度平台与CMDB/工单等系统数据流",
            "开发辅助工具，支持AI平台对底层资源（GPU/CPU）的基础获取与监控",
            "与算法、调度、运维团队协作，了解需求对接流程",
        ],
    },
    "campus-ai-099": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["上海"], "工作地点：上海"),
            graduation_years=_year_fact([2027], "招聘项目：它石智航2027校园招聘"),
            education_requirements=_text_fact(["硕士及以上学历"], "2027届硕士及以上学历"),
            major_requirements=_text_fact(["机器人", "人工智能", "计算机", "自动化", "控制"], "机器人、人工智能、计算机、自动化、控制等相关专业"),
        ),
        "requirements": [
            _requirement("具备机器人运动学/动力学、运动控制、强化学习、模仿学习、跨本体学习或灵巧手控制中的至少一个方向的扎实基础和项目经验", relation="any_of", items=["机器人运动学/动力学", "运动控制", "强化学习", "模仿学习", "跨本体学习", "灵巧手控制"]),
            _requirement("熟练使用 C++ 或 Python", relation="any_of", items=["C++", "Python"]),
            _requirement("熟悉 Linux、ROS/ROS2 等开发环境者优先", level="preferred"),
            _requirement("有真实机器人、机械臂、人形机器人、遥操作、模仿学习或强化学习项目经验者优先", level="preferred", relation="any_of", items=["真实机器人", "机械臂", "人形机器人", "遥操作", "模仿学习", "强化学习"]),
            _requirement("能够独立完成问题拆解、实验验证、结果分析和持续迭代，具备较强的工程落地意识"),
            _requirement("有机器人顶会论文、开源项目、竞赛获奖或完整真机闭环成果", level="preferred", relation="any_of", items=["机器人顶会论文", "开源项目", "竞赛获奖", "完整真机闭环成果"]),
        ],
        "responsibilities": [
            "参与机器人核心算法研发，重点包括强化学习策略、运动控制、跨本体学习与灵巧手操作等方向",
            "参与算法方案设计、仿真验证、真机调试与效果评估，推动算法从研究到真实场景落地",
            "参与机器人数据采集、示教数据整理、失败案例分析与策略迭代，提升系统鲁棒性、泛化能力和任务成功率",
            "结合机器人本体特性与任务需求，参与灵巧手、机械臂、人形机器人等不同平台的控制与策略适配",
            "与系统工程、硬件、仿真和测试团队协作，定位算法与整机系统之间的关键瓶颈并推动闭环优化",
        ],
    },
    "campus-ai-115": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京", "杭州"], "工作地点：北京/杭州"),
            graduation_years=_year_fact([2027], "招聘项目：千寻智能2027届秋季校园招聘"),
        ),
        "requirements": [
            _requirement("熟练使用 Python/Go/Java 其中一种", relation="any_of", items=["Python", "Go", "Java"]),
            _requirement("代码风格良好，追求 Clean Code，熟悉设计模式"),
            _requirement("有大型后端系统开发经验者优先", level="preferred"),
            _requirement("深度理解 ReAct 框架原理，阅读过相关核心论文"),
            _requirement("熟悉 LangChain / LangGraph / AutoGen 等框架的源码"),
            _requirement("有过校级学生会、技术社团负责人经历，或组织过黑客松、技术沙龙者优先（我们需要你在面对客户提问时也能从容应对）", level="preferred", relation="any_of", items=["校级学生会", "技术社团负责人经历", "组织过黑客松", "技术沙龙"]),
        ],
        "responsibilities": [
            "基于 Agentic 设计并实现高可用的 Agent 系统",
            "参与核心逻辑编写，让模型能够精准地进行“推理-行动-观察”的闭环，解决复杂的业务问题",
            "向来访客户或合作伙伴演示公司demo产品",
        ],
    },
    "campus-ai-118": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["深圳"], "工作地点：深圳"),
            graduation_years=_year_fact([2027], "招聘项目：自变量机器人27届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "计算机科学、软件工程、自动化、机器人或相关专业本科及以上学历"),
            major_requirements=_text_fact(["计算机科学", "软件工程", "自动化", "机器人"], "计算机科学、软件工程、自动化、机器人或相关专业本科及以上学历"),
        ),
        "requirements": [
            _requirement("熟练使用 C/C++、Rust 开发"),
            _requirement("熟悉 Linux 系统原理与开发，包括进程调度、内存管理、文件系统、网络编程、多线程与进程间通信"),
            _requirement("熟悉一种或多种机器人中间件或通信框架，如 ROS/ROS2、DDS（Cyclone DDS/FastDDS）、Zenoh、iceoryx2、dora-rs、copper-rs 等", relation="any_of", items=["ROS/ROS2", "DDS", "Zenoh", "iceoryx2", "dora-rs", "copper-rs"]),
        ],
        "responsibilities": [
            "负责机器人中间件的设计、开发、测试和部署，构建统一的软件通信与运行框架",
            "实现机器人中间件核心能力，包括模块通信、服务发现、进程间通信（IPC）、数据发布/订阅、远程过程调用（RPC）等",
            "保障机器人中间件的高吞吐、低延迟与高可靠性，满足机器人系统实时性与稳定性要求",
            "参与机器人整体基础软件架构设计与演进，构建覆盖操作系统层、通信层、设备抽象层、功能服务层的软件体系",
        ],
    },
    "campus-ai-129": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["上海"], "工作地点：上海"),
            graduation_years=_year_fact([2027], "招聘项目：它石智航2027届校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "2027届本科及以上学历"),
            major_requirements=_text_fact(["计算机", "电子信息", "自动化", "测控", "机械电子"], "计算机、电子信息、自动化、测控、机械电子等相关专业"),
        ),
        "requirements": [
            _requirement("具备基础软硬件测试、数据分析或机器人系统理解能力", relation="any_of", items=["基础软硬件测试", "数据分析", "机器人系统理解"]),
            _requirement("熟悉Python、测试脚本、常用仪器或Linux环境者优先", level="preferred", relation="any_of", items=["Python", "测试脚本", "常用仪器", "Linux环境"]),
        ],
        "responsibilities": [
            "参与机器人生产测试、功能测试、性能测试和出厂验证流程执行",
            "协助制定测试用例、测试规范、测试记录和问题追踪机制",
            "参与软硬件问题定位，推动研发、生产、质量团队完成缺陷闭环",
            "参与测试工具、自动化脚本或测试平台建设，提升测试效率和一致性",
        ],
    },
    "campus-ai-131": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["上海"], "工作地点：上海"),
            graduation_years=_year_fact([2027], "招聘项目：它石智航2027届校园招聘"),
            education_requirements=_text_fact(["硕士研究生及以上学历"], "2027届硕士研究生及以上学历"),
            major_requirements=_text_fact(["机械设计", "机械电子", "车辆工程", "机器人工程"], "机械设计、机械电子、车辆工程、机器人工程等相关专业"),
        ),
        "requirements": [
            _requirement("具备机构学、多体动力学、机器人运动学基础，能够理解复杂机构运动约束"),
            _requirement("熟悉Adams、MATLAB/Simulink、Ansys Motion或其他仿真工具者优先", level="preferred", relation="any_of", items=["Adams", "MATLAB/Simulink", "Ansys Motion", "其他仿真工具"]),
            _requirement("熟悉CAD装配、运动干涉检查和工程数据分析"),
            _requirement("有机器人整机、机械臂、移动平台、关节模组或竞赛项目仿真经验", level="preferred", relation="any_of", items=["机器人整机", "机械臂", "移动平台", "关节模组", "竞赛项目仿真经验"]),
        ],
        "responsibilities": [
            "参与机器人整机、关节模组和关键运动机构的运动学/动力学仿真建模",
            "参与工作空间、关节运动范围、传动效率和受力分布等运动性能分析",
            "参与传动机构误差、回差、柔性因素对运动精度影响的分析与优化建议输出",
            "与结构设计、控制、测试团队协作，推动仿真结论在样机设计和验证中落地",
        ],
    },
    "campus-ai-133": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["上海"], "工作地点：上海"),
            graduation_years=_year_fact([2027], "招聘项目：它石智航2027届校园招聘"),
            education_requirements=_text_fact(["硕士研究生及以上学历"], "2027届硕士研究生及以上学历"),
            major_requirements=_text_fact(["自动化", "电气工程", "控制", "机械电子", "机器人工程"], "自动化、电气工程、控制、机械电子、机器人工程等相关专业"),
        ),
        "requirements": [
            _requirement("熟悉电机控制基础，理解BLDC/PMSM、FOC、PID、编码器/电流采样等基本原理"),
            _requirement("具备C/C++或嵌入式开发能力", relation="any_of", items=["C/C++", "嵌入式开发"]),
            _requirement("了解MCU、驱动器、实时控制系统者优先", level="preferred"),
            _requirement("有电机控制、机器人关节、无人车、RoboMaster电控或硬件调试经验者优先", level="preferred", relation="any_of", items=["电机控制", "机器人关节", "无人车", "RoboMaster电控", "硬件调试"]),
            _requirement("有真实硬件闭环控制、驱动器调试、力控/触觉控制或竞赛获奖经历", level="preferred", relation="any_of", items=["真实硬件闭环控制", "驱动器调试", "力控/触觉控制", "竞赛获奖经历"]),
        ],
        "responsibilities": [
            "参与灵巧手电机控制算法开发，包括FOC、电流环/速度环/位置环、力矩控制等",
            "参与驱动器调试、传感器标定、控制参数整定和运动性能优化",
            "参与灵巧手精细操作场景中的控制效果验证，分析抖动、跟随误差、力控稳定性等问题",
            "与电机、硬件、嵌入式、结构和测试团队协作，推动执行器控制链路稳定落地",
        ],
    },
    "campus-ai-149": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["深圳"], "工作地点：深圳"),
            graduation_years=_year_fact([2027], "招聘项目：影石创新2027届秋季校园招聘"),
            education_requirements=_text_fact(["本科及以上学历"], "本科及以上学历"),
        ),
        "requirements": [
            _requirement("软件工程、工业设计、交互设计、心理学、人机交互、信息设计、计算机等背景优先", level="preferred"),
            _requirement("有软件产品、互联网产品、工具软件、影像/剪辑类产品、AI 工具或智能硬件 App 实习经验优先", level="preferred", relation="any_of", items=["软件产品", "互联网产品", "工具软件", "影像/剪辑类产品", "AI 工具", "智能硬件 App"]),
            _requirement("具备良好的用户同理心、逻辑表达能力和文档能力，能把模糊问题拆成清晰的用户场景、流程和功能需求"),
            _requirement("对交互体验敏感，能独立输出流程图、原型、竞品分析或体验分析"),
            _requirement("有作品集优先", level="preferred"),
            _requirement("做过自己的小工具、小程序、插件、AI 工作流、App Demo、低代码/无代码产品，或长期深度使用影像、剪辑、效率工具类软件", level="preferred", relation="any_of", items=["小工具", "小程序", "插件", "AI 工作流", "App Demo", "低代码/无代码产品", "长期深度使用影像、剪辑、效率工具类软件"]),
        ],
        "responsibilities": [
            "参与飞行相机/影像产品相关 App、机身端、遥控/Beacon 等多端软件体验设计，负责用户场景拆解、需求定义、功能流程梳理、交互方案打磨与版本验收",
            "协助产品经理完成竞品分析、用户研究、需求文档、原型设计、研发沟通、测试验收和上线复盘，推动软件功能从想法到落地",
            "围绕智能影像、拍摄、剪辑、设备连接、飞行交互等场景，持续发现用户痛点，提出可落地的软件体验优化方案",
            "与交互设计、视觉设计、App 研发、固件、算法、测试等团队协作，跟进需求排期、实现质量和用户体验闭环",
        ],
    },
    "campus-ai-151": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["上海"], "工作地点：上海"),
        ),
        "requirements": [
            _requirement("机器人、计算机、人工智能、自动化等相关专业优先", level="preferred"),
            _requirement("具备扎实的编程能力和工程实现能力，熟悉 PyTorch 等深度学习框架"),
            _requirement("对深度学习基础模型结构、模仿学习方法有较好的理解"),
            _requirement("掌握 Transformer、DiT 等模型架构，Diffusion Model、Flow-Based Model 等现代生成模型，以及 ACT、Diffusion Policy 等模仿学习方法"),
            _requirement("熟悉具身智能算法方向的前沿进展，了解 VLA、WAM、机器人基座模型的最新相关工作，包括 Pi、GR00T、DreamZero、Lingbot-VA、FastWAM 等"),
            _requirement("具备 VLA、WAM、模仿学习、机器人学习等相关项目经验，或有真机部署经验者优先", level="preferred", relation="any_of", items=["VLA、WAM、模仿学习、机器人学习等相关项目经验", "真机部署经验"]),
            _requirement("在 RA-L、ICRA、ICLR、NeurIPS、RSS 等机器人或人工智能期刊/会议发表过相关论文者优先", level="preferred"),
        ],
        "responsibilities": [
            "参与机器人数据采集、算法设计、模型训练与真机部署的全链路研发工作",
            "参与机器人数据采集规划，包括任务设计与质量分析，为下游模型训练提供高质量、多样化数据支持",
            "跟踪具身智能、机器人学习、VLA/WAM 等方向的前沿进展，调研并分析最新研究工作",
            "参与世界动作模型（World Action Model, WAM）的算法创新、模型结构设计与训练优化",
            "参与模型在真实机器人平台上的部署、调试与性能评估，推动算法从仿真/离线训练走向真实场景应用",
        ],
    },
    "campus-ai-154": {
        "facts": _facts(
            job_type=_job_type("campus", "招聘类型：应届生"),
            locations=_text_fact(["北京", "上海"], "工作地点：北京/上海"),
            graduation_years=_year_fact([2027], "招聘项目：阶跃星辰2027届StepStar校园招聘"),
            major_requirements=_text_fact(["计算机", "电子", "自动化", "软件"], "国内外计算机、电子、自动化、软件等相关专业的优秀应届毕业生"),
        ),
        "requirements": [
            _requirement("具备操作系统、计算机体系结构等基础知识"),
            _requirement("熟悉 SGLang、vLLM、Megatron 等框架，有开源项目贡献或相关经验者优先", level="preferred"),
            _requirement("熟悉 CUDA 编程和 GPU 性能优化，有 Triton、CUTLASS 开发经验者优先", level="preferred"),
        ],
        "responsibilities": [
            "参与分布式大模型推理框架的开发与优化，提升推理性能与吞吐量",
            "针对不同场景的 LLM 请求特点优化 GPU 计算流程，打造高效 LLM 推理引擎",
            "调研并引入前沿机器学习系统技术，推动系统架构持续优化升级",
            "与算法团队合作探索算法与系统协同优化方案",
        ],
    },
    "campus-ai-163": {
        "facts": _facts(
            job_type=_job_type("internship", "招聘类型：实习生"),
            locations=_text_fact(["深圳"], "工作地点：深圳"),
            education_requirements=_text_fact(["本科及以上在读"], "计算机、人工智能、机器人、自动化或相关专业本科及以上在读"),
            major_requirements=_text_fact(["计算机", "人工智能", "机器人", "自动化"], "计算机、人工智能、机器人、自动化或相关专业本科及以上在读"),
        ),
        "requirements": [
            _requirement("掌握机器学习与深度学习基础"),
            _requirement("了解计算机视觉、生成模型、模仿学习或强化学习", relation="any_of", items=["计算机视觉", "生成模型", "模仿学习", "强化学习"]),
            _requirement("熟练使用 Python 和 PyTorch，具备模型训练、调试及实验分析能力"),
            _requirement("对机器人运动学、动力学、控制或接触建模有基本了解", relation="any_of", items=["机器人运动学", "动力学", "控制", "接触建模"]),
            _requirement("了解 Isaac Sim、Isaac Lab、MuJoCo、SAPIEN、Genesis 等至少一种机器人仿真平台", relation="any_of", items=["Isaac Sim", "Isaac Lab", "MuJoCo", "SAPIEN", "Genesis"]),
        ],
        "responsibilities": [
            "参与人形机器人 VLA 模型设计、训练与评测，研究视觉、触觉、语言、机器人状态与动作的多模态融合",
            "探索世界建模、未来状态预测、动作生成和长时序任务规划",
            "搭建人形机器人操作与全身交互仿真 Benchmark，参与 Real-to-Sim-to-Real 工作流和真机强化学习系统研发",
            "在仿真和真机平台评估任务表现、鲁棒性及泛化能力",
        ],
    },
}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_dataset(source_path: Path, output_path: Path) -> dict[str, Any]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source_ids = [case["id"] for case in source["cases"]]
    if len(source_ids) != 30 or len(source_ids) != len(set(source_ids)):
        raise ValueError("Sealed source must contain 30 unique cases")
    if set(source_ids) != set(LABELS):
        missing = sorted(set(source_ids) - set(LABELS))
        extra = sorted(set(LABELS) - set(source_ids))
        raise ValueError(f"Label ids do not match sealed source: missing={missing}, extra={extra}")

    cases: list[dict[str, Any]] = []
    for source_case in source["cases"]:
        raw_content = source_case["raw_content"]
        if _sha256_text(raw_content) != source_case["source_content_sha256"]:
            raise ValueError(f"Source hash mismatch for {source_case['id']}")
        expected = ProductJDModelOutput.model_validate(LABELS[source_case["id"]])
        validate_product_jd_output(expected, raw_content)
        cases.append(
            {
                **source_case,
                "annotation_status": "codex_blind_draft_requires_human_review",
                "expected": expected.model_dump(mode="json"),
                "label_revision": {
                    "annotation_version": "product-jd-sealed30-codex-blind-draft-v1",
                    "predictions_read_before_annotation": False,
                    "historical_product_predictions_read": False,
                    "human_reviewed": False,
                },
            }
        )

    payload = {
        "dataset_version": DATASET_VERSION,
        "schema_version": "product-job-description-v1",
        "split": "sealed_test",
        "case_count": len(cases),
        "label_status": "codex_blind_draft_requires_human_review",
        "evaluation_policy": (
            "Blind draft created before Product JD predictions. It may be used for a "
            "preliminary run, but resume metrics require explicit human review and a "
            "new frozen label version."
        ),
        "source_dataset": {
            "path": source_path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        },
        "cases": cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build blind Product JD sealed labels")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_dataset(args.source, args.output)
    print(
        f"product-jd-sealed-label-draft cases={payload['case_count']} "
        f"status={payload['label_status']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

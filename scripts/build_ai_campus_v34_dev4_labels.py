from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.domain.core_skill_semantics import (
    CoreModelOutput,
    CoreSkillClause,
    compile_core_model_output,
)
from src.domain.skill_normalizer import skill_id_for
from src.services.core_jd_parser import CoreJobFields

REVIEW_OUTPUT_PATH = Path(
    "datasets/ai_campus_v34_dev4_labels_human_reviewed_v1_2026_09_03.json"
)
FROZEN_OUTPUT_PATH = Path("datasets/ai_campus_v34_dev4_label_freeze_v1_2026_09_03.json")
FROZEN_AT = "2026-09-03T09:45:05+08:00"


def clause(
    source_text: str,
    strength: str,
    skills: list[str],
    *,
    relation: str = "all_of",
    examples: list[str] | None = None,
    group_name: str | None = None,
    allow_other: bool = False,
    qualifier: str | None = None,
) -> dict[str, Any]:
    return {
        "source_text": source_text,
        "strength": strength,
        "relation": relation,
        "skills": skills,
        "examples": examples,
        "group_name": group_name,
        "allow_other": allow_other,
        "qualifier": qualifier,
    }


CASES: dict[str, dict[str, Any]] = {
    "external-dev-v34-001": {
        "company": "搜狐",
        "title": "【2027】AI算法研发工程师-【引力计划】人才专项",
        "source_url": "https://campus.sohu.com/jobs/2027-gravity-ai-algo-rd-engineer-2f6a47e0/",
        "owner_confirmation": {
            "status": "confirmed",
            "confirmed_at": "2026-09-03",
            "confirmed_items": ["A1", "A2", "A3", "A4", "A5"],
        },
        "job_type": "campus",
        "locations": ["北京"],
        "clauses": [
            clause(
                "计算机基础扎实，熟悉常见算法与数据结构，具备良好的编程能力",
                "required",
                ["计算机基础知识", "数据结构与算法", "编程能力"],
            ),
            clause(
                "熟悉 Java、Python、C++ 等至少一种编程语言",
                "required",
                ["Java", "Python", "C++"],
                relation="any_of",
                group_name="编程语言",
                allow_other=True,
            ),
            clause(
                "了解机器学习、深度学习相关基础知识，了解大语言模型（LLM）、Agent等相关技术",
                "mention",
                ["机器学习", "深度学习", "LLM", "Agent"],
            ),
            clause(
                "了解搜索、推荐系统、自然语言处理、计算机视觉、多模态等至少一个方向",
                "mention",
                ["搜索", "推荐系统", "NLP", "计算机视觉", "多模态"],
            ),
            clause(
                "有搜索、推荐、广告、NLP、CV、多模态等相关项目或科研经历",
                "preferred",
                ["搜索", "推荐系统", "广告", "NLP", "计算机视觉", "多模态"],
            ),
            clause(
                "有大模型、Agent、RAG等相关实践经验",
                "preferred",
                ["LLM", "Agent", "RAG"],
                qualifier="practical_experience",
            ),
            clause(
                "有开源项目贡献经历或技术博客输出习惯",
                "preferred",
                ["开源贡献"],
                qualifier="open_source_experience",
            ),
            clause(
                "参与Agent系统的设计与开发，推动Agent在搜索、推荐、视频理解等场景中的应用与落地",
                "mention",
                ["Agent系统研发", "搜索", "推荐系统", "视频理解"],
            ),
            clause(
                "参与搜狐视频搜索、推荐、广告及视频理解相关系统的研发与优化，持续提升用户体验和业务效果",
                "mention",
                ["视频搜索", "推荐系统", "广告", "视频理解"],
            ),
            clause(
                "跟踪大模型（LLM）、Agent、多模态等前沿技术，探索新技术在业务场景中的应用",
                "mention",
                ["LLM", "Agent", "多模态"],
            ),
            clause(
                "参与相关系统的架构设计、性能优化和工程建设，保障系统稳定高效运行",
                "mention",
                ["系统架构设计", "性能优化", "工程建设"],
            ),
        ],
        "manual_notes": (
            "‘了解……至少一个方向’受弱认知词支配，只作 mention，不建立必备 any_of；"
            "只有‘至少一种编程语言’建立开放 any_of。项目/科研、实践和开源贡献位于加分项，"
            "因此标为 preferred；竞赛经历、技术博客习惯、学历专业和软技能排除。"
        ),
    },
    "external-dev-v34-002": {
        "company": "摩尔线程",
        "title": "大模型推理优化工程师",
        "source_url": "https://mthreads.zhiye.com/campus/detail?jobAdId=e9c2216b-79c0-4c33-8687-147ad255e479",
        "owner_confirmation": {
            "status": "confirmed_with_revision",
            "confirmed_at": "2026-09-03",
            "confirmed_items": ["B1", "B2", "B3", "B4", "B5"],
            "revision": "B2/B3: C++ and Python form a closed any_of group",
        },
        "job_type": "campus",
        "locations": ["北京", "上海", "深圳", "杭州"],
        "manual_group_overrides": [
            {
                "source_text": "熟悉 C++/Python",
                "name": "编程语言",
                "any_of": ["C++", "Python"],
                "allow_other": False,
            }
        ],
        "clauses": [
            clause(
                "熟悉 C++/Python",
                "required",
                ["C++", "Python"],
                relation="any_of",
                group_name="编程语言",
            ),
            clause(
                "熟练使用 Linux 开发环境，具备扎实编程基础",
                "required",
                ["Linux", "编程基础"],
            ),
            clause(
                "了解 GPU 并行计算原理与 Transformer 大模型基础架构。",
                "mention",
                ["GPU并行计算", "Transformer", "LLM"],
            ),
            clause(
                "具备大模型推理、模型部署或性能优化相关认知与学习热情。",
                "mention",
                ["大模型推理", "模型部署", "性能优化"],
            ),
            clause(
                "负责各类大模型在自研 GPU 上的推理适配、性能调优与业务部署，解决高并发、长文本、多轮对话等场景的性能与稳定性瓶颈。",
                "mention",
                [
                    "LLM",
                    "GPU",
                    "推理适配",
                    "性能调优",
                    "模型部署",
                    "高并发",
                    "长文本",
                    "多轮对话",
                ],
            ),
            clause(
                "聚焦大模型推理全链路优化，落地分布式推理、量化、KV 缓存等核心策略，持续提升推理吞吐、降低推理时延。",
                "mention",
                [
                    "大模型推理",
                    "分布式推理",
                    "模型量化",
                    "KV-Cache",
                    "推理吞吐优化",
                    "推理时延优化",
                ],
            ),
            clause(
                "跟进 LLM、VLM 等前沿模型技术，完成新模型适配加速与推理能力迭代升级。",
                "mention",
                ["LLM", "VLM", "模型适配加速", "模型推理"],
            ),
            clause(
                "结合自研 GPU 架构特性，基于并行编程工具完成高性能推理算子开发与极致调优。",
                "mention",
                ["GPU架构", "并行编程", "推理算子开发", "性能调优"],
            ),
        ],
        "manual_notes": (
            "仓库所有者人工裁决本条‘熟悉 C++/Python’中的斜杠表达二选一，建立封闭 any_of；"
            "Linux 与编程基础仍为共同必备。该裁决只适用于本条，不把所有斜杠枚举自动改成 any_of。"
            "‘了解’和‘相关认知与学习热情’均只作 mention；无明确优先或加分技术项。"
        ),
    },
    "external-dev-v34-003": {
        "company": "摩尔线程",
        "title": "Agentic Infra 平台研发工程师",
        "source_url": "https://mthreads.zhiye.com/campus/detail?jobAdId=67d78507-7dbd-4c45-ade1-dfbb3488e30d",
        "owner_confirmation": {
            "status": "confirmed",
            "confirmed_at": "2026-09-03",
            "confirmed_items": ["C1", "C2", "C3", "C4", "C5", "C6"],
        },
        "job_type": "campus",
        "locations": ["北京", "杭州", "深圳"],
        "manual_group_overrides": [
            {
                "source_text": "精通 Go/Python/Java 任一后端语言",
                "name": "后端编程语言",
                "any_of": ["Go", "Python", "Java"],
                "allow_other": False,
            }
        ],
        "clauses": [
            clause(
                "具备 LLM Agent 落地实战经验，拥有代码智能助手、IDE AI 插件、研发提效平台完整落地案例。",
                "required",
                ["LLM Agent", "代码智能助手", "IDE AI插件", "研发提效平台"],
                qualifier="practical_experience",
            ),
            clause(
                "精通 Go/Python/Java 任一后端语言",
                "required",
                ["Go", "Python", "Java"],
                relation="any_of",
                group_name="后端编程语言",
            ),
            clause(
                "熟悉微服务、分布式队列、Redis、向量数据库（PgVector/Milvus）、K8S 容器调度。",
                "required",
                [
                    "微服务",
                    "分布式队列",
                    "Redis",
                    "向量数据库",
                    "Kubernetes",
                    "容器调度",
                ],
                examples=["PgVector", "Milvus"],
            ),
            clause(
                "拥有完整 AI Coding Agent 搭建经验",
                "required",
                ["AI Coding Agent"],
                qualifier="practical_experience",
            ),
            clause(
                "熟练 LangGraph/AutoGen/LlamaIndex 等 Agent 框架",
                "required",
                ["Agent框架"],
                examples=["LangGraph", "AutoGen", "LlamaIndex"],
            ),
            clause(
                "掌握 Function Calling、RAG、记忆调度、多智能体协同设计。",
                "required",
                ["Tool Calling", "RAG", "记忆调度", "多智能体协同设计"],
            ),
            clause(
                "具备代码模型强化学习落地经验",
                "required",
                ["代码模型强化学习"],
                qualifier="practical_experience",
            ),
            clause(
                "拥有代码沙箱、隔离执行环境、AI 输出安全风控架构设计经验。",
                "required",
                ["代码沙箱", "隔离执行环境", "AI输出安全风控架构设计"],
                qualifier="practical_experience",
            ),
            clause(
                "具备 VSCode/IDEA AI 插件、企业研发中台、CI/CD 智能自动化落地经验。",
                "required",
                ["IDE AI插件", "企业研发中台", "CI/CD智能自动化"],
                examples=["VSCode", "IDEA"],
                qualifier="practical_experience",
            ),
            clause(
                "熟悉 vLLM/SGLang 推理服务优化",
                "required",
                ["vLLM", "SGLang", "推理服务优化"],
            ),
            clause(
                "具备 GPU 算力调度、大模型性能调优经验。",
                "required",
                ["GPU算力调度", "大模型性能调优"],
                qualifier="practical_experience",
            ),
            clause(
                "负责基于公司 MUSA 统一架构实现 AI Coding Agent 平台整体系统架构设计，建设 MUSA 算子生成、长上下文治理、自我进化的完整 Agent 技术体系",
                "mention",
                [
                    "MUSA",
                    "AI Coding Agent平台",
                    "系统架构设计",
                    "MUSA算子生成",
                    "长上下文治理",
                    "Agent自我进化",
                ],
            ),
            clause(
                "搭建 Musa 编程的 Skills 技术体系，支持百万开发者基于 MUSA 快速构建 Musa App，并落地业务成果。",
                "mention",
                ["Skills技术体系", "MUSA", "Musa App"],
            ),
            clause(
                "搭建 Musa AI Coding Plan 套餐，支撑超长上下文、高并发、长程任务背景下的广大开发者并行使用场景",
                "mention",
                ["AI Coding Plan", "超长上下文", "高并发", "长程任务"],
            ),
        ],
        "manual_notes": (
            "‘任一后端语言’建立封闭 any_of；普通斜杠枚举不建组。PgVector/Milvus、"
            "LangGraph/AutoGen/LlamaIndex 和 VSCode/IDEA 作为上位能力的具体例子，只作 mention。"
            "文章和专利属于非技能加分条件，排除。当前 v34 关系守卫未覆盖‘任一+类别名’句式，"
            "标签按原文人工保留该组，不以 Parser 的错误输出为准。"
        ),
    },
    "external-dev-v34-004": {
        "company": "摩尔线程",
        "title": "图形渲染/3DGS算法工程师",
        "source_url": "https://mthreads.zhiye.com/campus/detail?jobAdId=7041d44a-0942-43ad-b10a-0c8b7894c07f",
        "owner_confirmation": {
            "status": "confirmed",
            "confirmed_at": "2026-09-03",
            "confirmed_items": ["D1", "D2", "D3", "D4", "D5", "D6", "D7"],
        },
        "job_type": "campus",
        "locations": ["北京", "杭州", "深圳", "上海", "无锡"],
        "clauses": [
            clause(
                "具备扎实的深度学习、概率论与优化理论功底。",
                "required",
                ["深度学习", "概率论", "优化理论"],
            ),
            clause(
                "精通 Python/C++，熟练掌握 PyTorch/TensorFlow。",
                "required",
                ["Python", "C++", "PyTorch", "TensorFlow"],
            ),
            clause(
                "深入理解 3DGS、NeRF 等相关技术，有相关项目复现或改进经验",
                "required",
                ["3DGS", "NeRF"],
                qualifier="project_experience",
            ),
            clause(
                "熟悉 Stable Diffusion、Sora 类视频生成模型",
                "required",
                ["视频生成模型"],
                examples=["Stable Diffusion", "Sora"],
            ),
            clause(
                "掌握扩散模型训练与可控生成技术。",
                "required",
                ["扩散模型训练", "可控生成"],
            ),
            clause(
                "具备从 0 到 1 的算法落地经验",
                "required",
                ["算法落地"],
                qualifier="practical_experience",
            ),
            clause(
                "熟悉工业级数据管线、模型压缩及端侧部署流程。",
                "required",
                ["工业级数据管线", "模型压缩", "端侧部署"],
            ),
            clause(
                "了解计算机图形学（CG）原理，如光照模型、物理模拟、Mesh/PBR 纹理管线等",
                "preferred",
                ["计算机图形学"],
                examples=["光照模型", "物理模拟", "Mesh", "PBR纹理管线"],
            ),
            clause(
                "熟悉 SLAM、多视角几何重建，具备三维场景理解能力",
                "preferred",
                ["SLAM", "多视角几何重建", "三维场景理解"],
            ),
            clause(
                "开展 3DGS 算法研究优化、多模态内容生成算法开发，搭建训练管线并完成算法全链路部署",
                "mention",
                ["3DGS", "多模态内容生成", "算法开发", "训练管线", "算法部署"],
            ),
            clause(
                "推动实时渲染与动态场景重建技术落地",
                "mention",
                ["实时渲染", "动态场景重建"],
            ),
            clause(
                "开发基于扩散模型、多模态等框架的视频/图像生成算法，支持多模态内容生成（如文生视频、图生3D等）",
                "mention",
                ["扩散模型", "多模态", "视频生成", "图像生成", "多模态内容生成"],
                examples=["文生视频", "图生3D"],
            ),
            clause(
                "优化大模型在显卡硬件的分布式训练与推理效率",
                "mention",
                ["LLM", "GPU", "分布式训练", "模型推理优化"],
            ),
            clause(
                "探索神经渲染、物理仿真与生成模型的融合应用",
                "mention",
                ["神经渲染", "物理仿真", "生成模型"],
            ),
            clause(
                "将CV算法集成到实时渲染管线",
                "mention",
                ["计算机视觉", "实时渲染管线"],
            ),
        ],
        "manual_notes": (
            "普通斜杠枚举按 all_of，不建立 any_of。Stable Diffusion/Sora 是‘视频生成模型’的例子；"
            "光照模型、物理模拟、Mesh/PBR 是‘计算机图形学’的例子。顶会一作与高影响力开源项目"
            "构成论文/项目混合任选条件，现有技能 schema 无法无损表达，整段排除并保留本说明。"
        ),
    },
}


def apply_manual_group_overrides(
    fields: dict[str, Any],
    overrides: list[dict[str, Any]],
) -> None:
    for override in overrides:
        options = override["any_of"]
        option_keys = {option.casefold() for option in options}
        fields["required_skills"] = [
            skill
            for skill in fields.get("required_skills") or []
            if skill.casefold() not in option_keys
        ]
        groups = fields.get("required_skill_groups") or []
        groups.append(
            {
                "name": override["name"],
                "any_of": options,
                "allow_other": override["allow_other"],
            }
        )
        fields["required_skill_groups"] = groups
        fields["skill_mentions"] = [
            *(fields.get("skill_mentions") or []),
            *options,
        ]
        fields["skill_concepts"] = [
            concept
            for concept in fields.get("skill_concepts") or []
            if not (
                concept["canonical_name"].casefold() in option_keys
                and concept["strength"] == "required"
                and concept["relation"] == "all_of"
            )
        ]
        fields["skill_concepts"].extend(
            {
                "skill_id": skill_id_for(option),
                "canonical_name": option,
                "strength": "required",
                "qualifier": None,
                "relation": "any_of",
                "group_name": override["name"],
                "allow_other": override["allow_other"],
                "source_text": override["source_text"],
            }
            for option in options
        )


def build_case(case: dict[str, Any]) -> dict[str, Any]:
    clauses = [CoreSkillClause.model_validate(item) for item in case["clauses"]]
    source_content = "\n".join(item.source_text for item in clauses)
    compiled = compile_core_model_output(
        CoreModelOutput(
            job_type=case["job_type"],
            locations=case["locations"],
            skill_clauses=clauses,
        ),
        source_content=source_content,
    )
    overrides = case.get("manual_group_overrides", [])
    expected_warnings = ["unsupported_any_of_relation"] * len(overrides)
    actual_warnings = [warning.code for warning in compiled.warnings]
    if actual_warnings != expected_warnings:
        messages = ", ".join(actual_warnings)
        raise ValueError(f"manual label compilation emitted warnings: {messages}")

    fields = dict(compiled.fields)
    apply_manual_group_overrides(fields, overrides)
    skill_mentions = fields.pop("skill_mentions") or []
    for key in (
        "locations",
        "required_skills",
        "required_skill_groups",
        "preferred_skills",
    ):
        fields[key] = fields.get(key) or []
    fields["skill_concepts"] = fields.get("skill_concepts") or []
    built = {
        "source": {
            "company": case["company"],
            "title": case["title"],
            "source_url": case["source_url"],
        },
        "fields": fields,
        "skill_mentions": skill_mentions,
        "manual_notes": case["manual_notes"],
        "owner_confirmation": case.get(
            "owner_confirmation",
            {"status": "pending", "confirmed_at": None, "confirmed_items": []},
        ),
    }
    validate_case(built)
    return built


def validate_case(case: dict[str, Any]) -> None:
    fields = case["fields"]
    mentions = case["skill_mentions"]
    CoreJobFields.model_validate({**fields, "skill_mentions": mentions})

    required = {skill.casefold() for skill in fields["required_skills"]}
    preferred = {skill.casefold() for skill in fields["preferred_skills"]}
    group_options = {
        skill.casefold()
        for group in fields["required_skill_groups"]
        for skill in group["any_of"]
    }
    assert required.isdisjoint(preferred)
    assert required.isdisjoint(group_options)
    assert preferred.isdisjoint(group_options)
    assert all(len(group["any_of"]) >= 2 for group in fields["required_skill_groups"])
    assert group_options <= {skill.casefold() for skill in mentions}

    concepts = fields["skill_concepts"]
    concept_keys = [
        (
            concept["skill_id"],
            concept["strength"],
            concept["qualifier"],
            concept["relation"],
            concept["group_name"],
            concept["allow_other"],
        )
        for concept in concepts
    ]
    assert len(concept_keys) == len(set(concept_keys))
    assert all(concept["source_text"] for concept in concepts)


def build_payload(*, frozen: bool) -> dict[str, Any]:
    payload = {
        "version": (
            "ai-campus-v34-dev4-label-freeze-v1-2026-09-03"
            if frozen
            else "ai-campus-v34-dev4-labels-v1-assistant-reviewed-2026-09-03"
        ),
        "selection_version": "ai-campus-v34-dev4-selection-v1-2026-09-03",
        "annotation_guide_version": "ai-campus-annotation-guide-v1",
        "annotation_status": (
            "owner_confirmed_frozen" if frozen else "owner_confirmed_not_frozen"
        ),
        "annotator": "Codex coding agent",
        "annotated_at": "2026-09-03",
        "reviewer": "repository owner",
        "reviewed_at": "2026-09-03",
        "parser_predictions_viewed": False,
        "external_model_calls": False,
        "frozen": frozen,
        "frozen_at": FROZEN_AT if frozen else None,
        "owner_confirmed_case_count": sum(
            case.get("owner_confirmation", {}).get("status")
            in {"confirmed", "confirmed_with_revision"}
            for case in CASES.values()
        ),
        "cases": {case_id: build_case(case) for case_id, case in CASES.items()},
    }
    return payload


def write_payload(path: Path, payload: dict[str, Any], *, immutable: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"refusing to overwrite changed freeze: {path}")
        return
    path.write_text(rendered, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    arguments = parser.parse_args()
    frozen = bool(arguments.freeze)
    write_payload(
        FROZEN_OUTPUT_PATH if frozen else REVIEW_OUTPUT_PATH,
        build_payload(frozen=frozen),
        immutable=frozen,
    )


if __name__ == "__main__":
    main()

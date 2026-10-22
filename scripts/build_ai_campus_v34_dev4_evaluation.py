from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.domain.skill_normalizer import SKILL_ONTOLOGY_VERSION
from src.evaluation.models import EvaluationManifest
from src.services.core_jd_parser import (
    CORE_SCHEMA_VERSION,
    DEFAULT_CORE_PARSER_VERSION,
    DEFAULT_CORE_PROMPT_VERSION,
)

LABEL_PATH = Path("datasets/ai_campus_v34_dev4_label_freeze_v1_2026_09_03.json")
RAW_PATH = Path("artifacts/evaluation/ai-campus-v34-dev4-raw-v1-2026-09-03.json")
MANIFEST_PATH = Path(
    "artifacts/evaluation/m11-ai-campus-manifest-core-v34-dev4-frozen-v1-2026-09-03.json"
)
FREEZE_PATH = Path("datasets/ai_campus_v34_dev4_freeze_manifest_v1_2026_09_03.json")
FROZEN_AT = "2026-09-03T09:45:05+08:00"

PARSER_FILES = (
    Path("src/services/core_jd_parser.py"),
    Path("src/domain/core_skill_semantics.py"),
    Path("src/domain/skill_normalizer.py"),
    Path("src/domain/job.py"),
    Path("src/infrastructure/llm_client.py"),
)


RAW_CASES: dict[str, dict[str, str]] = {
    "external-dev-v34-001": {
        "company": "搜狐",
        "title": "【2027】AI算法研发工程师-【引力计划】人才专项",
        "source_url": "https://campus.sohu.com/jobs/2027-gravity-ai-algo-rd-engineer-2f6a47e0/",
        "raw_content": """岗位名称：【2027】AI算法研发工程师-【引力计划】人才专项
招聘类型：校园招聘全职
招聘项目：2027届
工作地点：北京
发布日期：2026-08-03
申请截止：2026-10-31

岗位职责
1、参与Agent系统的设计与开发，推动Agent在搜索、推荐、视频理解等场景中的应用与落地
2、参与搜狐视频搜索、推荐、广告及视频理解相关系统的研发与优化，持续提升用户体验和业务效果
3、跟踪大模型（LLM）、Agent、多模态等前沿技术，探索新技术在业务场景中的应用
4、参与相关系统的架构设计、性能优化和工程建设，保障系统稳定高效运行

任职要求
1、硕士及以上学历，计算机、软件工程、数学、人工智能等相关专业优先
2、计算机基础扎实，熟悉常见算法与数据结构，具备良好的编程能力
3、熟悉 Java、Python、C++ 等至少一种编程语言
4、了解机器学习、深度学习相关基础知识，了解大语言模型（LLM）、Agent等相关技术
5、了解搜索、推荐系统、自然语言处理、计算机视觉、多模态等至少一个方向
6、具备良好的学习能力和技术热情，能够主动关注AI领域前沿技术发展
7、具备良好的沟通协作能力和责任心

加分项
1、有搜索、推荐、广告、NLP、CV、多模态等相关项目或科研经历
2、有大模型、Agent、RAG等相关实践经验
3、有 ACM、Kaggle等竞赛经历
4、有开源项目贡献经历或技术博客输出习惯""",
    },
    "external-dev-v34-002": {
        "company": "摩尔线程",
        "title": "大模型推理优化工程师",
        "source_url": "https://mthreads.zhiye.com/campus/detail?jobAdId=e9c2216b-79c0-4c33-8687-147ad255e479",
        "raw_content": """岗位名称：大模型推理优化工程师(J10995)
招聘类型：校园招聘 全职
工作地点：北京市、上海市、广东省·深圳市、浙江省·杭州市
发布日期：2026-08-10

工作职责
欢迎加入摩尔线程！我们深耕大模型推理场景与底层算子优化，依托自研 GPU 完成各类 AI 模型适配加速，落地高性能推理解决方案，助力 AI 算力产品商业化落地与开发者生态建设。
岗位职责：
1、负责各类大模型在自研 GPU 上的推理适配、性能调优与业务部署，解决高并发、长文本、多轮对话等场景的性能与稳定性瓶颈。
2、聚焦大模型推理全链路优化，落地分布式推理、量化、KV 缓存等核心策略，持续提升推理吞吐、降低推理时延。
3、跟进 LLM、VLM 等前沿模型技术，完成新模型适配加速与推理能力迭代升级。
4、结合自研 GPU 架构特性，基于并行编程工具完成高性能推理算子开发与极致调优。
5、对接业务与研发团队，输出可落地的推理解决方案，沉淀技术内容，共建开发者生态。

任职资格
1、计算机、人工智能、电子信息等相关专业，本科及以上学历。
2、熟悉 C++/Python，熟练使用 Linux 开发环境，具备扎实编程基础。
3、了解 GPU 并行计算原理与 Transformer 大模型基础架构。
4、具备大模型推理、模型部署或性能优化相关认知与学习热情。
5、具备良好的学习分析能力、责任心与团队协作意识。""",
    },
    "external-dev-v34-003": {
        "company": "摩尔线程",
        "title": "Agentic Infra 平台研发工程师",
        "source_url": "https://mthreads.zhiye.com/campus/detail?jobAdId=67d78507-7dbd-4c45-ade1-dfbb3488e30d",
        "raw_content": """岗位名称：Agentic Infra 平台研发工程师(J10997)
招聘类型：校园招聘 全职
工作地点：北京市、浙江省·杭州市、广东省·深圳市
发布日期：2026-08-10

工作职责
欢迎加入摩尔线程！你将参与 AI Coding 智能体平台的架构建设，打造面向 MUSA 生态的开发者基础设施，赋能广大开发者高效构建应用，实现个人技术成长与生态业务发展双向共赢。
岗位职责：
1、负责基于公司 MUSA 统一架构实现 AI Coding Agent 平台整体系统架构设计，建设 MUSA 算子生成、长上下文治理、自我进化的完整 Agent 技术体系，打造全球范围内领先的 MUSA AI Coding 智能体。
2、搭建 Musa 编程的 Skills 技术体系，支持百万开发者基于 MUSA 快速构建 Musa App，并落地业务成果。
3、搭建 Musa AI Coding Plan 套餐，支撑超长上下文、高并发、长程任务背景下的广大开发者并行使用场景，支持高质量 Coding Plan，交付高价值业务结果。

任职资格
1、具备 LLM Agent 落地实战经验，拥有代码智能助手、IDE AI 插件、研发提效平台完整落地案例。
2、精通 Go/Python/Java 任一后端语言，熟悉微服务、分布式队列、Redis、向量数据库（PgVector/Milvus）、K8S 容器调度。
3、拥有完整 AI Coding Agent 搭建经验，熟练 LangGraph/AutoGen/LlamaIndex 等 Agent 框架，掌握 Function Calling、RAG、记忆调度、多智能体协同设计。
4、具备代码模型强化学习落地经验，拥有代码沙箱、隔离执行环境、AI 输出安全风控架构设计经验。
5、具备 VSCode/IDEA AI 插件、企业研发中台、CI/CD 智能自动化落地经验。
6、熟悉 vLLM/SGLang 推理服务优化，具备 GPU 算力调度、大模型性能调优经验。
【加分项】
发表过 Agent / 代码大模型相关技术文章、拥有相关技术专利""",
    },
    "external-dev-v34-004": {
        "company": "摩尔线程",
        "title": "图形渲染/3DGS算法工程师",
        "source_url": "https://mthreads.zhiye.com/campus/detail?jobAdId=7041d44a-0942-43ad-b10a-0c8b7894c07f",
        "raw_content": """岗位名称：图形渲染/3DGS算法工程师(J10985)
招聘类型：校园招聘 全职
工作地点：北京市、浙江省·杭州市、广东省·深圳市、上海市、江苏省·无锡市
发布日期：2026-08-10

工作职责
欢迎加入摩尔线程！我们团队依托自研 GPU 算力底座，开展 3DGS 算法研究优化、多模态内容生成算法开发，搭建训练管线并完成算法全链路部署，跟进顶会前沿技术，联动图形引擎推动技术在业务场景落地，欢迎对图形 AI、三维生成方向充满热情的同学加入！
1、算法研发与优化
● 主导3D高斯泼溅（3DGS）算法的研究、实现及在显卡平台的性能优化，推动实时渲染与动态场景重建技术落地
● 开发基于扩散模型、多模态等框架的视频/图像生成算法，支持多模态内容生成（如文生视频、图生3D等）
2、模型训练与部署
● 设计高效训练管线，优化大模型在显卡硬件的分布式训练与推理效率，解决显存、算力瓶颈问题
● 实现算法从原型到产品的全链路部署，包括边缘端（如移动设备、嵌入式显卡）的轻量化适配
3、技术研究与创新
● 跟踪CVPR/ICCV/SIGGRAPH等顶会前沿技术，探索神经渲染、物理仿真与生成模型的融合应用
● 主导技术专利与顶会论文产出，提升公司在图形AI领域的技术影响力
4、跨团队协作
● 联动图形引擎团队，将CV算法集成到实时渲染管线，推动生成内容在游戏、影视等场景的落地

任职资格
1、硕士及以上学历，计算机、数学、电子工程相关专业，具备扎实的深度学习、概率论与优化理论功底。
2、精通 Python/C++，熟练掌握 PyTorch/TensorFlow。
3、深入理解 3DGS、NeRF 等相关技术，有相关项目复现或改进经验；熟悉 Stable Diffusion、Sora 类视频生成模型，掌握扩散模型训练与可控生成技术。
4、在 CVPR/ICCV/ECCV/SIGGRAPH 等顶会以一作发表论文，或主导过高影响力开源项目；具备从 0 到 1 的算法落地经验，熟悉工业级数据管线、模型压缩及端侧部署流程。
【加分项】
了解计算机图形学（CG）原理，如光照模型、物理模拟、Mesh/PBR 纹理管线等
熟悉 SLAM、多视角几何重建，具备三维场景理解能力""",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def write_json(path: Path, payload: dict[str, Any], *, immutable: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"refusing to overwrite changed freeze: {path}")
        return
    path.write_text(rendered, encoding="utf-8")


def build_manifest(labels: dict[str, Any]) -> dict[str, Any]:
    cases = []
    for case_id, raw_case in RAW_CASES.items():
        label = labels["cases"][case_id]
        cases.append(
            {
                "id": case_id,
                "split": "dev",
                "source": {
                    "kind": "real_public_source",
                    "reference": raw_case["source_url"],
                    "authorization": (
                        "用户于 2026-09-03 明确要求使用冻结 Parser 对这 4 条公开 JD 运行一次"
                    ),
                    "notes": label["manual_notes"],
                },
                "input": {
                    "raw_content": raw_case["raw_content"],
                    "source_url": raw_case["source_url"],
                    "scenario": "fresh_public_dev4_parser_evaluation",
                },
                "candidate_evidence_ids": [],
                "expected": {
                    "fields": label["fields"],
                    "skill_mentions": label["skill_mentions"],
                    "eligibility": None,
                    "evidence": {},
                    "failure_code": None,
                    "tags": ["v34_dev4", "owner_reviewed", "frozen_labels_v1"],
                },
            }
        )
    payload = {
        "manifest_version": "m11-ai-campus-v34-dev4-frozen-v1",
        "dataset_version": "m11-ai-v34-dev4-frozen-v1-2026-09-03",
        "split": "dev",
        "purpose": (
            "四条全新公开 2027 校招 JD 的一次性非盲开发评测；标签在预测前人工复核并冻结。"
        ),
        "source_policy": (
            "仅发送四个官方公开职位页面的 JD 原文给配置的 DeepSeek API；不读取候选人资料，"
            "不执行投递，不包含 blind-8 或密封 holdout。"
        ),
        "fields": [
            "job_type",
            "locations",
            "required_skills",
            "required_skill_groups",
            "preferred_skills",
        ],
        "thresholds": {},
        "cases": cases,
    }
    return EvaluationManifest.model_validate(payload).model_dump(mode="json")


def main() -> None:
    labels = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    if not labels.get("frozen") or labels.get("annotation_status") != (
        "owner_confirmed_frozen"
    ):
        raise ValueError(
            "labels must be owner-confirmed and frozen before manifest build"
        )
    if set(labels["cases"]) != set(RAW_CASES):
        raise ValueError("raw cases and frozen labels do not contain the same IDs")
    if (
        DEFAULT_CORE_PARSER_VERSION,
        DEFAULT_CORE_PROMPT_VERSION,
        CORE_SCHEMA_VERSION,
        SKILL_ONTOLOGY_VERSION,
    ) != (
        "jd-core-parser-v34",
        "jd-core-parser-prompt-v23",
        "core-job-fields-v10",
        "skill-ontology-v4",
    ):
        raise ValueError("runtime parser contract no longer matches the v34 freeze")

    raw_payload = {
        "version": "ai-campus-v34-dev4-raw-v1-2026-09-03",
        "collected_at": "2026-09-03",
        "source_policy": "official public job detail pages",
        "case_count": len(RAW_CASES),
        "cases": [
            {"id": case_id, **raw_case} for case_id, raw_case in RAW_CASES.items()
        ],
    }
    write_json(RAW_PATH, raw_payload, immutable=True)

    manifest = build_manifest(labels)
    write_json(MANIFEST_PATH, manifest, immutable=True)

    freeze = {
        "freeze_version": "ai-campus-v34-dev4-freeze-v1-2026-09-03",
        "frozen_at": FROZEN_AT,
        "purpose": "one authorized non-blind dev run on four fresh public JDs",
        "frozen_parser": {
            "parser": DEFAULT_CORE_PARSER_VERSION,
            "prompt": DEFAULT_CORE_PROMPT_VERSION,
            "schema": CORE_SCHEMA_VERSION,
            "skill_ontology": SKILL_ONTOLOGY_VERSION,
            "files": {path.as_posix(): file_record(path) for path in PARSER_FILES},
        },
        "annotation": file_record(LABEL_PATH),
        "raw_source": file_record(RAW_PATH),
        "evaluation_manifest": file_record(MANIFEST_PATH),
        "case_ids": list(RAW_CASES),
        "case_count": len(RAW_CASES),
        "api_authorization": {
            "authorized": True,
            "authorized_at": "2026-09-03",
            "destination": "configured DeepSeek API",
            "scope": "the four public JD texts in raw_source",
            "run_count_limit": 1,
        },
        "run_policy": {
            "concurrency": 1,
            "model_retries": 0,
            "parser_validation_repairs": 0,
            "http_timeout_seconds": 180,
            "case_timeout_seconds": 210,
            "checkpoint_resume": False,
            "retry_failures": False,
        },
        "prediction_status": "not_generated_at_freeze_time",
    }
    write_json(FREEZE_PATH, freeze, immutable=True)
    print(
        f"frozen cases={len(RAW_CASES)} label={sha256(LABEL_PATH)} "
        f"raw={sha256(RAW_PATH)} manifest={sha256(MANIFEST_PATH)}"
    )


if __name__ == "__main__":
    main()

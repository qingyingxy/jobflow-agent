from src.domain.core_skill_semantics import normalize_compiled_core_fields
from src.evaluation.models import EvaluationManifest, PredictionFile
from src.evaluation.replay_core_normalization import replay_core_normalization


def test_replay_core_normalization_changes_names_without_strength_inference() -> None:
    manifest = EvaluationManifest.model_validate(
        {
            "manifest_version": "test-v1",
            "dataset_version": "test-v1",
            "split": "dev",
            "purpose": "Test deterministic Core normalization replay.",
            "source_policy": "Synthetic test fixture with no external calls.",
            "fields": ["required_skills", "preferred_skills"],
            "cases": [
                {
                    "id": "case-1",
                    "split": "dev",
                    "source": {
                        "kind": "synthetic",
                        "reference": "inline-test",
                        "authorization": "test-fixture",
                    },
                    "input": {
                        "raw_content": (
                            "任职要求：熟悉机器学习理论；有 Volcano、Koordinator "
                            "相关项目、实习或开源经历优先。"
                        )
                    },
                    "expected": {"fields": {}},
                }
            ],
        }
    )
    predictions = PredictionFile.model_validate(
        {
            "prediction_version": "test-v1",
            "predictions": [
                {
                    "case_id": "case-1",
                    "fields": {
                        "required_skills": ["机器学习理论"],
                        "preferred_skills": [
                            "Volcano项目",
                            "Koordinator项目",
                            "Volcano实习",
                            "Koordinator实习",
                        ],
                    },
                }
            ],
        }
    )

    replayed = replay_core_normalization(
        manifest,
        predictions,
        prompt_version="replay-v1",
    )

    fields = replayed.predictions[0].fields
    assert fields is not None
    assert fields["required_skills"] == ["机器学习"]
    assert fields["preferred_skills"] == ["Volcano", "Koordinator"]
    assert replayed.prompt_version == "replay-v1"


def test_compiled_replay_preserves_source_scoped_required_compounds() -> None:
    source = (
        "任职要求：深入了解 PyTorch 等深度学习框架的架构和运行原理；"
        "具备机器人运动学、动力学与控制理论基础；"
        "扎实编程（Python/Java/C++/Go）。"
    )

    fields = normalize_compiled_core_fields(
        {
            "required_skills": [
                "PyTorch",
                "深度学习框架",
                "机器人运动学",
                "动力学",
                "控制理论",
                "编程能力",
                "Python",
                "Java",
                "C++",
                "Go",
            ]
        },
        source_content=source,
    )

    assert fields["required_skills"] == [
        "深度学习框架原理",
        "机器人运动学",
        "机器人动力学",
        "控制理论",
        "编程能力",
    ]
    assert fields["skill_mentions"] == ["PyTorch", "Python", "Java", "C++", "Go"]


def test_compiled_replay_collapses_explicit_preferred_categories_and_contexts() -> None:
    source = (
        "加分项：熟悉 KMP、RN 等跨平台技术，拥有 iOS、Android、鸿蒙等多端开发"
        "项目经验者优先；有足式机器人、机械臂、人形机器人真机部署经验，或机器人"
        "开源项目成果者优先。"
    )

    fields = normalize_compiled_core_fields(
        {
            "preferred_skills": [
                "KMP",
                "RN",
                "iOS",
                "Android",
                "鸿蒙",
                "足式机器人真机部署",
                "机械臂真机部署",
                "人形机器人真机部署",
                "开源项目",
            ]
        },
        source_content=source,
    )

    assert fields["preferred_skills"] == [
        "跨平台开发",
        "多端开发",
        "机器人真机部署",
        "机器人开源项目",
    ]
    assert set(fields["skill_mentions"] or []) >= {
        "KMP",
        "RN",
        "iOS",
        "Android",
        "鸿蒙",
    }


def test_compiled_replay_applies_shared_direction_experience_suffix() -> None:
    fields = normalize_compiled_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "研究方向",
                    "any_of": ["LLM方向", "穿戴模型方向"],
                    "allow_other": False,
                }
            ]
        },
        source_content="具备以下任一方向经验均可：LLM方向；穿戴模型方向。",
    )

    assert fields["required_skill_groups"] == [
        {
            "name": "研究方向",
            "any_of": ["LLM方向经验", "穿戴模型方向经验"],
            "allow_other": False,
        }
    ]

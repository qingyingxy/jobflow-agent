"""Versioned, deterministic evaluation helpers for the JobFlow MVP."""

from src.evaluation.agent_runs import summarize_agent_runs
from src.evaluation.metrics import EvaluationReport, evaluate_manifest
from src.evaluation.models import (
    EvaluationCase,
    EvaluationManifest,
    PredictionFile,
    PredictionRecord,
)

__all__ = [
    "EvaluationCase",
    "EvaluationManifest",
    "EvaluationReport",
    "PredictionFile",
    "PredictionRecord",
    "evaluate_manifest",
    "summarize_agent_runs",
]

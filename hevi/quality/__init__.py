"""Quality gates, failure taxonomy and bounded autonomous repair."""

from .evaluation import QualityEvaluation, QualityEvidence, evaluation_from_shot_verdicts
from .gate_policy import GatePolicy
from .repair_controller import (
    RepairAction,
    RepairBudget,
    RepairController,
    RepairDecision,
)
from .repair_executor import RepairPatch, apply_repair_decision, scopes_to_shot_indexes
from .repository import RepairRepository
from .taxonomy import FailureCode, severity_for

__all__ = [
    "FailureCode",
    "GatePolicy",
    "QualityEvaluation",
    "QualityEvidence",
    "RepairAction",
    "RepairBudget",
    "RepairController",
    "RepairDecision",
    "RepairPatch",
    "RepairRepository",
    "apply_repair_decision",
    "evaluation_from_shot_verdicts",
    "scopes_to_shot_indexes",
    "severity_for",
]

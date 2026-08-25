"""Canonical Production Graph persistence primitives.

The graph is the durable owner for director productions.  API modules may keep
an in-process projection for hot reads, but a projection is never the source
of truth.
"""

from hevi.production_graph.contracts import (
    ConstraintChange,
    ExecutionNode,
    ExecutionPlan,
    PlanDecision,
    ProductionCommand,
    RepairDecision,
    ToolCall,
    inputs_hash,
)
from hevi.production_graph.repository import ProductionGraphRepository

__all__ = [
    "ConstraintChange",
    "ExecutionNode",
    "ExecutionPlan",
    "PlanDecision",
    "ProductionCommand",
    "ProductionGraphRepository",
    "RepairDecision",
    "ToolCall",
    "inputs_hash",
]

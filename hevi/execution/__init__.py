"""P0-E: Immutable Execution Plans + DAG-scoped Autonomous Repair.

- ExecutionPlan: INSERT-ONLY versioning with hash-based idempotency
- RepairPlan: DAG closure + convergence + budget decision
- compute_dag_closure: only re-run affected DAG nodes
- decide_repair: iteration/budget/convergence stop logic
"""

from .plan import (
    ExecutionPlan,
    ImmutablePlanViolation,
    RepairPlan,
    compute_dag_closure,
    decide_repair,
)
from .repository import ExecutionPlanRepository
from .scheduler import (
    ResourceSnapshot,
    Scheduler,
    SchedulingDecision,
    SchedulingRequest,
    SchedulingWeights,
)

__all__ = [
    "ExecutionPlan",
    "ExecutionPlanRepository",
    "ImmutablePlanViolation",
    "RepairPlan",
    "compute_dag_closure",
    "decide_repair",
    "ResourceSnapshot",
    "Scheduler",
    "SchedulingDecision",
    "SchedulingRequest",
    "SchedulingWeights",
]

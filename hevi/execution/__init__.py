"""HEVI execution.

Two layers share this package, and they are not the same concern:

* **P0-E** — immutable execution plans, DAG repair, and scheduling. Who *should*
  run, and what to run when. Owned by ``plan``/``scheduler``/``repository``.
* **P8.3** — production proof. :class:`ProductionReceipt` is issued only from artifact
  *bytes* that a validator has observed, because ``artifact_exists() !=
  production_success``. Owned by ``models``/``execute``.

They are kept in separate modules and separate namespaces deliberately. P8.3 names its
receipt ``ProductionReceipt`` rather than ``ExecutionReceipt`` because P6's
``ExecutionReceipt`` already means "a delegate ran"; one name with two meanings is the
defect P8.2 found in its own state enum.

Neither layer names ``RunState``: only P6 may set ``RunState.PRODUCED``.
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

# ── P8.3: production proof ──
from hevi.execution.execute import (
    ArtifactReader,
    ReceiptLedger,
    Validator,
    issue_receipt,
)
from hevi.execution.models import (
    ExecutionFailure,
    ExecutionRun,
    ExecutionState,
    ProductionReceipt,
)

__all__ += [
    "ArtifactReader",
    "ExecutionFailure",
    "ExecutionRun",
    "ExecutionState",
    "ProductionReceipt",
    "ReceiptLedger",
    "Validator",
    "issue_receipt",
]

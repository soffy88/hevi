from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_service import GraphService
from hevi.canvas.node_mapper import NODE_EXECUTORS, VALID_NODE_TYPES, create_node_executor
from hevi.canvas.validation import GraphValidationError

__all__ = [
    "NODE_EXECUTORS",
    "VALID_NODE_TYPES",
    "ExecutorService",
    "GraphService",
    "GraphValidationError",
    "create_node_executor",
    "WorkflowAdapterError",
    "canvas_edge_warnings",
    "graph_to_workflow",
    "plan_rerun",
    "planned_graph",
    "rerun_order",
    "run_preflight_for_workflow",
    "workflow_to_graph",
]

# Workflow adapter names are resolved lazily (PEP 562): the adapter
# imports hevi.capabilities.canvas_workflow, and importing it eagerly
# here could cycle through hevi.capabilities modules that touch
# hevi.canvas.  Attribute access (and `from hevi.canvas import
# workflow_to_graph`) still works; it just happens on first use.
_WORKFLOW_ADAPTER_NAMES = {
    "WorkflowAdapterError",
    "canvas_edge_warnings",
    "graph_to_workflow",
    "plan_rerun",
    "planned_graph",
    "rerun_order",
    "run_preflight_for_workflow",
    "workflow_to_graph",
}


def __getattr__(name: str):  # PEP 562 lazy export
    if name in _WORKFLOW_ADAPTER_NAMES:
        from hevi.canvas import workflow_adapter as _adapter

        return getattr(_adapter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

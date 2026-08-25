from uuid import uuid4

import pytest

from hevi.production_graph import ExecutionNode, ExecutionPlan, PlanDecision, inputs_hash


def test_execution_plan_validates_dependencies_and_is_deterministic() -> None:
    production_id = uuid4()
    revision_id = uuid4()
    plan = ExecutionPlan(
        production_id=production_id,
        revision_id=revision_id,
        nodes=[
            ExecutionNode(node_key="render", op_type="render", capability="video/shot"),
            ExecutionNode(
                node_key="deliver",
                op_type="deliver",
                capability="artifact/commit",
                dependencies=["render"],
            ),
        ],
    )
    plan.validate_dag()
    assert inputs_hash({"b": 2, "a": 1}) == inputs_hash({"a": 1, "b": 2})


def test_execution_plan_rejects_cycles() -> None:
    plan = ExecutionPlan(
        production_id=uuid4(),
        revision_id=uuid4(),
        nodes=[
            ExecutionNode(node_key="a", op_type="x", capability="x", dependencies=["b"]),
            ExecutionNode(node_key="b", op_type="x", capability="x", dependencies=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        plan.validate_dag()


def test_agent_decision_has_replay_identity() -> None:
    command = PlanDecision(
        production_id=uuid4(),
        revision_id=uuid4(),
        inputs_hash=inputs_hash({"topic": "x"}),
        idempotency_key="plan:x",
        operation="compile",
        reason="test",
    )
    assert command.decision_id
    assert command.schema_version == 1

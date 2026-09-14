"""Interactive film graph validation and bounded path enumeration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from hevi.obase.creative import Choice, InteractiveFilm, StoryNode


class GraphFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: Literal["ERROR", "WARN"]
    node_id: UUID | None = None
    choice_id: UUID | None = None
    message: str


class GraphValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["PASS", "FAIL"]
    findings: tuple[GraphFinding, ...] = ()
    reachable_endings: tuple[UUID, ...] = ()
    unreachable_nodes: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class InteractiveFilmGraph:
    film: InteractiveFilm
    nodes: tuple[StoryNode, ...]
    choices: tuple[Choice, ...]


class InteractiveFilmModule:
    def validate(self, graph: InteractiveFilmGraph) -> GraphValidation:
        findings: list[GraphFinding] = []
        nodes = {node.node_id: node for node in graph.nodes}
        choices = {choice.choice_id: choice for choice in graph.choices}
        if len(nodes) != len(graph.nodes):
            findings.append(
                GraphFinding(code="DUPLICATE_NODE", severity="ERROR", message="duplicate node id")
            )
        if len(choices) != len(graph.choices):
            findings.append(
                GraphFinding(
                    code="DUPLICATE_CHOICE", severity="ERROR", message="duplicate choice id"
                )
            )
        if graph.film.start_node_id not in nodes:
            findings.append(
                GraphFinding(
                    code="START_NODE_MISSING", severity="ERROR", message="start node is missing"
                )
            )

        edges: dict[UUID, tuple[UUID, ...]] = {}
        for node in graph.nodes:
            targets: list[UUID] = []
            for choice_id in node.choice_ids:
                choice = choices.get(choice_id)
                if choice is None:
                    findings.append(
                        GraphFinding(
                            code="CHOICE_MISSING",
                            severity="ERROR",
                            node_id=node.node_id,
                            choice_id=choice_id,
                            message="node references unknown choice",
                        )
                    )
                    continue
                if choice.target_node_id not in nodes:
                    findings.append(
                        GraphFinding(
                            code="TARGET_NODE_MISSING",
                            severity="ERROR",
                            choice_id=choice.choice_id,
                            message="choice targets unknown node",
                        )
                    )
                    continue
                if choice.condition:
                    findings.extend(
                        GraphFinding(
                            code="INVALID_CONDITION",
                            severity="ERROR",
                            choice_id=choice.choice_id,
                            message=f"condition references unknown variable: {variable}",
                        )
                        for variable in choice.condition.variable_refs
                        if variable not in graph.film.variable_names
                    )
                targets.append(choice.target_node_id)
            edges[node.node_id] = tuple(targets)

        reachable = self._reachable(graph.film.start_node_id, edges)
        unreachable_nodes = tuple(node_id for node_id in nodes if node_id not in reachable)
        findings.extend(
            GraphFinding(
                code="DEAD_NODE",
                severity="ERROR",
                node_id=node_id,
                message="node is unreachable from the start",
            )
            for node_id in unreachable_nodes
        )
        reachable_endings = tuple(
            node.node_id for node in graph.nodes if node.ending and node.node_id in reachable
        )
        if not reachable_endings:
            findings.append(
                GraphFinding(
                    code="UNREACHABLE_ENDING",
                    severity="ERROR",
                    message="no ending is reachable from the start",
                )
            )
        status: Literal["PASS", "FAIL"] = "FAIL" if findings else "PASS"
        return GraphValidation(
            status=status,
            findings=tuple(findings),
            reachable_endings=reachable_endings,
            unreachable_nodes=unreachable_nodes,
        )

    def enumerate_paths(
        self,
        graph: InteractiveFilmGraph,
        *,
        max_depth: int = 30,
    ) -> tuple[tuple[UUID, ...], ...]:
        if max_depth < 1:
            raise ValueError("max_depth must be positive")
        nodes = {node.node_id: node for node in graph.nodes}
        choices = {choice.choice_id: choice for choice in graph.choices}
        paths: list[tuple[UUID, ...]] = []

        def visit(node_id: UUID | None, path: tuple[UUID, ...]) -> None:
            if node_id is None or node_id not in nodes or len(path) > max_depth:
                return
            next_path = (*path, node_id)
            node = nodes[node_id]
            if node.ending or len(next_path) == max_depth:
                paths.append(next_path)
                return
            for choice_id in node.choice_ids:
                choice = choices.get(choice_id)
                if choice and choice.target_node_id not in next_path:
                    visit(choice.target_node_id, next_path)

        visit(graph.film.start_node_id, ())
        return tuple(paths)

    @staticmethod
    def _reachable(start: UUID | None, edges: dict[UUID, tuple[UUID, ...]]) -> set[UUID]:
        if start is None or start not in edges:
            return set()
        seen: set[UUID] = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(edges.get(current, ()))
        return seen


__all__ = [
    "GraphFinding",
    "GraphValidation",
    "InteractiveFilmGraph",
    "InteractiveFilmModule",
]

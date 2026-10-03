"""P10d field-level dependency/impact graph (early cutoff + rerun_plan + inbound)."""

from __future__ import annotations

from dataclasses import dataclass, field

from hevi.creative.direction_verify.errors import VerifyError

STAGE_ORDER = ("Brief", "Benchmark", "Thesis", "Treatment", "BeatPlan", "Cinematography",
               "SoundDirection", "CueMap", "SceneDirection", "ShotIntent", "ShotPlan",
               "Generate", "TTS", "Timeline", "Render", "Observe", "Verify")


@dataclass(frozen=True)
class DepNode:
    id: str
    stage: str
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DepEdge:
    upstream: str
    downstream: str
    fields: frozenset[str] = frozenset()  # empty = conservative whole-node + warning


@dataclass
class DependencyGraph:
    nodes: dict[str, DepNode] = field(default_factory=dict)
    edges: list[DepEdge] = field(default_factory=list)

    def add_node(self, node: DepNode) -> None:
        if node.stage not in STAGE_ORDER:
            raise VerifyError(f"unknown stage: {node.stage}", code="DEP_BAD_STAGE")
        self.nodes[node.id] = node

    def add_edge(self, edge: DepEdge) -> None:
        self.edges.append(edge)

    def conservative_edges(self) -> list[DepEdge]:
        return [e for e in self.edges if not e.fields]


@dataclass(frozen=True)
class RerunStep:
    stage: str
    scope: tuple[str, ...]
    cost_class: str


@dataclass(frozen=True)
class ImpactReport:
    changed_fields: tuple[str, ...]
    upper_bound: tuple[str, ...]
    earliest_stage: str
    preserved: tuple[str, ...]
    rerun_plan: tuple[RerunStep, ...]
    gate_required: bool
    conservative_warnings: tuple[str, ...] = ()


def compute_revision_impact(base: dict[str, str], new: dict[str, str],
                            graph: DependencyGraph,
                            *, gate_fields: frozenset[str] = frozenset()) -> ImpactReport:
    """base/new: {node_id: content_hash}. Returns conservative upper bound."""
    changed_fields: set[str] = set()
    for node_id, old_hash in base.items():
        if new.get(node_id) != old_hash:
            node = graph.nodes.get(node_id)
            changed_fields.update(node.writes if node else {node_id})
    seeds = {n.id for n in graph.nodes.values() if n.reads & changed_fields}
    changed_nodes = {nid for nid, old_hash in base.items() if new.get(nid) != old_hash}
    upper = set(seeds) | (changed_nodes & set(graph.nodes))
    for node_id in list(upper):
        changed_fields.update(graph.nodes[node_id].writes)
    frontier = list(upper)
    warnings: list[str] = []
    while frontier:
        current = frontier.pop()
        for edge in graph.edges:
            if edge.upstream != current or edge.downstream in upper:
                continue
            if not edge.fields:
                warnings.append(f"IMPACT_CONSERVATIVE_EDGE: {edge.upstream}->{edge.downstream}")
                upper.add(edge.downstream)
                changed_fields.update(graph.nodes[edge.downstream].writes)
                frontier.append(edge.downstream)
            elif edge.fields & changed_fields:
                upper.add(edge.downstream)
                changed_fields.update(graph.nodes[edge.downstream].writes)
                frontier.append(edge.downstream)
    ordered = sorted(upper, key=lambda n: STAGE_ORDER.index(graph.nodes[n].stage))
    earliest = graph.nodes[ordered[0]].stage if ordered else ""
    preserved = tuple(sorted(set(graph.nodes) - upper))
    plan = tuple(RerunStep(graph.nodes[n].stage, (n,), "low") for n in ordered)
    return ImpactReport(tuple(sorted(changed_fields)), tuple(ordered), earliest, preserved,
                        plan, bool(changed_fields & gate_fields), tuple(warnings))


def apply_early_cutoff(upper_bound: tuple[str, ...],
                       rebuilt_hashes: dict[str, tuple[str, str]]) -> tuple[str, ...]:
    """Drop nodes whose rebuild proved output unchanged. Downstream pruning of an
    unchanged node is the caller's iterative job; this step guarantees
    actually_rebuilt ⊆ upper_bound. Unrebuilt nodes stay (still pending)."""
    return tuple(n for n in upper_bound
                 if n not in rebuilt_hashes or rebuilt_hashes[n][0] != rebuilt_hashes[n][1])


def apply_authority_change(graph: DependencyGraph, authority: str,
                           pinned_nodes: dict[str, str]) -> tuple[str, ...]:
    """Inbound invalidation: nodes pinned to a changed authority go STALE."""
    return tuple(nid for nid, pin in pinned_nodes.items()
                 if pin == authority and nid in graph.nodes)

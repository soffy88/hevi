"""HEVI P3 — Autonomous Production Runtime (orchestration only).

Durable JSON-backed mission store, plan graph executor with real fan-out,
fan-in validation, targeted repair, resume, cancel, idempotency, budget,
and provider-policy recording. All media work delegates to P0/P1/P2.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.missions.p3_types import (
    ArtifactRecord,
    ClaimRecord,
    DeliveryManifest,
    NarrationBlock,
    PlanNode,
    ProductionBudget,
    ProductionChapter,
    ProductionMission,
    ProductionPlan,
    ProductionSegment,
    ProviderPolicy,
    ResearchBundle,
    ScriptDocument,
    ScriptSection,
    SourceRecord,
)

_STORE_FILENAME = "mission.json"
_CANCEL_FILENAME = "CANCEL"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Store ─────────────────────────────────────────────────────────────

class MissionStore:
    """Durable file-backed mission store. Every mutation persists."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self.root / _STORE_FILENAME

    def save(self, mission: ProductionMission) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(mission.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> ProductionMission | None:
        if not self.path.is_file():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return _mission_from_dict(raw)

    def cancel_requested(self) -> bool:
        return (self.root / _CANCEL_FILENAME).is_file()

    def request_cancel(self) -> None:
        (self.root / _CANCEL_FILENAME).write_text("cancel", encoding="utf-8")


def _mission_from_dict(raw: dict[str, Any]) -> ProductionMission:
    m = ProductionMission(
        mission_id=raw.get("mission_id", ""),
        request=raw.get("request", ""),
        profile_id=raw.get("profile_id", ""),
        production_goal=raw.get("production_goal", ""),
        target_duration_s=float(raw.get("target_duration_s", 0) or 0),
        status=raw.get("status", "CREATED"),
        revision=int(raw.get("revision", 1)),
        artifact_root=raw.get("artifact_root", ""),
        quality_policy=raw.get("quality_policy", {}),
        repair_count=int(raw.get("repair_count", 0)),
        no_progress_streak=int(raw.get("no_progress_streak", 0)),
    )
    m.created_at = raw.get("created_at", m.created_at)
    m.updated_at = raw.get("updated_at", m.updated_at)
    pp = raw.get("provider_policy", {})
    m.provider_policy = ProviderPolicy(
        preferred_provider=pp.get("preferred_provider", ""),
        fallback_providers=tuple(pp.get("fallback_providers", ())),
        cost_ceiling_usd=float(pp.get("cost_ceiling_usd", 0) or 0),
        quality_floor=pp.get("quality_floor", ""),
        retry_max=int(pp.get("retry_max", 2)),
        timeout_s=int(pp.get("timeout_s", 300)),
    )
    bg = raw.get("budget", {})
    m.budget = ProductionBudget(
        max_total_cost_usd=float(bg.get("max_total_cost_usd", 0) or 0),
        estimated_cost_usd=float(bg.get("estimated_cost_usd", 0) or 0),
        actual_cost_usd=float(bg.get("actual_cost_usd", 0) or 0),
    )
    rb = raw.get("research_bundle")
    if rb:
        m.research_bundle = ResearchBundle(
            bundle_id=rb.get("bundle_id", ""),
            sources=[SourceRecord(**s) for s in rb.get("sources", [])],
            claims=[ClaimRecord(**c) for c in rb.get("claims", [])],
            asset_leads=list(rb.get("asset_leads", [])),
            revision=int(rb.get("revision", 1)),
        )
    sc = raw.get("script")
    if sc:
        sections = [ScriptSection(
            section_id=s.get("section_id", ""),
            title=s.get("title", ""),
            blocks=[NarrationBlock(**b) for b in s.get("blocks", [])],
            profile_phase=s.get("profile_phase", "DEVELOPMENT"),
        ) for s in sc.get("sections", [])]
        m.script = ScriptDocument(
            script_id=sc.get("script_id", ""), sections=sections,
            revision=int(sc.get("revision", 1)),
            research_bundle_id=sc.get("research_bundle_id", ""),
            profile_id=sc.get("profile_id", ""))
    pl = raw.get("plan")
    if pl:
        m.plan = ProductionPlan(plan_id=pl.get("plan_id", ""), revision=int(pl.get("revision", 1)))
        for n in pl.get("nodes", []):
            m.plan.nodes.append(PlanNode(
                node_id=n.get("node_id", ""), kind=n.get("kind", ""), label=n.get("label", ""),
                dependencies=tuple(n.get("dependencies", ())), status=n.get("status", "PENDING"),
                attempts=int(n.get("attempts", 0)), max_attempts=int(n.get("max_attempts", 3)),
                artifact_ids=tuple(n.get("artifact_ids", ())), error=n.get("error", ""),
                estimated_cost_usd=float(n.get("estimated_cost_usd", 0) or 0),
                actual_cost_usd=float(n.get("actual_cost_usd", 0) or 0),
                idempotency_key=n.get("idempotency_key", ""),
                segment_index=int(n.get("segment_index", -1)),
                payload=n.get("payload", {})))
    for c in raw.get("chapters", []):
        ch = ProductionChapter(chapter_index=int(c.get("chapter_index", 0)), title=c.get("title", ""))
        for s in c.get("segments", []):
            ch.segments.append(ProductionSegment(
                segment_index=int(s.get("segment_index", 0)),
                chapter_index=int(s.get("chapter_index", 0)),
                narration=s.get("narration", ""), status=s.get("status", "PENDING"),
                segment_run_dir=s.get("segment_run_dir", ""), final_mp4=s.get("final_mp4", ""),
                report=s.get("report", {})))
        m.chapters.append(ch)
    for k, v in (raw.get("artifacts", {}) or {}).items():
        m.artifacts[k] = ArtifactRecord(
            artifact_id=v.get("artifact_id", k), type=v.get("type", ""),
            revision=int(v.get("revision", 1)), producer=v.get("producer", ""),
            parents=tuple(v.get("parents", ())), hash=v.get("hash", ""),
            status=v.get("status", "VALID"), created_at=v.get("created_at", ""),
            provenance=v.get("provenance", {}), path=v.get("path", ""))
    dl = raw.get("delivery")
    if dl:
        m.delivery = DeliveryManifest(
            mission_id=dl.get("mission_id", m.mission_id), final_mp4=dl.get("final_mp4", ""),
            proof_mp4=dl.get("proof_mp4", ""), captions=dl.get("captions", ""),
            thumbnail=dl.get("thumbnail", ""), production_report=dl.get("production_report", ""),
            source_manifest=dl.get("source_manifest", ""), artifact_manifest=dl.get("artifact_manifest", ""),
            editable_project=dl.get("editable_project", ""), hashes=dl.get("hashes", {}))
    return m


def create_mission(
    root: Path,
    request: str,
    profile_id: str,
    production_goal: str = "",
    target_duration_s: float = 0.0,
    budget_usd: float = 50.0,
) -> tuple[ProductionMission, MissionStore]:
    store = MissionStore(root)
    mission_id = f"mission-{uuid.uuid4().hex[:12]}"
    mission = ProductionMission(
        mission_id=mission_id, request=request, profile_id=profile_id,
        production_goal=production_goal or request,
        target_duration_s=target_duration_s, artifact_root=str(root),
        budget=ProductionBudget(max_total_cost_usd=budget_usd),
        provider_policy=ProviderPolicy(preferred_provider="local", quality_floor="cpu_first"),
    )
    store.save(mission)
    return mission, store


# ── Planning ──────────────────────────────────────────────────────────

def _split_narration(narration: str, parts: int) -> list[str]:
    sents = [s.strip() for s in narration.replace("。", ".").split(".") if s.strip()]
    if not sents:
        return [narration]
    groups: list[list[str]]
    if parts <= 1 or len(sents) <= parts:
        groups = [[s] for s in sents]
    else:
        # Contiguous chunks preserve narrative order (never round-robin).
        base, extra = divmod(len(sents), parts)
        groups = []
        idx = 0
        for p in range(parts):
            size = base + (1 if p < extra else 0)
            groups.append(sents[idx:idx + size])
            idx += size
    # Preserve sentence boundaries so downstream beat planners see real sentences.
    return [". ".join(g) + ("" if not g else ".") for g in groups if g]


def build_plan(mission: ProductionMission, narration: str, segments_per_chapter: int = 3) -> ProductionPlan:
    """Deterministic planner: research → script → per-segment renders → fan-in → delivery."""
    plan = ProductionPlan(plan_id=f"{mission.mission_id}:plan")
    plan.nodes.append(PlanNode(node_id="research", kind="RESEARCH", label="research + verification",
                               estimated_cost_usd=0.0, idempotency_key=f"{mission.mission_id}:research:v1"))
    plan.nodes.append(PlanNode(node_id="script", kind="SCRIPT", label="script document",
                               dependencies=("research",), estimated_cost_usd=0.0,
                               idempotency_key=f"{mission.mission_id}:script:v1"))
    seg_texts = _split_narration(narration, segments_per_chapter)
    for i, seg in enumerate(seg_texts):
        plan.nodes.append(PlanNode(
            node_id=f"segment-{i}", kind="RENDER", label=f"segment {i} render",
            dependencies=("script",), estimated_cost_usd=1.0,
            idempotency_key=f"{mission.mission_id}:segment-{i}:v1", segment_index=i,
            payload={"narration": seg}))
    plan.nodes.append(PlanNode(
        node_id="fanin", kind="EDIT", label="segment fan-in + master QA",
        dependencies=tuple(f"segment-{i}" for i in range(len(seg_texts))),
        estimated_cost_usd=0.0, idempotency_key=f"{mission.mission_id}:fanin:v1"))
    plan.nodes.append(PlanNode(
        node_id="delivery", kind="DELIVERY", label="delivery manifest",
        dependencies=("fanin",), estimated_cost_usd=0.0,
        idempotency_key=f"{mission.mission_id}:delivery:v1"))
    return plan


def build_chapters(mission: ProductionMission, narration: str, segments_per_chapter: int = 3) -> None:
    seg_texts = _split_narration(narration, segments_per_chapter)
    ch = ProductionChapter(chapter_index=0, title=mission.production_goal or "chapter-0")
    for i, seg in enumerate(seg_texts):
        ch.segments.append(ProductionSegment(
            segment_index=i, chapter_index=0, narration=seg,
            segment_run_dir=str(Path(mission.artifact_root) / f"segment-{i}")))
    mission.chapters = [ch]


def plan_graph_edges(plan: ProductionPlan) -> dict[str, list[str]]:
    """Dependency + lineage edges for observability."""
    return {n.node_id: list(n.dependencies) for n in plan.nodes}


# ── Research / Script builders ────────────────────────────────────────

_KNOWN_SOURCES: dict[str, dict[str, str]] = {
    "meditations": {"title": "Meditations", "author": "Marcus Aurelius", "type": "book-public-domain"},
    "black hole": {"title": "NASA black hole imagery", "author": "NASA", "type": "science-official"},
    "accretion": {"title": "NASA accretion disk visualization", "author": "NASA", "type": "science-official"},
    "tang": {"title": "Tang dynasty records", "author": "multiple", "type": "history-public"},
    "chang'an": {"title": "Tang dynasty records", "author": "multiple", "type": "history-public"},
    "silk road": {"title": "Silk Road historical consensus", "author": "multiple", "type": "history-public"},
}


def build_research(request: str, narration: str) -> ResearchBundle:
    text = f"{request} {narration}".lower()
    sources: list[SourceRecord] = []
    seen: set[str] = set()
    for kw, meta in _KNOWN_SOURCES.items():
        if kw in text and meta["title"] not in seen:
            seen.add(meta["title"])
            sources.append(SourceRecord(
                source_id=f"src-{len(sources)}", title=meta["title"],
                source_type=meta["type"], verified=True, verification_method="known-source-registry"))
    claims = [ClaimRecord(claim_id=f"claim-{i}", statement=s.strip(),
                          source_ids=tuple(s.source_id for s in sources),
                          verified=bool(sources), kind="fact" if sources else "original_expression")
              for i, s in enumerate([x.strip() for x in narration.split(".") if x.strip()])]
    return ResearchBundle(bundle_id=f"research-{uuid.uuid4().hex[:8]}",
                          sources=sources, claims=claims,
                          asset_leads=["/tmp/hevi-science-v3/assets"])


def build_script(research: ResearchBundle, narration: str, profile_id: str) -> ScriptDocument:
    sents = [s.strip() for s in narration.replace("。", ".").split(".") if s.strip()]
    phases = ["HOOK", "ORIENTATION", "DEVELOPMENT", "ESCALATION", "PAYOFF"]
    sections = []
    for i, s in enumerate(sents):
        kind = "paraphrase" if ("paraphrased" in s.lower() or "reminded me" in s.lower()) else "narration"
        src_ids = tuple(x.source_id for x in research.sources)
        sections.append(ScriptSection(
            section_id=f"sec-{i}", title=f"section-{i}",
            blocks=[NarrationBlock(block_id=f"blk-{i}", text=s, kind=kind,
                                   source_ids=src_ids, verified=bool(src_ids) or kind != "quotation")],
            profile_phase=phases[min(i, len(phases) - 1)] if len(sents) <= 5 else "DEVELOPMENT"))
    return ScriptDocument(script_id=f"script-{uuid.uuid4().hex[:8]}", sections=sections,
                          research_bundle_id=research.bundle_id, profile_id=profile_id)


# ── Executor ──────────────────────────────────────────────────────────

NodeRunner = Callable[[ProductionMission, PlanNode, MissionStore], Any]


async def _run_node_sync(runner: NodeRunner, mission: ProductionMission,
                         node: PlanNode, store: MissionStore) -> Any:
    import inspect

    result = runner(mission, node, store)
    if inspect.isawaitable(result):
        result = await result
    return result


class MissionExecutor:
    """Graph executor with fan-out, checkpoints, idempotency, cancel, budget."""

    def __init__(self, store: MissionStore, runners: dict[str, NodeRunner],
                 max_parallel: int = 2, crash_after: int = -1) -> None:
        self.store = store
        self.runners = runners
        self.max_parallel = max_parallel
        self.crash_after = crash_after
        self._completed_since_start = 0

    def _check_cancel(self, mission: ProductionMission) -> bool:
        return self.store.cancel_requested()

    def _check_budget(self, mission: ProductionMission, node: PlanNode) -> tuple[bool, str]:
        return mission.budget.check(node.estimated_cost_usd)

    def _node_cached(self, mission: ProductionMission, node: PlanNode) -> bool:
        if node.status != "COMPLETED":
            return False
        for aid in node.artifact_ids:
            rec = mission.artifacts.get(aid)
            if rec is None or rec.status != "VALID":
                return False
            if rec.path and not Path(rec.path).is_file():
                return False
        return bool(node.artifact_ids)

    async def run(self, mission: ProductionMission,
                  only_kinds: set[str] | None = None) -> ProductionMission:
        assert mission.plan is not None, "mission has no plan"
        sem = asyncio.Semaphore(self.max_parallel)
        while True:
            if self._check_cancel(mission):
                for n in mission.plan.nodes:
                    if n.status in ("PENDING", "RUNNING"):
                        n.status = "CANCELLED"
                mission.set_status("CANCELLED")
                self.store.save(mission)
                return mission
            ready = mission.plan.ready_nodes()
            if only_kinds is not None:
                ready = [n for n in ready if n.kind in only_kinds]
            if not ready:
                break
            # Budget gate before dispatch
            for n in ready:
                ok, reason = self._check_budget(mission, n)
                if not ok:
                    n.status = "BLOCKED"
                    n.error = reason
                    mission.set_status("BLOCKED")
                    self.store.save(mission)
                    return mission
            # Idempotency: skip cached nodes
            todo = []
            for n in ready:
                if self._node_cached(mission, n):
                    continue
                todo.append(n)
            if not todo:
                break

            async def _one(node: PlanNode) -> None:
                async with sem:
                    if self._check_cancel(mission):
                        node.status = "CANCELLED"
                        return
                    node.status = "RUNNING"
                    node.attempts += 1
                    self.store.save(mission)
                    runner = self.runners.get(node.kind)
                    if runner is None:
                        node.status = "FAILED"
                        node.error = f"no runner for kind {node.kind}"
                        self.store.save(mission)
                        return
                    try:
                        result = await _run_node_sync(runner, mission, node, self.store)
                        cost = float((result or {}).get("actual_cost_usd", 0.0))
                        node.actual_cost_usd = cost
                        mission.budget.actual_cost_usd += cost
                        node.status = "COMPLETED"
                        node.error = ""
                        if isinstance(result, dict):
                            for aid in result.get("artifact_ids", ()):
                                node.artifact_ids = (*node.artifact_ids, aid)
                        self._completed_since_start += 1
                    except Exception as exc:
                        node.status = "FAILED"
                        node.error = str(exc)[:500]
                    self.store.save(mission)
                    if self.crash_after >= 0 and self._completed_since_start >= self.crash_after:
                        raise RuntimeError("INJECTED_CRASH")

            await asyncio.gather(*(_one(n) for n in todo))
            self.store.save(mission)
            # Stop on failures (repair handled by caller)
            if any(n.status == "FAILED" for n in mission.plan.nodes):
                break
        return mission


def invalidate_dependents(mission: ProductionMission, changed_node_ids: tuple[str, ...]) -> list[str]:
    """Mark artifacts STALE and reset dependent nodes to PENDING. Returns reset node ids."""
    assert mission.plan is not None
    reset: list[str] = []
    # Collect downstream closure
    downstream: set[str] = set(changed_node_ids)
    changed = True
    while changed:
        changed = False
        for n in mission.plan.nodes:
            if n.node_id not in downstream and any(d in downstream for d in n.dependencies):
                downstream.add(n.node_id)
                changed = True
    for n in mission.plan.nodes:
        if (n.node_id in downstream
                and n.status in ("COMPLETED", "FAILED", "BLOCKED")):
            n.status = "PENDING"
            n.error = ""
            reset.append(n.node_id)
    for rec in mission.artifacts.values():
        if rec.producer in downstream:
            rec.status = "STALE"
    return reset


def classify_failure(node: PlanNode) -> str:
    err = (node.error or "").lower()
    mapping = [
        ("SOURCE_TRUTH", ("source", "verif", "unverified", "provenance")),
        ("SCRIPT_STRUCTURE", ("script",)),
        ("AUDIO", ("tts", "audio")),
        ("TIMELINE", ("timeline", "subtitle", "drift")),
        ("ASSET", ("asset",)),
        ("SHOT", ("shot",)),
        ("MOTION", ("motion", "remotion")),
        ("EDIT", ("edit", "concat", "fan-in", "fanin")),
        ("VISUAL_QA", ("visual quality", "quality", "blocked artifact")),
    ]
    for layer, keywords in mapping:
        if any(k in err for k in keywords):
            return layer
    return "VISUAL_QA"


def check_no_progress(mission: ProductionMission, completed_before: int,
                      max_streak: int = 3) -> tuple[bool, str]:
    """Detect repair rounds that produce no new completions.

    Returns (blocked, reason). Call after each repair round with the
    completed-node count observed before the round.
    """
    assert mission.plan is not None
    completed_now = sum(1 for n in mission.plan.nodes if n.status == "COMPLETED")
    if completed_now <= completed_before:
        mission.no_progress_streak += 1
    else:
        mission.no_progress_streak = 0
    if mission.no_progress_streak >= max_streak:
        return True, "NO_PROGRESS_BLOCKED"
    return False, ""


def assert_completable(mission: ProductionMission) -> tuple[bool, list[str]]:
    """Canonical completion authority: all required work truly done."""
    blockers: list[str] = []
    if mission.plan is None:
        return False, ["NO_PLAN"]
    incomplete = mission.plan.required_incomplete()
    if incomplete:
        blockers.append(f"NOT_RUN: {[n.node_id for n in incomplete]}")
    # P0/P1/P2 gates from segment reports
    for ch in mission.chapters:
        for seg in ch.segments:
            gates = seg.report.get("gates", {}) if isinstance(seg.report, dict) else {}
            failed = [g for g, v in gates.items() if not v]
            if failed:
                blockers.append(f"SEGMENT_GATES_FAIL seg{seg.segment_index}: {failed}")
    if mission.delivery is None:
        blockers.append("NO_DELIVERY")
    elif mission.delivery.final_mp4 and not Path(mission.delivery.final_mp4).is_file():
        blockers.append("DELIVERY_FILE_MISSING")
    return (len(blockers) == 0), blockers


def reap_stale_running_nodes(mission: ProductionMission) -> list[str]:
    """Reset RUNNING nodes left behind by a dead worker to PENDING.

    Attempts are preserved so retry budgets stay honest. Returns reset ids.
    """
    assert mission.plan is not None
    reset = []
    for n in mission.plan.nodes:
        if n.status == "RUNNING":
            n.status = "PENDING"
            reset.append(n.node_id)
    return reset


def status_view(mission: ProductionMission) -> dict[str, Any]:
    nodes = mission.plan.nodes if mission.plan else []
    by_status: dict[str, int] = dict(Counter(n.status for n in nodes))
    running = [n.node_id for n in nodes if n.status == "RUNNING"]
    failed = [n.node_id for n in nodes if n.status == "FAILED"]
    blocked = [n.node_id for n in nodes if n.status == "BLOCKED"]
    done = by_status.get("COMPLETED", 0)
    total = len(nodes)
    return {
        "mission_id": mission.mission_id, "status": mission.status,
        "phase": mission.status, "current_nodes": running,
        "completed_nodes": done, "total_nodes": total,
        "failed_nodes": failed, "blocked_nodes": blocked,
        "progress_pct": round(done / total * 100, 1) if total else 0.0,
        "actual_cost_usd": mission.budget.actual_cost_usd,
        "remaining_usd": mission.budget.remaining_usd,
        "repair_count": mission.repair_count,
        "next_dependencies": [n.node_id for n in (mission.plan.ready_nodes() if mission.plan else [])],
    }


__all__ = [
    "MissionExecutor",
    "MissionStore",
    "assert_completable",
    "build_chapters",
    "build_plan",
    "build_research",
    "build_script",
    "check_no_progress",
    "classify_failure",
    "create_mission",
    "invalidate_dependents",
    "reap_stale_running_nodes",
    "status_view",
]

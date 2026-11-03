"""A4 persistent world-session discipline (clean-room, method only).

Method source: Athenaion ``tools/session.mjs`` as described in
``hevi-vs-athenaion.md`` -- build the world once, snap many
variants, idle expiry -- see ATHENAION_ATTRIBUTION.md. The
discipline is layered on the existing, already-registered
``pipeline.project_snapshot`` (manual snapshots with inventory)
and ``pipeline.project_graph`` (validated node/edge graphs);
no second state store is invented here.

``WorldSession`` keeps one built world in memory: the build
callable runs exactly once, every variant reuses that build and
records its own wall time, and each variant is persisted as a
``project_snapshot`` snapshot of a manifest naming the world,
the build hash, the variant parameters and the project graph.
``check_session_record`` judges a recorded session: one build,
variants that all name the same build hash, snapshot ids that
exist in the record, and -- the economy claim -- total variant
time below the sum of independently rebuilding for each variant.
Timings must be measured and supplied; an unmeasured session
fails instead of passing on assertion.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.project_graph import create_graph, validate_graph
from hevi.capabilities.project_snapshot import create_snapshot, list_snapshots
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _build_hash(built: Any) -> str:
    try:
        payload = json.dumps(built, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        payload = repr(built)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class WorldSession:
    """One build, many snap variants, persisted via project_snapshot."""

    def __init__(
        self,
        project_root: Path,
        world_id: str,
        build_fn: Callable[[], Any],
        *,
        graph_nodes: list[dict[str, Any]] | None = None,
    ) -> None:
        root = Path(project_root)
        if not root.is_dir():
            raise CapabilityError(f"pipeline.athenaion_session: project root not found: {root}")
        if not isinstance(world_id, str) or not world_id.strip():
            raise CapabilityError("pipeline.athenaion_session: world_id must be a non-empty string")
        if not callable(build_fn):
            raise CapabilityError("pipeline.athenaion_session: build_fn must be callable")
        self.project_root = root
        self.world_id = world_id
        self._build_fn = build_fn
        self._built: Any = None
        self._build_hash: str | None = None
        self._build_ms: float | None = None
        self._build_calls = 0
        self.variants: list[dict[str, Any]] = []
        self.graph: dict[str, Any] | None = None
        if graph_nodes is not None:
            self.graph = create_graph(graph_nodes)

    def build(self) -> Any:
        """Run the build callable once; later calls return the cache."""
        if self._built is None:
            started = time.perf_counter()
            self._built = self._build_fn()
            self._build_ms = round((time.perf_counter() - started) * 1000.0, 3)
            self._build_hash = _build_hash(self._built)
            self._build_calls += 1
        return self._built

    @property
    def build_calls(self) -> int:
        return self._build_calls

    @property
    def build_hash(self) -> str | None:
        return self._build_hash

    def variant(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Snap one variant reusing the single build; persist a snapshot."""
        if not isinstance(name, str) or not name.strip():
            raise CapabilityError("pipeline.athenaion_session: variant name must be a non-empty string")
        if not isinstance(params, dict):
            raise CapabilityError("pipeline.athenaion_session: variant params must be a JSON object")
        built = self.build()
        started = time.perf_counter()
        variant_payload = {
            "world_id": self.world_id,
            "build_hash": self._build_hash,
            "variant": name,
            "params": params,
            "built_summary": str(built)[:200],
            "graph": self.graph,
        }
        manifest_path = self.project_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(variant_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        snapshot = create_snapshot(
            self.project_root, label=f"athenaion:{self.world_id}:{name}"
        )
        variant_ms = round((time.perf_counter() - started) * 1000.0, 3)
        record = {
            "name": name,
            "params": params,
            "world_id": self.world_id,
            "build_hash": self._build_hash,
            "snapshot_id": snapshot["snapshot_id"],
            "variant_ms": variant_ms,
        }
        self.variants.append(record)
        return record

    def record(self, *, independent_build_ms: list[float] | None = None) -> dict[str, Any]:
        """Session record for :func:`check_session_record`."""
        return {
            "world_id": self.world_id,
            "build": {
                "calls": self._build_calls,
                "build_hash": self._build_hash,
                "build_ms": self._build_ms,
            },
            "variants": list(self.variants),
            "variants_total_ms": round(sum(v["variant_ms"] for v in self.variants), 3),
            "independent_build_ms": independent_build_ms,
            "snapshot_ids": [v["snapshot_id"] for v in self.variants],
        }


def check_session_record(record: Any) -> dict[str, Any]:
    """Judge a session record. Unmeasured economy claims fail."""
    if not isinstance(record, dict):
        raise CapabilityError("pipeline.athenaion_session: session record must be a JSON object")
    issues: list[dict[str, Any]] = []
    build = record.get("build")
    if not isinstance(build, dict):
        issues.append(_issue("build_missing", "record needs a 'build' object"))
        build = {}
    if build.get("calls") != 1:
        issues.append(_issue(
            "build_not_once",
            "the world must be built exactly once per session",
            calls=build.get("calls"),
        ))
    build_hash = build.get("build_hash")
    if not isinstance(build_hash, str) or not build_hash:
        issues.append(_issue("build_hash_missing", "record.build needs a build_hash"))
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        issues.append(_issue(
            "variants_too_few",
            "a session needs at least 2 variants to prove reuse",
            count=len(variants) if isinstance(variants, list) else None,
        ))
        variants = []
    seen: set[str] = set()
    for variant in variants:
        if not isinstance(variant, dict):
            issues.append(_issue("variant_not_object", "variants must be objects"))
            continue
        if variant.get("build_hash") != build_hash:
            issues.append(_issue(
                "variant_build_hash_mismatch",
                "variant does not name the session build hash",
                variant=variant.get("name"),
            ))
        if variant.get("world_id") != record.get("world_id"):
            issues.append(_issue(
                "variant_world_mismatch",
                "variant does not name the session world_id",
                variant=variant.get("name"),
            ))
        snapshot_id = variant.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            issues.append(_issue("variant_snapshot_missing", "variant needs a snapshot_id"))
        elif snapshot_id in seen:
            issues.append(_issue("snapshot_id_reused", f"snapshot_id {snapshot_id!r} used twice"))
        seen.add(str(snapshot_id))
        if not isinstance(variant.get("variant_ms"), (int, float)):
            issues.append(_issue("variant_ms_missing", "variant needs a measured variant_ms"))
    total = record.get("variants_total_ms")
    independent = record.get("independent_build_ms")
    if not isinstance(total, (int, float)):
        issues.append(_issue("variants_total_missing", "record needs measured variants_total_ms"))
    if not isinstance(independent, list) or not independent or not all(
        isinstance(v, (int, float)) for v in independent
    ):
        issues.append(_issue(
            "independent_build_unmeasured",
            "independent_build_ms must list measured rebuild times, one per variant; "
            "an unmeasured economy claim fails",
        ))
    elif isinstance(total, (int, float)) and float(total) >= float(sum(independent)):
        issues.append(_issue(
            "no_reuse_economy",
            f"variants total {total}ms is not below independent rebuild sum {sum(independent)}ms",
            variants_total_ms=total, independent_sum_ms=sum(independent),
        ))
    return {
        "verdict": "fail" if issues else "pass",
        "issues": issues,
        "world_id": record.get("world_id"),
        "variant_count": len(variants),
        "variants_total_ms": total,
        "independent_sum_ms": sum(independent) if isinstance(independent, list) and independent else None,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record = params.get("record")
    if record is None:
        raise CapabilityError("pipeline.athenaion_session: params.record is required")
    report = check_session_record(record)
    # Cross-check snapshot ids against a real project root when given.
    if params.get("project_root"):
        existing = {s["snapshot_id"] for s in list_snapshots(Path(params["project_root"]))}
        missing = [sid for sid in record.get("snapshot_ids", []) if sid not in existing]
        if missing:
            report["issues"].append(_issue(
                "snapshot_not_found",
                "snapshot ids in the record are not present under project_root",
                missing=missing,
            ))
            report["verdict"] = "fail"
    report_path = out_dir / "athenaion_session_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass", "issues": report["issues"]},
    )


def register_athenaion_session_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="pipeline.athenaion_session",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "record": {"type": "object"},
                "project_root": {"type": "string"},
            },
            "required": ["record"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.01,
        render=_render,
        has_media_output=False,
        description=(
            "A4 persistent world-session discipline: build once, snap "
            "many variants via pipeline.project_snapshot / project_graph, "
            "with measured reuse economy. Unmeasured claims fail. "
            "See ATHENAION_ATTRIBUTION.md."
        ),
        line="pipeline",
    ))
    return ["pipeline.athenaion_session"]


register_athenaion_session_capabilities_once()

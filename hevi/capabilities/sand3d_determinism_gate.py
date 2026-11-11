"""3D program determinism gate (``qa.sand3d_determinism_gate``).

A sand3d-style program is deterministic when the same program
produces the same mesh digest in two fresh processes run with
different hash seeds, in either order. The gate compares the
digests of at least two such runs: any drift fails, and when
a golden digest is named the runs must match it too. The
gate's scope is stated honestly and enforced: it certifies
program-to-mesh digest equality only. Claiming byte-identical
export files overstates what the digest proves, and fails.

Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.
This gate judges determinism reports only; it never runs
Blender or any sand3d code. Real execution needs a separate
py3.13 + bpy 5.2 environment and is a separate work item.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

DETERMINISM_SCOPE = "program_to_mesh_digest"
OVERCLAIM_SCOPE = "byte_identical_exports"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_sand3d_determinism(report: Any) -> dict[str, Any]:
    """Validate a sand3d-style determinism report.

    Verdicts are ``pass`` / ``fail`` only. The report fails
    when it is not an object, when it carries fewer than two
    runs, when any run lacks a hash seed or a digest, when
    two runs share a hash seed, when the digests differ, when
    a named golden digest does not match the runs, when the
    report states no scope, or when the stated scope claims
    byte-identical export files instead of program-to-mesh
    digest equality.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(report, dict):
        return fail("report_not_object", "determinism report must be a JSON object")
    scope = report.get("scope")
    if scope == OVERCLAIM_SCOPE:
        return fail(
            "scope_overclaim",
            "determinism covers program-to-mesh digest equality "
            "only; byte-identical export files are not proven "
            "by a mesh digest",
        )
    if scope != DETERMINISM_SCOPE:
        return fail(
            "scope_missing",
            f"determinism report must state its scope as {DETERMINISM_SCOPE!r}",
        )
    runs = report.get("runs")
    if not isinstance(runs, list) or len(runs) < 2:
        return fail(
            "runs_missing",
            "determinism needs at least two runs in fresh processes with different hash seeds",
        )
    seeds: set[str] = set()
    digests: set[str] = set()
    for position, run in enumerate(runs):
        if not isinstance(run, dict):
            return fail(
                "run_not_object",
                f"run {position} must be an object",
            )
        seed = run.get("hash_seed")
        if not isinstance(seed, str) or not seed:
            return fail(
                "hash_seed_missing",
                f"run {position} must carry its hash seed",
            )
        if seed in seeds:
            return fail(
                "hash_seed_repeated",
                f"run {position} reuses hash seed {seed!r}; runs must use different hash seeds",
            )
        seeds.add(seed)
        digest = run.get("digest")
        if not isinstance(digest, str) or not digest:
            return fail(
                "digest_missing",
                f"run {position} must carry its mesh digest",
            )
        digests.add(digest)
    if len(digests) != 1:
        return fail(
            "digest_drift",
            "runs produced different mesh digests; the program is not deterministic",
        )
    golden = report.get("golden_digest")
    if golden is not None and golden not in digests:
        return fail(
            "golden_mismatch",
            "run digests do not match the named golden digest",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_sand3d_determinism(params.get("report"))
    report_path = out_dir / "sand3d_determinism_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sand3d_determinism_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sand3d_determinism_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "report": {"type": "object"},
                },
                "required": ["report"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "sand3d determinism gate: same program, same mesh "
                "digest in two fresh processes with different hash "
                "seeds; golden digest match; scope is "
                "program-to-mesh digest only, never byte-identical "
                "export files."
            ),
        )
    )
    return ["qa.sand3d_determinism_gate"]


__all__ = [
    "DETERMINISM_SCOPE",
    "OVERCLAIM_SCOPE",
    "check_sand3d_determinism",
    "register_sand3d_determinism_gate_capabilities_once",
]

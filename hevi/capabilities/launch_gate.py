"""Launch readiness gate (``pipeline.launch_gate``).

A gate and a report only. This module never deploys anything: no
push, no container operation, no production write. It answers one
question -- "is this project ready to be handed to a deployment
step?" -- and when the answer is no, it lists exactly which checks
failed.

Checks (every one must pass for ``ready: True``):

1. ``version_commit`` -- a commit hash is readable from the repo
   (``git rev-parse HEAD`` in ``repo_root``) and a version string
   is present (``version.txt`` at the repo root when it exists, or
   the literal ``unversioned`` recorded honestly when it does not;
   a missing commit hash alone fails this check).
2. ``capabilities`` -- every required capability imports and is
   registered: the six new productization capabilities plus the
   P0/P1/P2 set (``pipeline.project_handoff``,
   ``pipeline.spend_brake``, ``qa.final_qc_gate``,
   ``edit.subtitle_discipline``, ``audio.mix_recipe``,
   ``video.motion_beat_chart``, ``script.spoken_script_gate``,
   ``edit.speech_blemish_trim``, ``design.cover_family``,
   ``research.reference_teardown``). Missing names are listed.
   Note: capability names are verified against the live registry
   after importing ``hevi.capabilities``; a name that only exists
   as a file but never registers still fails.
3. ``regression_tests`` -- the P0/P1P2 + new regression test files
   can be listed (from an explicit list, or discovered under
   ``<repo>/tests`` by the known filenames). An empty list fails.
   Listing is all this check does: it does not run the suite, so a
   listed-but-failing test cannot be hidden behind this gate, and
   the report says the tests were listed, not run.
4. ``snapshot_ledger_io`` -- the snapshot directory and the ledger
   file under the checked project are readable and writable: a
   probe file is written, read back and removed in each location.
   A missing or read-only location fails with its path named.
5. ``rollback_point`` -- at least one snapshot exists in the
   project's snapshot directory, so there is a previous state to
   roll back to. The newest snapshot id is reported as the
   rollback point. Zero snapshots fails.

``check_launch`` returns the full report dict; ``write_report``
writes it as ``launch_readiness.json``. ``ready`` is False whenever
``failures`` is non-empty, and no partial pass is ever reported as
ready.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

NEW_CAPABILITIES: tuple[str, ...] = (
    "pipeline.project_graph",
    "pipeline.project_snapshot",
    "pipeline.spend_ledger",
    "pipeline.smart_reference",
    "model.model_directory",
    "pipeline.launch_gate",
)

LEGACY_CAPABILITIES: tuple[str, ...] = (
    "pipeline.project_handoff",
    "pipeline.spend_brake",
    "qa.final_qc_gate",
    "edit.subtitle_discipline",
    "audio.mix_recipe",
    "video.motion_beat_chart",
    "script.spoken_script_gate",
    "edit.speech_blemish_trim",
    "design.cover_family",
    "research.reference_teardown",
)

REQUIRED_CAPABILITIES: tuple[str, ...] = NEW_CAPABILITIES + LEGACY_CAPABILITIES

KNOWN_REGRESSION_TESTS: tuple[str, ...] = (
    "test_project_handoff.py",
    "test_spend_brake.py",
    "test_final_qc.py",
    "test_subtitle_discipline.py",
    "test_mix_recipe.py",
    "test_motion_beat_chart.py",
    "test_spoken_script.py",
    "test_speech_blemish_trim.py",
    "test_cover_family.py",
    "test_reference_teardown.py",
    "test_p0_product_graph.py",
    "test_p0_product_snapshot.py",
    "test_p0_spend_ledger.py",
    "test_p0_smart_reference.py",
    "test_p0_model_directory.py",
    "test_p0_launch_gate.py",
)


def _fail(message: str) -> None:
    raise CapabilityError(f"pipeline.launch_gate: {message}")


def _repo_root(repo_root: Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    # hevi/capabilities/launch_gate.py -> repo root is parents[2].
    return Path(__file__).resolve().parents[2]


def _read_commit(repo_root: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "commit": None, "detail": f"git failed: {exc}"}
    commit = proc.stdout.strip()
    if proc.returncode != 0 or not commit:
        return {
            "ok": False,
            "commit": None,
            "detail": (proc.stderr.strip() or "git rev-parse HEAD failed"),
        }
    version_path = repo_root / "version.txt"
    version = (
        version_path.read_text(encoding="utf-8").strip()
        if version_path.is_file() else "unversioned"
    )
    return {"ok": True, "commit": commit, "version": version, "detail": ""}


def _check_capabilities(required: tuple[str, ...]) -> dict[str, Any]:
    try:
        import hevi.capabilities as caps  # noqa: F401 -- import registers
        from hevi.capabilities.registry import names as registry_names
        registered = set(registry_names())
    except Exception as exc:  # noqa: BLE001 -- gate must report, not crash
        return {
            "ok": False, "missing": list(required),
            "detail": f"capability import failed: {exc}",
        }
    missing = [name for name in required if name not in registered]
    return {
        "ok": not missing,
        "missing": missing,
        "checked": list(required),
        "detail": (
            "" if not missing
            else f"missing registered capabilities: {missing}"
        ),
    }


def _discover_tests(repo_root: Path) -> list[str]:
    tests_dir = repo_root / "tests"
    found: list[str] = []
    if tests_dir.is_dir():
        for name in KNOWN_REGRESSION_TESTS:
            if (tests_dir / name).is_file():
                found.append(str(tests_dir / name))
    return found


def _probe_writable(location: Path) -> dict[str, Any]:
    try:
        location.mkdir(parents=True, exist_ok=True)
        probe = location / ".launch_gate_probe"
        probe.write_text("probe", encoding="utf-8")
        ok = probe.read_text(encoding="utf-8") == "probe"
        probe.unlink()
        return {"ok": ok, "detail": "" if ok else "probe readback mismatch"}
    except OSError as exc:
        return {"ok": False, "detail": f"{location}: {exc}"}


def check_launch(
    *,
    repo_root: Path | None = None,
    project_root: Path | None = None,
    regression_tests: list[str] | None = None,
    required_capabilities: tuple[str, ...] = REQUIRED_CAPABILITIES,
) -> dict[str, Any]:
    """Run every gate check and return the readiness report.

    ``project_root`` is the project whose snapshots/ledger are
    checked; when omitted it defaults to ``repo_root`` (a repo root
    normally has no snapshots, so that default is expected to fail
    the rollback check honestly -- pass an explicit project).
    """
    repo = _repo_root(repo_root)
    project = Path(project_root) if project_root is not None else repo
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    commit_info = _read_commit(repo)
    checks.append({
        "name": "version_commit", "ok": commit_info["ok"],
        "commit": commit_info.get("commit"),
        "version": commit_info.get("version"),
        "detail": commit_info.get("detail", ""),
    })
    if not commit_info["ok"]:
        failures.append("version_commit: commit hash not readable")

    cap_info = _check_capabilities(required_capabilities)
    checks.append({
        "name": "capabilities", "ok": cap_info["ok"],
        "missing": cap_info["missing"],
        "checked": cap_info["checked"],
        "detail": cap_info["detail"],
    })
    if not cap_info["ok"]:
        failures.append(
            f"capabilities: missing {cap_info['missing']}"
        )

    tests = list(regression_tests) if regression_tests is not None \
        else _discover_tests(repo)
    tests_ok = bool(tests)
    checks.append({
        "name": "regression_tests", "ok": tests_ok,
        "tests": tests,
        "detail": (
            "listed only; the gate does not run the suite"
            if tests_ok else "no P0/P1P2 regression test files listed"
        ),
    })
    if not tests_ok:
        failures.append("regression_tests: no regression tests listed")

    snapshot_dir = project / "snapshots"
    ledger_path = project / "spend_ledger.json"
    snap_probe = _probe_writable(snapshot_dir)
    ledger_probe = _probe_writable(ledger_path.parent)
    io_ok = snap_probe["ok"] and ledger_probe["ok"]
    checks.append({
        "name": "snapshot_ledger_io", "ok": io_ok,
        "snapshot_dir": str(snapshot_dir),
        "ledger_path": str(ledger_path),
        "detail": "; ".join(
            d for d in (snap_probe["detail"], ledger_probe["detail"]) if d
        ),
    })
    if not io_ok:
        failures.append(
            "snapshot_ledger_io: snapshot dir or ledger location not writable"
        )

    from hevi.capabilities.project_snapshot import list_snapshots
    snaps = list_snapshots(project)
    rollback_ok = bool(snaps)
    rollback_id = snaps[0]["snapshot_id"] if snaps else None
    checks.append({
        "name": "rollback_point", "ok": rollback_ok,
        "rollback_snapshot_id": rollback_id,
        "snapshot_count": len(snaps),
        "detail": (
            "" if rollback_ok
            else "no snapshot exists; there is no previous state to roll back to"
        ),
    })
    if not rollback_ok:
        failures.append("rollback_point: no snapshot exists")

    return {
        "capability": "pipeline.launch_gate",
        "ready": not failures,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_root": str(repo),
        "project_root": str(project),
        "commit": commit_info.get("commit"),
        "version": commit_info.get("version"),
        "checks": checks,
        "failures": failures,
        "note": (
            "Gate and report only: this module performs no production "
            "deployment, no push and no container operation."
        ),
    }


def write_report(report: dict[str, Any], output_path: Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_launch(
        repo_root=Path(params["repo_root"]) if params.get("repo_root") else None,
        project_root=Path(params["project_root"]) if params.get("project_root") else None,
        regression_tests=params.get("regression_tests"),
    )
    report_path = write_report(report, out_dir / "launch_readiness.json")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": report},
    )


def register_launch_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.launch_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "repo_root": {"type": "string"},
                    "project_root": {"type": "string"},
                    "regression_tests": {"type": "array",
                                         "items": {"type": "string"}},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Launch readiness gate (report only, never a deployment): "
                "version/commit readable, required capabilities "
                "importable and registered, P0/P1P2 regression tests "
                "listable, snapshot and ledger locations readable and "
                "writable, and a rollback snapshot present. Any failing "
                "check makes ready False and lists the failures."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.launch_gate"]


register_launch_gate_capabilities_once()

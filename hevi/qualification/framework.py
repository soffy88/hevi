"""Discovery and evidence contracts for the Studio production lines."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

STATUSES = {
    "PRODUCTION_COMPLETE", "QUALIFIED", "PARTIAL", "BLOCKED_PROVIDER",
    "BLOCKED_HARDWARE", "FAILED",
}
HIGH_RANDOMNESS_LINES = {
    "cinematic", "reference_adapt", "character_animation", "talking_head",
    "avatar_spokesperson", "localization_dub",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hardware_available() -> bool:
    try:
        result = subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _provider_needs(recipe: dict[str, Any]) -> list[str]:
    tools = set(recipe.get("tools", []))
    providers: list[str] = []
    if recipe.get("render_runtime") in {"remotion", "hyperframes", "manim"}:
        providers.append(recipe["render_runtime"])
    if any("h3" in tool or "avatar" in tool for tool in tools):
        providers.append("h3_local")
    if any(tool.startswith(("score.", "research.", "script.")) for tool in tools):
        providers.append("llm")
    if any(tool.startswith(("tts.", "audio.", "dub.")) for tool in tools):
        providers.append("tts")
    if any(tool.startswith(("material.", "watch.", "ingest.")) for tool in tools):
        providers.append("media_source")
    return sorted(set(providers))


def _base_report(line: str, recipe: dict[str, Any], evidence_root: Path) -> dict[str, Any]:
    provider_required = _provider_needs(recipe)
    hardware_line = "h3_local" in provider_required
    provider_available = bool(os.getenv("HEVI_QUALIFICATION_REAL"))
    hardware_available = _hardware_available() if hardware_line else True
    blockers: list[str] = []
    status = "BLOCKED_PROVIDER"
    if hardware_line and not hardware_available:
        status = "BLOCKED_HARDWARE"
        blockers.append("nvidia-smi/CUDA unavailable for required local provider")
    elif not provider_available:
        blockers.append("real provider qualification not enabled; no mock accepted")
    else:
        blockers.append("real artifact evidence not supplied")
    checks = {
        "recipe_complete": bool(recipe.get("pipeline", {}).get("stages")) and bool(recipe.get("slots") is not None),
        "runtime_complete": bool(recipe.get("render_runtime")),
        "provider_available": provider_available and hardware_available,
        "real_e2e": False,
        "final_artifact": False,
        "ffprobe_valid": False,
        "media_quality": False,
        "provenance_complete": False,
        "retry_verified": False,
        "observability_complete": False,
        "security_gate": False,
    }
    completeness = round(100 * sum(checks.values()) / len(checks))
    return {
        "line": line,
        **checks,
        "completeness_percent": completeness,
        "provider_required": provider_required,
        "provider": provider_required,
        "quality_gate": "BLOCKED",
        "status": status,
        "blockers": blockers,
        "evidence": {
            "recipe_sha256": _sha256(Path(recipe["_source"])) if recipe.get("_source") else None,
            "evidence_root": str(evidence_root),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "hardware_probe": hardware_available,
            "real_mode": provider_available,
        },
    }


def discover_reports(lines_dir: Path, evidence_root: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(lines_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not raw.get("id"):
            raise ValueError(f"invalid line YAML: {path}")
        raw["_source"] = str(path)
        reports.append(_base_report(str(raw["id"]), raw, evidence_root))
    return reports


def write_reports(reports: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    for report in reports:
        line_dir = output / report["line"]
        line_dir.mkdir(parents=True, exist_ok=True)
        (line_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {status: sum(item["status"] == status for item in reports) for status in sorted(STATUSES)}
    summary = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "total": len(reports), "counts": counts, "lines": reports}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary

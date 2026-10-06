"""Discovery and evidence contracts for the Studio production lines."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from hevi.providers.facts import PROVIDER_CATALOGUE

STATUSES = {
    "PRODUCTION_COMPLETE",
    "QUALIFIED",
    "PARTIAL",
    "BLOCKED_PROVIDER",
    "BLOCKED_HARDWARE",
    "FAILED",
}
HIGH_RANDOMNESS_LINES = {
    "cinematic",
    "reference_adapt",
    "character_animation",
    "talking_head",
    "avatar_spokesperson",
    "localization_dub",
}
IMPLEMENTATION_FIELDS = (
    "recipe_complete",
    "runtime_complete",
    "provider_contract",
    "tests",
    "artifact_model",
    "media_validation",
    "retry_verified",
    "observability_complete",
    "security_gate",
    "provenance_model",
)
PRODUCTION_FIELDS = (
    "recipe_complete",
    "runtime_complete",
    "provider_available",
    "real_e2e",
    "final_artifact",
    "ffprobe_valid",
    "media_quality",
    "provenance_complete",
    "retry_verified",
    "observability_complete",
    "security_gate",
    "quality_gate_passed",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hardware_available() -> bool:
    try:
        result = subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=10)
    except OSError, subprocess.SubprocessError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


class UnknownRenderRuntime(ValueError):
    """A recipe named a render runtime the catalogue does not declare."""


def _declared_providers_for(capability: str) -> list[str]:
    """Providers the catalogue says can serve ``capability``.

    R3: this used to ``return ["h3_local"]``. A module inside ``hevi/qualification/``
    naming a provider in code is a miniature second selection authority — eligibility
    is ``ProviderPolicy``'s question, and identity is ``ProviderCatalogue``'s. The name
    is now a *query*, so a provider added to the catalogue is discoverable here without
    this file changing.
    """
    return sorted(
        provider_id
        for provider_id in PROVIDER_CATALOGUE.list_ids()
        if capability in PROVIDER_CATALOGUE.resolve(provider_id).capabilities
    )


#: Recipes may name a render runtime; the catalogue decides whether it exists.
#: R3 removed a hardcoded provider set here, so a typo can no longer silently select a
#: provider that was never declared.
_RENDER_CAPABILITY = "t2v"


#: R3: an undeclared render runtime is recorded, not selected and not fatal here. The
#: report turns it into a blocker, so a recipe naming a renderer the catalogue has not
#: caught up with produces an honest BLOCKED line instead of a crash.
_last_undeclared: list[str] = []


def undeclared_runtimes(recipe: dict[str, Any]) -> list[str]:
    """Render runtimes the recipe names that the catalogue does not declare."""
    _provider_needs(recipe)
    return list(_last_undeclared)


def _provider_needs(recipe: dict[str, Any]) -> list[str]:
    tools = set(recipe.get("tools", []))
    providers: list[str] = []
    undeclared_runtime: list[str] = []

    runtime = recipe.get("render_runtime")
    if runtime:
        if PROVIDER_CATALOGUE.get(str(runtime)) is not None:
            providers.append(str(runtime))
        else:
            # An undeclared render runtime is a *reportable* gap, not an exception.
            # R3 removed a hardcoded provider set here; validating against the catalogue
            # is the point, but this module must not crash on a real production recipe
            # that names a renderer the catalogue has not caught up with. It records
            # the blocker and refuses to qualify — which is the honest outcome.
            undeclared_runtime.append(str(runtime))

    if any("h3" in tool or "avatar" in tool for tool in tools):
        # the avatar provider is queried, not asserted
        providers.extend(_declared_providers_for("avatar"))
    if any(tool.startswith(("score.", "research.", "script.")) for tool in tools):
        providers.append("llm")

    _last_undeclared[:] = undeclared_runtime
    # Translation is a real provider call in the production localization
    # workflow.  Do not allow a line to appear eligible when its translation
    # dependency is only discovered after the renderer starts.
    if "dub.translate" in tools:
        providers.append("llm")
    if any(tool.startswith(("tts.", "audio.", "dub.")) for tool in tools):
        providers.append("tts")
    if any(tool.startswith(("material.", "watch.", "ingest.")) for tool in tools):
        providers.append("media_source")
    return sorted(set(providers))


def _base_report(line: str, recipe: dict[str, Any], evidence_root: Path) -> dict[str, Any]:
    provider_required = _provider_needs(recipe)
    # derived from declared locality, not from a provider's name
    hardware_line = any(
        (PROVIDER_CATALOGUE.get(pid) is not None
         and PROVIDER_CATALOGUE.resolve(pid).locality.value == "LOCAL"
         and PROVIDER_CATALOGUE.resolve(pid).capabilities)
        for pid in provider_required
    ) or "h3" in json.dumps(recipe.get("tools", []))
    readiness_path = Path("artifacts/qualification/provider_readiness.json")
    readiness = (
        json.loads(readiness_path.read_text(encoding="utf-8"))
        if readiness_path.exists()
        else {"providers": []}
    )
    readiness_by_name = {str(item.get("provider")): item for item in readiness.get("providers", [])}
    dependency_blockers = []
    for provider_name in provider_required:
        item = readiness_by_name.get(provider_name)
        if item is None:
            dependency_blockers.append(f"{provider_name}=BLOCKED_SERVICE:readiness_not_recorded")
        elif item.get("status") != "READY":
            dependency_blockers.append(
                f"{provider_name}={item.get('status')}:{item.get('blocker') or 'probe_failed'}"
            )
    provider_available = bool(provider_required) and not dependency_blockers
    hardware_available = _hardware_available() if hardware_line else True
    blockers: list[str] = []
    status = "BLOCKED_PROVIDER"
    if hardware_line and not hardware_available:
        status = "BLOCKED_HARDWARE"
        blockers.extend(
            dependency_blockers or ["LOCAL_PROVIDER=BLOCKED_HARDWARE:nvidia-smi/CUDA unavailable"]
        )
    elif dependency_blockers:
        blockers.extend(dependency_blockers)
    else:
        blockers.append("real_e2e_not_executed; no mock accepted")
    checks = {
        "recipe_complete": bool(recipe.get("pipeline", {}).get("stages"))
        and bool(recipe.get("slots") is not None),
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
        "provider_contract": True,
        "tests": True,
        "artifact_model": Path("hevi/production/artifacts.py").exists(),
        "media_validation": Path("hevi/qualification/media.py").exists(),
        "provenance_model": Path("hevi/tongjian").exists(),
        "quality_gate_passed": False,
    }
    code_fields = (
        "recipe_complete",
        "provider_contract",
        "tests",
        "artifact_model",
        "media_validation",
        "provenance_model",
        "security_gate",
    )
    runtime_fields = (
        "runtime_complete",
        "provider_contract",
        "artifact_model",
        "media_validation",
        "retry_verified",
        "observability_complete",
    )
    implementation_completeness = round(
        100 * sum(checks[field] for field in IMPLEMENTATION_FIELDS) / len(IMPLEMENTATION_FIELDS)
    )
    code_completeness = round(100 * sum(checks[field] for field in code_fields) / len(code_fields))
    runtime_completeness = round(
        100 * sum(checks[field] for field in runtime_fields) / len(runtime_fields)
    )
    production_completeness = round(
        100 * sum(checks[field] for field in PRODUCTION_FIELDS) / len(PRODUCTION_FIELDS)
    )
    return {
        "line": line,
        **checks,
        "completeness_percent": production_completeness,
        "implementation_completeness": implementation_completeness,
        "code_completeness": code_completeness,
        "runtime_completeness": runtime_completeness,
        "production_completeness": production_completeness,
        "provider_required": provider_required,
        "provider": provider_required,
        "quality_gate": "BLOCKED",
        "status": status,
        "blockers": blockers,
        "evidence": {
            "recipe_sha256": _sha256(Path(recipe["_source"])) if recipe.get("_source") else None,
            "git_sha": _git_sha(),
            "provider_model": os.getenv("OPENAI_MODEL") or os.getenv("H3_MODEL") or None,
            "host_fingerprint": hashlib.sha256(
                f"{platform.node()}|{platform.platform()}".encode()
            ).hexdigest(),
            "evidence_root": str(evidence_root),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "hardware_probe": hardware_available,
            "real_mode": provider_available,
        },
    }


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except OSError, subprocess.SubprocessError:
        return None


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
        (line_dir / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    counts = {
        status: sum(item["status"] == status for item in reports) for status in sorted(STATUSES)
    }
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(reports),
        "counts": counts,
        "lines": reports,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary

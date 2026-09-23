#!/usr/bin/env python3
"""Fail-closed environment doctor for the qualification ML import chain.

Root cause this locks down: torchvision installed with a build that does not
match the locked torch (baseline failure: torchvision 0.29.0 against
torch==2.12.0) dies inside ``transformers.image_utils`` with
``RuntimeError: operator torchvision::nms does not exist``, which transformers
surfaces as ``ModuleNotFoundError: Could not import module 'modeling_utils'``.
That single mismatch broke provider registration and every pipeline fixture
setup (baseline: 84 setup errors + 8 provider failures + 6 studio failures
later reclassified from PRE_EXISTING to ENVIRONMENT).

transformers guards the import with ``is_torchvision_available()``, so
torchvision ABSENT is safe and torchvision PRESENT-BUT-BROKEN is not. The
doctor therefore fails only on an installed-but-incompatible torchvision.

Status vocabulary matches docs/VIDEO-INTELLIGENCE-FINAL-CLOSURE.md:
  PASS        software chain healthy
  FAIL        software chain broken (exit 1)
  ENV_BLOCKED hardware/tool absent; classified, reported, does not fail exit
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _record(name: str, status: str, detail: str) -> dict[str, str]:
    return {"check": name, "status": status, "detail": detail}


def _check_torch() -> dict[str, str]:
    try:
        import torch

        return _record("torch", "PASS", f"torch=={torch.__version__}")
    except Exception as exc:
        return _record("torch", "FAIL", f"{type(exc).__name__}: {exc}")


def _check_torchvision_consistency(torch_version: str) -> dict[str, str]:
    spec = importlib.util.find_spec("torchvision")
    if spec is None:
        return _record(
            "torchvision_consistency",
            "PASS",
            "torchvision absent (optional; transformers guards the import)",
        )
    try:
        import torchvision
        from torchvision.ops import nms  # noqa: F401 — the baseline crash site

        pinned = ""
        try:
            from importlib import metadata

            requires = metadata.requires("torchvision") or []
            pinned = next((r for r in requires if r.startswith("torch")), "")
        except Exception:
            pinned = ""
        base = torch_version.split("+")[0]
        if pinned and base not in pinned:
            return _record(
                "torchvision_consistency",
                "FAIL",
                f"torchvision=={torchvision.__version__} requires {pinned}, "
                f"installed torch=={torch_version}",
            )
        return _record(
            "torchvision_consistency",
            "PASS",
            f"torchvision=={torchvision.__version__} matches torch=={torch_version} "
            f"(nms import ok; {pinned or 'no torch pin found'})",
        )
    except Exception as exc:
        return _record(
            "torchvision_consistency",
            "FAIL",
            f"torchvision=={getattr(sys.modules.get('torchvision'), '__version__', '?')} "
            f"installed but broken: {type(exc).__name__}: {exc}",
        )


def _check_module(name: str) -> dict[str, str]:
    try:
        importlib.import_module(name)

        return _record(name, "PASS", "import ok")
    except Exception as exc:
        return _record(name, "FAIL", f"{type(exc).__name__}: {exc}")


def _check_vibevoice_patch() -> dict[str, str]:
    try:
        from hevi.audio.vibevoice_patch import patch_vibevoice_exports

        patch_vibevoice_exports()
        return _record("vibevoice_patch", "PASS", "patch_vibevoice_exports ok")
    except Exception as exc:
        return _record("vibevoice_patch", "FAIL", f"{type(exc).__name__}: {exc}")


def _check_provider_registration() -> dict[str, str]:
    try:
        from hevi.providers.registry import register_all_providers

        register_all_providers()
        return _record("provider_registration", "PASS", "register_all_providers ok")
    except Exception as exc:
        return _record("provider_registration", "FAIL", f"{type(exc).__name__}: {exc}")


def _check_media_tools() -> dict[str, str]:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        return _record("ffmpeg_ffprobe", "FAIL", f"missing on PATH: {', '.join(missing)}")
    return _record("ffmpeg_ffprobe", "PASS", "ffmpeg and ffprobe on PATH")


def _check_cuda() -> dict[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return _record("cuda", "PASS", f"cuda available: {torch.cuda.get_device_name(0)}")
    except Exception as exc:
        return _record("cuda", "ENV_BLOCKED", f"{type(exc).__name__}: {exc}")
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return _record("cuda", "ENV_BLOCKED", "nvidia-smi absent; torch CPU-only")
    try:
        proc = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=10)
        detail = (proc.stdout or proc.stderr or "").strip().splitlines()
        return _record(
            "cuda",
            "ENV_BLOCKED",
            f"torch reports no CUDA (nvidia-smi rc={proc.returncode}: "
            f"{detail[0] if detail else 'no output'})",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _record("cuda", "ENV_BLOCKED", f"nvidia-smi failed: {type(exc).__name__}: {exc}")


def _check_hyperframes_cli() -> dict[str, str]:
    configured = os.environ.get("HYPERFRAMES_BIN") or shutil.which("hyperframes")
    if not configured:
        return _record(
            "hyperframes_cli",
            "ENV_BLOCKED",
            "hyperframes binary not on PATH and HYPERFRAMES_BIN unset "
            "(HYPERFRAMES_CLI_UNAVAILABLE)",
        )
    return _record("hyperframes_cli", "PASS", f"hyperframes at {configured}")


def run_doctor() -> dict[str, Any]:
    torch_status = _check_torch()
    torch_version = torch_status["detail"].removeprefix("torch==")
    checks = [
        torch_status,
        _check_torchvision_consistency(torch_version if torch_status["status"] == "PASS" else ""),
        _check_module("transformers.modeling_utils"),
        _check_vibevoice_patch(),
        _check_provider_registration(),
        _check_media_tools(),
        _check_cuda(),
        _check_hyperframes_cli(),
    ]
    summary = {"PASS": 0, "FAIL": 0, "ENV_BLOCKED": 0}
    for item in checks:
        summary[item["status"]] = summary.get(item["status"], 0) + 1
    software_gate = "FAIL" if summary.get("FAIL") else "PASS"
    return {
        "doctor": "environment",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(ROOT),
        "checks": checks,
        "summary": summary,
        "software_gate": software_gate,
        "classification": {
            "ENV_BLOCKED": [c["check"] for c in checks if c["status"] == "ENV_BLOCKED"],
            "note": (
                "ENV_BLOCKED entries are hardware/tooling gaps classified for the "
                "final acceptance report; they do not fail the software gate."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the full report to this path")
    args = parser.parse_args()

    report = run_doctor()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    for item in report["checks"]:
        print(f"[{item['status']:>11}] {item['check']}: {item['detail']}", file=sys.stderr)
    print(f"software_gate={report['software_gate']}", file=sys.stderr)
    return 1 if report["software_gate"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())

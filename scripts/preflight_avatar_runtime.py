#!/usr/bin/env python3
"""Deterministic EchoMimic/ComfyUI preflight and managed bootstrap.

This probe never declares an avatar provider ready from a connection error. It
reports each installation boundary separately and can start the managed
runtime when ``--start`` is supplied by the production provider.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path(os.getenv("ECHO_MIMIC_COMFY_ROOT", "/home/soffy/ComfyUI"))
WORKFLOW = REPO / "hevi/providers/echo_mimic/workflows/echomimic_v2_10g.json"
URL = os.getenv("ECHO_MIMIC_COMFY_URL", os.getenv("H3_COMFY_URL", "http://127.0.0.1:8188"))


def _python(root: Path) -> tuple[Path | None, str]:
    candidates = [
        Path(os.getenv("HEVI_COMFY_PYTHON", "")),
        root / "venv/bin/python",
        REPO / ".venv/bin/python",
    ]
    for candidate in candidates:
        if str(candidate) and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate, "valid"
    return None, "no executable Python found"


def _health(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/system_stats", timeout=3) as response:
            return response.status == 200, f"HTTP_{response.status}"
    except Exception as exc:  # noqa: BLE001 - preflight must report exact class
        return False, type(exc).__name__


def collect(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    py, py_detail = _python(root)
    venv_cfg = root / "venv/pyvenv.cfg"
    custom_node = root / "custom_nodes/EchoMimicV2-ComfyUI"
    model_paths = [root / "models", root / "models/checkpoints", root / "models/diffusion_models"]
    reachable, health_detail = _health(URL)
    runtime_imports: dict[str, bool] = {}
    if py:
        probe = subprocess.run(
            [str(py), "-c", "import torch, comfy_aimdo, aiohttp; print(torch.cuda.is_available())"],
            capture_output=True, text=True, timeout=20,
        )
        runtime_imports = {
            "torch": "torch" in probe.stdout or "torch" not in probe.stderr,
            "comfy_aimdo": "comfy_aimdo" not in probe.stderr,
            "aiohttp": "aiohttp" not in probe.stderr,
            "cuda": probe.returncode == 0 and probe.stdout.strip().endswith("True"),
        }
    return {
        "COMFYUI_INSTALLATION_DISCOVERED": (root / "main.py").is_file(),
        "PYTHON_EXECUTABLE": str(py) if py else None,
        "PYTHON_EXECUTABLE_VALID": py is not None,
        "VENV_VALID": py is not None and venv_cfg.is_file(),
        "VENV_CONFIG": str(venv_cfg),
        "RUNTIME_DEPENDENCIES_VALID": bool(runtime_imports) and all(runtime_imports.values()),
        "RUNTIME_IMPORTS": runtime_imports,
        "CUSTOM_NODES_VALID": custom_node.is_dir() and any(custom_node.iterdir()),
        "CUSTOM_NODE_PATH": str(custom_node),
        "MODEL_PATHS_VALID": any(path.is_dir() and any(path.iterdir()) for path in model_paths),
        "MODEL_PATHS": [str(path) for path in model_paths],
        "ECHOMIMIC_WORKFLOW_LOAD": WORKFLOW.is_file(),
        "COMFYUI_URL": URL,
        "COMFYUI_HEALTH": reachable,
        "COMFYUI_HEALTH_DETAIL": health_detail,
        "COMFYUI_BOOT": reachable,
    }


def start(root: Path) -> dict[str, Any]:
    py, _ = _python(root)
    launcher = root / "start-echomimic.sh"
    if not py or not launcher.is_file():
        return {"started": False, "start_error": "launcher_or_python_missing"}
    env = os.environ.copy()
    env["HEVI_COMFY_PYTHON"] = str(py)
    log = Path("/tmp/hevi-h3"); log.mkdir(parents=True, exist_ok=True)
    with (log / "comfyui-managed.log").open("ab") as handle:
        subprocess.Popen(["bash", str(launcher)], cwd=root, env=env, stdout=handle, stderr=handle, start_new_session=True)
    for _ in range(60):
        ok, detail = _health(URL)
        if ok:
            return {"started": True, "health": detail}
        time.sleep(1)
    return {"started": False, "start_error": "boot_timeout", "health": detail}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = collect()
    if args.start and not payload["COMFYUI_HEALTH"]:
        payload["BOOT_ATTEMPT"] = start(DEFAULT_ROOT)
        payload.update(collect())
    payload["READY"] = all(payload[key] for key in (
        "COMFYUI_INSTALLATION_DISCOVERED", "PYTHON_EXECUTABLE_VALID", "VENV_VALID",
        "RUNTIME_DEPENDENCIES_VALID", "CUSTOM_NODES_VALID", "MODEL_PATHS_VALID",
        "COMFYUI_HEALTH", "ECHOMIMIC_WORKFLOW_LOAD",
    ))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["READY"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

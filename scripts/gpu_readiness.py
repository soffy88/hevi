#!/usr/bin/env python3
"""Fail-closed GPU/ComfyUI readiness probe with explicit hardware diagnostics."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _run(command: list[str], timeout: int = 10) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": None, "stdout": "", "stderr": type(exc).__name__}


def _comfy(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/system_stats", timeout=3) as response:
            return True, f"HTTP_{response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP_{exc.code}"
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, type(exc).__name__


def collect() -> dict[str, Any]:
    lspci = _run(["lspci"]) if shutil.which("lspci") else {"returncode": None, "stdout": "", "stderr": "lspci unavailable"}
    nvidia = _run(["nvidia-smi", "-q"], timeout=20) if shutil.which("nvidia-smi") else {"returncode": None, "stdout": "", "stderr": "nvidia-smi unavailable"}
    xid_text = "\n".join(part for part in (nvidia["stdout"], nvidia["stderr"]) if part)
    if shutil.which("dmesg"):
        xid_text += "\n" + _run(["dmesg", "--level=err,warn"], timeout=10)["stdout"]
    xid_matches = sorted(set(re.findall(r"Xid[^\n]*?(?:79|154)", xid_text, re.IGNORECASE)))
    fallen_off_bus = "unable to determine the device handle" in xid_text.lower() or "no devices were found" in xid_text.lower()
    nvml = {"available": False, "error": None}
    try:
        ctypes.CDLL("libnvidia-ml.so.1")
        nvml = {"available": True, "error": None}
    except OSError as exc:
        nvml["error"] = str(exc)
    torch_probe: dict[str, Any] = {"available": False}
    if importlib.util.find_spec("torch"):
        try:
            import torch
            torch_probe = {"available": bool(torch.cuda.is_available()), "device_count": torch.cuda.device_count(), "devices": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}
        except Exception as exc:  # probe must report, never hide host failure
            torch_probe = {"available": False, "error": type(exc).__name__}
    comfy_url = os.getenv("H3_COMFY_URL", "http://127.0.0.1:8188")
    comfy_ok, comfy_detail = _comfy(comfy_url)
    cuda_execution = {"allocation": False, "tensor_kernel": False, "vram_alloc_free": False, "error": "not_run"}
    if torch_probe.get("available"):
        try:
            import torch
            tensor = torch.ones((8, 8), device="cuda")
            result = tensor @ tensor
            cuda_execution = {"allocation": True, "tensor_kernel": bool(result.is_cuda), "vram_alloc_free": True, "error": None}
            del result, tensor
            torch.cuda.empty_cache()
        except Exception as exc:  # host probe must report execution failures
            cuda_execution["error"] = type(exc).__name__
    nvidia_ok = nvidia["returncode"] == 0
    blockers: list[str] = []
    if xid_matches:
        blockers.append("GPU_XID_79_OR_154")
    if fallen_off_bus:
        blockers.append("GPU_FALLEN_OFF_BUS_OR_DEVICE_HANDLE_UNKNOWN")
    if not nvidia_ok:
        blockers.append("NVIDIA_SMI_UNAVAILABLE")
    if not nvml["available"]:
        blockers.append("NVML_INITIALIZATION_FAILURE")
    if not torch_probe.get("available"):
        blockers.append("CUDA_RUNTIME_UNAVAILABLE")
    if not comfy_ok:
        blockers.append(f"COMFYUI_UNAVAILABLE:{comfy_detail}")
    strict_checks = {"nvidia_smi": nvidia_ok, "nvml": nvml["available"], "torch_cuda": bool(torch_probe.get("available")), "cuda_allocation": cuda_execution["allocation"], "tensor_kernel": cuda_execution["tensor_kernel"], "vram_alloc_free": cuda_execution["vram_alloc_free"], "comfyui_health": comfy_ok, "comfyui_minimal_workflow": False, "h3_model_readiness": False}
    strict_ready = all(strict_checks.values())
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "READY" if strict_ready and not xid_matches and not fallen_off_bus else "BLOCKED_HARDWARE", "blockers": blockers,
            "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"), "lspci_nvidia": "NVIDIA" in lspci["stdout"],
            "lspci": lspci, "nvidia_smi": {"returncode": nvidia["returncode"], "stderr": nvidia["stderr"], "summary": nvidia["stdout"][:2000]},
            "nvml": nvml, "torch": torch_probe, "cuda_execution": cuda_execution, "strict_checks": strict_checks, "comfyui": {"url": comfy_url, "reachable": comfy_ok, "detail": comfy_detail},
            "h3_runtime": {"module_present": Path("hevi/providers/h3_local").exists(), "comfy_client_present": Path("hevi/providers/h3_local/comfy_client.py").exists()},
            "xid_diagnostics": xid_matches}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification/gpu_readiness.json"))
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

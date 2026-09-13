#!/usr/bin/env python3
"""Collect read-only host diagnostics for a failed NVIDIA device."""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def _run(command: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"command": command, "returncode": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-4000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"command": command, "returncode": None, "stdout": "", "stderr": type(exc).__name__}


def collect() -> dict[str, Any]:
    lspci = _run(["lspci", "-nnk"]) if shutil.which("lspci") else {"stderr": "lspci unavailable"}
    gpu_lines = [line for line in str(lspci.get("stdout", "")).splitlines() if "NVIDIA" in line or "VGA compatible" in line]
    gpu_address = next((re.match(r"^([0-9a-f:.]+)\s", line, re.I).group(1) for line in gpu_lines if "NVIDIA" in line and re.match(r"^([0-9a-f:.]+)\s", line, re.I)), None)
    commands: dict[str, dict[str, Any]] = {
        "uname": {"stdout": platform.platform(), "command": ["uname", "-a"]},
        "lspci_nnk": lspci,
        "nvidia_smi": _run(["nvidia-smi"]) if shutil.which("nvidia-smi") else {"stderr": "unavailable"},
        "nvidia_smi_q": _run(["nvidia-smi", "-q"], timeout=30) if shutil.which("nvidia-smi") else {"stderr": "unavailable"},
        "lsmod_nvidia": _run(["bash", "-lc", "lsmod | grep nvidia"]) if shutil.which("lsmod") else {"stderr": "unavailable"},
        "modinfo_nvidia": _run(["modinfo", "nvidia"]) if shutil.which("modinfo") else {"stderr": "unavailable"},
        "dkms_status": _run(["dkms", "status"]) if shutil.which("dkms") else {"stderr": "unavailable"},
        "journal_kernel": _run(["journalctl", "-k", "-n", "500", "--no-pager"], timeout=20) if shutil.which("journalctl") else {"stderr": "unavailable"},
        "dmesg": _run(["dmesg", "--level=err,warn"]) if shutil.which("dmesg") else {"stderr": "unavailable"},
    }
    if gpu_address:
        commands["lspci_gpu_verbose"] = _run(["lspci", "-vv", "-s", gpu_address])
    proc_version = Path("/proc/driver/nvidia/version")
    commands["nvidia_proc_version"] = {"path": str(proc_version), "content": proc_version.read_text(encoding="utf-8", errors="replace") if proc_version.exists() else None}
    combined = "\n".join(json.dumps(value) for value in commands.values()).lower()
    if any(token in combined for token in ("xid 79", "xid 154", "fallen off the bus", "unable to determine the device handle")):
        diagnosis = "GPU_HARDWARE"
    elif "aer" in combined or ("pcie" in combined and "error" in combined):
        diagnosis = "PCIE_LINK_FAILURE"
    elif "dkms" in combined and ("error" in combined or "failed" in combined):
        diagnosis = "DKMS_KERNEL_MISMATCH"
    elif "driver/library version mismatch" in combined:
        diagnosis = "DRIVER_SOFTWARE"
    elif "cuda" in combined and "error" in combined:
        diagnosis = "CUDA_RUNTIME"
    elif "reboot" in combined:
        diagnosis = "REBOOT_REQUIRED"
    else:
        diagnosis = "UNKNOWN"
    torch_probe: dict[str, Any] = {"available": False}
    try:
        import torch
        torch_probe = {"available": bool(torch.cuda.is_available()), "device_count": torch.cuda.device_count()}
    except (ImportError, RuntimeError, OSError) as exc:
        torch_probe = {"available": False, "error": type(exc).__name__}
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "diagnosis": diagnosis, "gpu_address": gpu_address, "gpu_lines": gpu_lines, "commands": commands, "torch_cuda": torch_probe}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification/gpu_diagnostic.json"))
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(f"# GPU diagnostic\n\nDiagnosis: `{payload['diagnosis']}`\n\nGPU address: `{payload['gpu_address']}`\n\nCollected commands: {', '.join(payload['commands'])}\n", encoding="utf-8")
    print(json.dumps({"diagnosis": payload["diagnosis"], "gpu_address": payload["gpu_address"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

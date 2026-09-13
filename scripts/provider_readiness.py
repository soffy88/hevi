#!/usr/bin/env python3
"""Non-billable provider readiness inventory; never prints secret values."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _url_probe(url: str) -> tuple[bool, str]:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            return True, f"HTTP_{response.status}"
    except urllib.error.HTTPError as exc:
        return exc.code < 500, f"HTTP_{exc.code}"
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, type(exc).__name__


def _entry(name: str, *, configured: bool, secret_present: bool, endpoint: str | None,
           gpu_dependency: bool, capability: bool, blocker: str | None = None) -> dict[str, Any]:
    reachable, detail = _url_probe(endpoint) if endpoint else (capability, "local")
    status = "READY"
    if gpu_dependency and not _gpu_available():
        status, blocker = "BLOCKED_HARDWARE", "nvidia-smi/CUDA unavailable"
    elif not configured or not secret_present:
        status, blocker = "BLOCKED_SECRET", blocker or "required configuration/secret absent"
    elif not capability:
        status, blocker = "BLOCKED_CAPABILITY", blocker or "local capability not installed"
    elif endpoint and not reachable:
        status, blocker = "BLOCKED_NETWORK", blocker or f"endpoint probe failed: {detail}"
    return {
        "provider": name, "configured": configured, "secret_present": secret_present,
        "endpoint": endpoint, "endpoint_reachable": reachable, "auth_valid": None,
        "capability_available": capability, "readiness_probe": "non_billable_only",
        "gpu_dependency": gpu_dependency, "status": status, "blocker": blocker,
        "probe_detail": detail,
    }


def _gpu_available() -> bool:
    return shutil.which("nvidia-smi") is not None and os.system("nvidia-smi -L >/dev/null 2>&1") == 0


def collect() -> dict[str, Any]:
    comfy = os.getenv("H3_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
    dash_key = any(os.getenv(key) for key in ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY"))
    edge_tts = importlib.util.find_spec("edge_tts") is not None
    remotion = Path("hevi-remotion/package.json").exists() and shutil.which("node") is not None
    hyperframes = Path("hevi/providers/hyperframes").exists()
    ffmpeg = shutil.which("ffmpeg") is not None
    entries = [
        _entry("h3_local", configured=bool(os.getenv("H3_ROUTING")), secret_present=True,
               endpoint=comfy, gpu_dependency=True, capability=Path("hevi/providers/h3_local").exists()),
        _entry("ComfyUI/local_gpu_backend", configured=bool(os.getenv("H3_COMFY_URL")), secret_present=True,
               endpoint=comfy, gpu_dependency=True, capability=Path("hevi/providers/h3_local/comfy_client.py").exists()),
        _entry("llm", configured=dash_key, secret_present=dash_key,
               endpoint=None, gpu_dependency=False, capability=True),
        _entry("remotion", configured=remotion, secret_present=True,
               endpoint=None, gpu_dependency=False, capability=remotion),
        _entry("tts", configured=edge_tts, secret_present=True,
               endpoint=None, gpu_dependency=False, capability=edge_tts),
        _entry("media_source", configured=ffmpeg, secret_present=True,
               endpoint=None, gpu_dependency=False, capability=ffmpeg),
        _entry("hyperframes", configured=hyperframes, secret_present=True,
               endpoint=None, gpu_dependency=False, capability=hyperframes),
    ]
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "providers": entries}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification/provider_readiness.json"))
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = ["# Provider readiness", "", "| Provider | Status | Configured | Secret present | Endpoint | Blocker |", "|---|---|---|---|---|---|"]
    md.extend(
        f"| {item['provider']} | {item['status']} | {item['configured']} | {item['secret_present']} | {item['endpoint'] or 'local'} | {item['blocker'] or '—'} |"
        for item in payload["providers"]
    )
    args.output.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

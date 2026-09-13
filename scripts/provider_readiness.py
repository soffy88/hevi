#!/usr/bin/env python3
"""Run real, fail-closed readiness probes without printing secrets."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _url_probe(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=5) as response:
            return True, f"HTTP_{response.status}"
    except urllib.error.HTTPError as exc:
        return exc.code < 500, f"HTTP_{exc.code}"
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, type(exc).__name__


def _gpu_available() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _probe_hyperframes() -> dict[str, Any]:
    output = Path("/tmp/hevi-provider-probes/hyperframes-readiness.mp4")
    try:
        from hevi.providers.hyperframes.provider import hyperframes_generate
        output.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        asyncio.run(hyperframes_generate(prompt="HEVI readiness probe", output_path=output, duration_s=2))
        return {"passed": output.is_file() and output.stat().st_size > 0, "latency_ms": round((time.perf_counter() - started) * 1000), "artifact_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        return {"passed": False, "error": type(exc).__name__}


def _probe_remotion() -> dict[str, Any]:
    output = Path("/tmp/hevi-provider-probes/remotion-readiness.mp4")
    if not Path("hevi-remotion/node_modules").is_dir() or shutil.which("npx") is None:
        return {"passed": False, "error": "node_modules_or_npx_unavailable"}
    try:
        started = time.perf_counter()
        result = subprocess.run(["npx", "remotion", "render", "src/index.ts", "Zhibo", str(output), "--frames=0-1", "--log=error"], cwd="hevi-remotion", capture_output=True, text=True, timeout=180)
        passed = result.returncode == 0 and output.is_file() and output.stat().st_size > 0
        return {"passed": passed, "returncode": result.returncode, "latency_ms": round((time.perf_counter() - started) * 1000), "artifact_sha256": hashlib.sha256(output.read_bytes()).hexdigest() if passed else None, "error": None if passed else "render_failed"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"passed": False, "error": type(exc).__name__}


def _probe_tts() -> dict[str, Any]:
    if importlib.util.find_spec("edge_tts") is None:
        return {"passed": False, "error": "edge_tts_unavailable"}
    if os.getenv("HEVI_SKIP_REMOTE_PROBES") == "1":
        return {"passed": False, "error": "remote_probe_disabled"}
    output = Path("/tmp/hevi-provider-probes/tts-readiness.mp3")
    try:
        from edge_tts import Communicate
        output.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(Communicate("HEVI readiness probe", "en-US-AriaNeural").save(str(output)))
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(output)], capture_output=True, text=True, timeout=20)
        duration = float(probe.stdout.strip()) if probe.returncode == 0 and probe.stdout.strip() else 0.0
        return {"passed": duration > 0 and output.stat().st_size > 0, "duration_s": duration, "artifact_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return {"passed": False, "error": type(exc).__name__}


def _probe_media_source() -> dict[str, Any]:
    """Query Wikimedia Commons and freeze one openly licensed image."""
    query = "https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=public%20domain%20film&gsrnamespace=6&gsrlimit=5&prop=imageinfo&iiprop=url%7Cextmetadata&iiurlwidth=320&format=json"
    target = Path("/tmp/hevi-provider-probes/media-source-probe.bin")
    try:
        with urllib.request.urlopen(urllib.request.Request(query, headers={"User-Agent": "HEVI-provider-readiness/1.0"}), timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        pages = payload.get("query", {}).get("pages", {})
        target.parent.mkdir(parents=True, exist_ok=True)
        failures: list[dict[str, Any]] = []
        ordered_pages = sorted(pages.values(), key=lambda item: any(str((item.get("imageinfo") or [{}])[0].get(key, "")).lower().split("?")[0].endswith((".webm", ".mp4", ".mov")) for key in ("url", "thumburl")), reverse=True)
        for page in ordered_pages:
            info = (page.get("imageinfo") or [{}])[0]
            metadata = info.get("extmetadata") or {}
            candidates = (info.get("url"), info.get("thumburl")) if str(info.get("url", "")).lower().split("?")[0].endswith((".webm", ".mp4", ".mov")) else (info.get("thumburl"), info.get("url"))
            for url in candidates:
                if not url:
                    continue
                request = urllib.request.Request(str(url), headers={"User-Agent": "HEVI-provider-readiness/1.0", "Referer": "https://commons.wikimedia.org/"})
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        content_type = response.headers.get("content-type", "")
                        if not content_type.startswith(("image/", "video/")):
                            failures.append({"url_host": urllib.parse.urlparse(str(url)).hostname, "status": response.status, "content_type": content_type, "reason": "invalid_mime"})
                            continue
                        body = response.read(50 * 1024 * 1024 if content_type.startswith("video/") else 2 * 1024 * 1024)
                        target.write_bytes(body)
                        digest = hashlib.sha256(target.read_bytes()).hexdigest()
                        return {"passed": target.stat().st_size > 0, "provider": "wikimedia_commons", "source_url": str(url), "final_url": response.geturl(), "redirected": response.geturl() != str(url), "response_headers": {"content-type": content_type, "content-length": response.headers.get("content-length"), "server": response.headers.get("server")}, "referer_sent": True, "authorization_sent": False, "license_metadata_present": bool(metadata.get("LicenseShortName") or metadata.get("UsageTerms")), "local_frozen_path": str(target), "sha256": digest}
                except urllib.error.HTTPError as exc:
                    failures.append({"url_host": urllib.parse.urlparse(str(url)).hostname, "status": exc.code, "content_type": exc.headers.get("content-type"), "reason": "http_error"})
        return {"passed": False, "error": "HTTP_403" if any(item.get("status") == 403 for item in failures) else "CONTENT_UNAVAILABLE", "phase": "download", "url_host": "commons.wikimedia.org", "attempts": failures}
    except urllib.error.HTTPError as exc:
        return {"passed": False, "error": f"HTTP_{exc.code}", "phase": "download", "url_host": "commons.wikimedia.org", "http_status": exc.code}
    except (OSError, urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"passed": False, "error": type(exc).__name__}


def _local_llm_config() -> tuple[str, str, str, bool]:
    provider = os.getenv("HEVI_LLM_PROVIDER", "").strip().lower()
    base = (os.getenv("OPENAI_BASE_URL", "").strip() or os.getenv("LONGCAT_BASE_URL", "").strip()).rstrip("/")
    model = (os.getenv("OPENAI_MODEL", "").strip() or os.getenv("LONGCAT_MODEL", "").strip())
    key = os.getenv("OPENAI_API_KEY") or os.getenv("LONGCAT_API_KEY") or ""
    host = (urlsplit(base).hostname or "").lower()
    trusted_local = provider in {"openai_compatible", "local_openai_compatible"} and host in {"localhost", "127.0.0.1", "::1"}
    return base, model, key, trusted_local


def _probe_llm() -> dict[str, Any]:
    base, model, key, trusted_local = _local_llm_config()
    if not base:
        return {"passed": False, "error": "endpoint_missing"}
    if not model:
        return {"passed": False, "error": "model_missing"}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    elif not trusted_local:
        return {"passed": False, "error": "secret_missing"}
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "Reply with READY only."}], "max_tokens": 4}).encode("utf-8")
    request = urllib.request.Request(f"{base}/chat/completions", data=body, method="POST", headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"passed": bool(str(text).strip()), "latency_ms": round((time.perf_counter() - started) * 1000), "request_id_present": bool(response.headers.get("x-request-id") or payload.get("id")), "usage": payload.get("usage"), "model": payload.get("model", model), "auth_mode": "token" if key else "none", "error": None if text else "empty_response"}
    except urllib.error.HTTPError as exc:
        return {"passed": False, "error": f"HTTP_{exc.code}", "latency_ms": round((time.perf_counter() - started) * 1000), "http_status": exc.code}
    except (OSError, urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"passed": False, "error": type(exc).__name__}


def _entry(name: str, *, configured: bool, secret_present: bool, endpoint: str | None, gpu_dependency: bool, capability: bool, probe: dict[str, Any] | None = None) -> dict[str, Any]:
    reachable, detail = _url_probe(endpoint) if endpoint else (True, "local")
    status = "READY"
    blocker = None
    if gpu_dependency and not _gpu_available():
        status, blocker = "BLOCKED_HARDWARE", "nvidia-smi/CUDA unavailable"
    elif not configured or (not secret_present and not (probe and probe.get("auth_mode") == "none")):
        status, blocker = "BLOCKED_SECRET", "required configuration/secret absent"
    elif not capability:
        status, blocker = "BLOCKED_CAPABILITY", "provider capability unavailable"
    elif endpoint and not reachable:
        status, blocker = "BLOCKED_NETWORK", f"endpoint probe failed: {detail}"
    elif probe is not None and not probe.get("passed"):
        error = str(probe.get("error") or "real readiness probe failed")
        if name == "llm" and error in {"HTTP_401", "HTTP_403"}:
            status, blocker = "BLOCKED_AUTH", error
        elif name == "llm" and error in {"HTTP_404", "HTTP_400"}:
            status, blocker = "BLOCKED_MODEL", error
        elif error.startswith(("HTTP_", "URLError", "Timeout")):
            status, blocker = "UPSTREAM_FAILURE" if error.startswith(("HTTP_429", "HTTP_5")) else "BLOCKED_NETWORK", error
        else:
            status, blocker = "BLOCKED_SERVICE", error
    return {"provider": name, "configured": configured, "secret_present": secret_present, "endpoint": endpoint, "endpoint_reachable": reachable, "auth_valid": None, "capability_available": capability, "readiness_probe": probe or {"passed": False, "error": "not_run"}, "gpu_dependency": gpu_dependency, "status": status, "blocker": blocker}


def collect(provider_filter: str | None = None) -> dict[str, Any]:
    comfy = os.getenv("H3_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
    llm_base, llm_model, llm_key, llm_local = _local_llm_config()
    llm_secret = bool(llm_key)
    llm_configured = bool(llm_base and llm_model) and (llm_local or llm_secret)
    remotion_capable = Path("hevi-remotion/package.json").exists() and shutil.which("npx") is not None
    hyperframes_capable = Path("hevi/providers/hyperframes").exists() and shutil.which("ffmpeg") is not None
    ffmpeg_capable = shutil.which("ffmpeg") is not None
    tts_capable = importlib.util.find_spec("edge_tts") is not None
    llm_endpoint = llm_base or "https://api.openai.com/v1"
    entries = [
        _entry("h3_local", configured=bool(os.getenv("H3_ROUTING")), secret_present=True, endpoint=comfy, gpu_dependency=True, capability=Path("hevi/providers/h3_local").exists()),
        _entry("ComfyUI/local_gpu_backend", configured=bool(os.getenv("H3_COMFY_URL")), secret_present=True, endpoint=comfy, gpu_dependency=True, capability=Path("hevi/providers/h3_local/comfy_client.py").exists()),
        _entry("llm", configured=llm_configured, secret_present=llm_secret, endpoint=llm_endpoint, gpu_dependency=False, capability=True, probe=_probe_llm()),
        _entry("remotion", configured=remotion_capable, secret_present=True, endpoint=None, gpu_dependency=False, capability=remotion_capable, probe=_probe_remotion()),
        _entry("tts", configured=tts_capable, secret_present=True, endpoint=None, gpu_dependency=False, capability=tts_capable, probe=_probe_tts()),
        _entry("media_source", configured=ffmpeg_capable, secret_present=True, endpoint=None, gpu_dependency=False, capability=ffmpeg_capable, probe=_probe_media_source()),
        _entry("hyperframes", configured=hyperframes_capable, secret_present=True, endpoint=None, gpu_dependency=False, capability=hyperframes_capable, probe=_probe_hyperframes()),
    ]
    if provider_filter:
        entries = [item for item in entries if item["provider"] == provider_filter]
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "providers": entries}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification/provider_readiness.json"))
    parser.add_argument("--provider")
    parser.add_argument("--real", action="store_true", help="Run real probes; retained for explicit CI intent")
    args = parser.parse_args()
    payload = collect(args.provider)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = ["# Provider readiness", "", "| Provider | Status | Secret present | Probe | Blocker |", "|---|---|---|---|---|"]
    md.extend(f"| {item['provider']} | {item['status']} | {item['secret_present']} | {item['readiness_probe'].get('passed')} | {item['blocker'] or '—'} |" for item in payload["providers"])
    args.output.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

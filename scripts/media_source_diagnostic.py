#!/usr/bin/env python3
"""Layered, redacted media-source connectivity and asset-freeze diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

URL = "https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=public%20domain%20film&gsrnamespace=6&gsrlimit=5&prop=imageinfo&iiprop=url%7Cextmetadata&iiurlwidth=320&format=json"


def _dns(host: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        return {"passed": True, "addresses": addresses, "latency_ms": round((time.perf_counter() - started) * 1000)}
    except socket.gaierror as exc:
        return {"passed": False, "error": type(exc).__name__}


def _tcp_tls(host: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, 443), timeout=10) as raw, ssl.create_default_context().wrap_socket(raw, server_hostname=host) as secure:
            return {"passed": True, "tls_version": secure.version(), "cipher": secure.cipher()[0] if secure.cipher() else None, "latency_ms": round((time.perf_counter() - started) * 1000)}
    except (OSError, ssl.SSLError) as exc:
        return {"passed": False, "error": type(exc).__name__}


def _http() -> dict[str, Any]:
    started = time.perf_counter()
    request = urllib.request.Request(URL, method="GET", headers={"User-Agent": "HEVI-provider-readiness/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(65536)
            return {"passed": response.status < 400, "status": response.status, "content_type": response.headers.get("content-type"), "bytes": len(body), "latency_ms": round((time.perf_counter() - started) * 1000)}
    except urllib.error.HTTPError as exc:
        return {"passed": False, "status": exc.code, "response_category": "HTTP_4XX" if exc.code < 500 else "HTTP_5XX", "latency_ms": round((time.perf_counter() - started) * 1000)}
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {"passed": False, "error": type(exc).__name__, "latency_ms": round((time.perf_counter() - started) * 1000)}


def _search_download() -> dict[str, Any]:
    target = Path("/tmp/hevi-provider-probes/media-source-diagnostic.bin")
    try:
        with urllib.request.urlopen(URL, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        page = next(iter(payload.get("query", {}).get("pages", {}).values()), {})
        info = (page.get("imageinfo") or [{}])[0]
        source_url = str(info.get("thumburl") or info.get("url") or "")
        metadata = info.get("extmetadata") or {}
        if not source_url:
            return {"passed": False, "classification": "CONTENT_UNAVAILABLE"}
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(source_url, timeout=30) as response, target.open("wb") as stream:
            stream.write(response.read(2 * 1024 * 1024))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {"passed": target.stat().st_size > 0, "source_url": source_url, "license": bool(metadata.get("LicenseShortName") or metadata.get("UsageTerms")), "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "local_frozen_path": str(target), "sha256": digest}
    except urllib.error.HTTPError as exc:
        return {"passed": False, "classification": f"HTTP_{exc.code}"}
    except (OSError, urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"passed": False, "classification": type(exc).__name__}


def collect() -> dict[str, Any]:
    host = urlparse(URL).hostname or ""
    proxy = {key.lower(): value.split("@")[-1] for key, value in os.environ.items() if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
    payload: dict[str, Any] = {"provider": "wikimedia_commons", "url_host": host, "url_path": urlparse(URL).path, "proxy": proxy, "dns": _dns(host), "tcp_tls": _tcp_tls(host), "http": _http(), "auth": {"required": False, "status": "NOT_REQUIRED"}}
    http_result = payload["http"]
    if http_result.get("status") == 429:
        payload["classification"] = "HTTP_429"
    elif http_result.get("status") in {401, 403, 404}:
        payload["classification"] = f"HTTP_{http_result['status']}"
    elif not payload["dns"].get("passed"):
        payload["classification"] = "DNS_FAILURE"
    elif not payload["tcp_tls"].get("passed"):
        payload["classification"] = "TLS_FAILURE"
    elif not http_result.get("passed"):
        payload["classification"] = "TIMEOUT" if "Timeout" in str(http_result.get("error")) else "CONTENT_UNAVAILABLE"
    else:
        payload["classification"] = "READY"
    if payload["classification"] == "READY":
        payload["search"] = {"passed": True}
        payload["download"] = _search_download()
        if not payload["download"].get("passed"):
            payload["classification"] = payload["download"].get("classification", "CONTENT_UNAVAILABLE")
    else:
        payload["search"] = {"passed": False}
        payload["download"] = {"passed": False}
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification/media_source_diagnostic.json"))
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"classification": payload["classification"], "url_host": payload["url_host"], "http": payload["http"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

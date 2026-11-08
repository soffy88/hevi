#!/usr/bin/env python3
"""Tiny OpenAI-compatible proxy bound to the Docker bridge only.

Why: the free LLM channels inside the hevi containers are either dead
(``teamo`` TLS reset), misconfigured (``ollama`` base missing ``/v1``), or
missing one header (OpenCode Zen answers ``400 MissingSessionID`` without
``x-opencode-session``).  The host's OpenCode installation already has a valid
``opencode-go`` credential and can reach ``opencode-go/deepseek-v4.1-flash``.

This proxy runs on the host, listens only on a Docker bridge address, and
forwards ``POST /v1/chat/completions`` to the OpenCode Zen endpoint with the
required session header.  The container never sees the credential.

Config (env):
    HEVI_LLM_PROXY_HOSTS       comma list of bind addresses, default 172.17.0.1,172.20.0.1
    HEVI_LLM_PROXY_PORT        default 20129
    HEVI_HOST_LLM_ENDPOINT     default https://opencode.ai/zen/go/v1/chat/completions
    HEVI_HOST_LLM_MODEL        default deepseek-v4.1-flash
    HEVI_HOST_LLM_KEY          explicit key (else read from the auth file)
    HEVI_HOST_LLM_KEY_FILE     default ~/.local/share/opencode/auth.json
    HEVI_HOST_LLM_AUTH_KEY     default opencode-go
    HEVI_LLM_PROXY_TIMEOUT_S   default 90

No external dependencies: Python standard library only.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("hevi-llm-proxy")

ENDPOINT = os.getenv(
    "HEVI_HOST_LLM_ENDPOINT", "https://opencode.ai/zen/go/v1/chat/completions"
)
MODEL = os.getenv("HEVI_HOST_LLM_MODEL", "deepseek-v4.1-flash")
TIMEOUT = float(os.getenv("HEVI_LLM_PROXY_TIMEOUT_S", "90"))


def _key() -> str:
    explicit = os.getenv("HEVI_HOST_LLM_KEY", "").strip()
    if explicit:
        return explicit
    path = Path(
        os.getenv(
            "HEVI_HOST_LLM_KEY_FILE",
            str(Path.home() / ".local/share/opencode/auth.json"),
        )
    )
    auth_key = os.getenv("HEVI_HOST_LLM_AUTH_KEY", "opencode-go")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data.get(auth_key) or {}
        return str(entry.get("key") or entry.get("access") or "").strip()
    except Exception as exc:  # pragma: no cover - startup diagnostics
        log.error("cannot read %s: %s", path, exc)
        return ""


class Handler(BaseHTTPRequestHandler):
    server_version = "hevi-llm-proxy/1.0"
    session = uuid.uuid4().hex

    def log_message(self, fmt: str, *args: object) -> None:  # quiet default log
        log.debug(fmt, *args)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": MODEL, "object": "model", "owned_by": "opencode-go"}
                    ],
                },
            )
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": {"message": "only /v1/chat/completions"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            self._json(400, {"error": {"message": "invalid JSON body"}})
            return
        payload["model"] = str(payload.get("model") or MODEL)
        # The Zen gateway routes by exact model id; "opencode-go/..." is not a
        # valid upstream model name.
        payload["model"] = payload["model"].split("/")[-1]
        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_key()}",
                "x-opencode-session": os.getenv("HEVI_LLM_PROXY_SESSION", self.session),
                "User-Agent": "hevi-llm-proxy/1.0 (host bridge)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header(
                    "Content-Type", resp.headers.get("Content-Type", "application/json")
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            data = exc.read() or b"{}"
            self.send_response(exc.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            log.warning("upstream failed: %s", exc)
            self._json(502, {"error": {"message": f"upstream failed: {exc}"}})


def main() -> int:
    logging.basicConfig(
        level=os.getenv("HEVI_LLM_PROXY_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not _key():
        log.error("no host LLM credential available; refusing to start")
        return 1
    hosts = [
        part.strip()
        for part in os.getenv("HEVI_LLM_PROXY_HOSTS", "172.17.0.1,172.20.0.1").split(",")
        if part.strip()
    ]
    port = int(os.getenv("HEVI_LLM_PROXY_PORT", "20129"))
    servers = []
    for host in hosts:
        try:
            servers.append(ThreadingHTTPServer((host, port), Handler))
            log.info("listening on %s:%d", host, port)
        except OSError as exc:
            log.error("cannot bind %s:%d: %s", host, port, exc)
    if not servers:
        return 1
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Pluggable video-understanding backends."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from hevi.judge.types import BackendResult

AGY_BIN = "/home/soffy/.local/sgbin/agy"
GEMINI_BIN = "/snap/bin/gemini"


class VideoUnderstandingBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        ...


def _which(path: str) -> bool:
    import os
    if os.path.isabs(path):
        return Path(path).is_file() and os.access(path, os.X_OK)
    return shutil.which(path) is not None


@dataclass
class MockBackend:
    name: str = "mock"
    responses: list = None
    calls: int = 0

    def __post_init__(self):
        if self.responses is None:
            self.responses = []

    def available(self) -> bool:
        return True

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        self.calls += 1
        idx = self.calls - 1
        if idx < len(self.responses):
            val = self.responses[idx]
        else:
            val = self.responses[-1] if self.responses else {}
        if isinstance(val, Exception):
            raise val
        if isinstance(val, str):
            text = val
            raw = None
        else:
            text = json.dumps(val, ensure_ascii=False)
            raw = val
        return BackendResult(backend="mock", text=text, raw=raw, model="mock", calls=1)


class AgyBackend:
    name = "agy"

    def __init__(self, bin_path: str = AGY_BIN):
        self.bin_path = bin_path

    def available(self) -> bool:
        return _which(self.bin_path)

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        t0 = time.time()
        cmd = [self.bin_path, "--dangerously-skip-permissions", "--print"]
        if json_schema:
            cmd += ["--json-schema", json_schema]
        vp = str(Path(video_path).resolve())
        full_prompt = f"{prompt}\n\nVideo file: {vp}"
        cmd += ["--add-dir", str(Path(vp).parent), full_prompt]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"agy timeout after {timeout_s}s") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"agy failed: {proc.stderr.strip()[:500]}")
        text = proc.stdout.strip()
        raw = None
        try:
            raw = json.loads(text)
        except Exception:
            raw = None
        return BackendResult(backend="agy", text=text, raw=raw, model="agy",
                             elapsed_s=time.time() - t0)


class GeminiCliBackend:
    name = "gemini_cli"

    def __init__(self, bin_path: str = GEMINI_BIN):
        self.bin_path = bin_path

    def available(self) -> bool:
        return _which(self.bin_path)

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        t0 = time.time()
        vp = str(Path(video_path).resolve())
        cmd = [self.bin_path, "--skip-trust", "-y", "-p", f"{prompt}\n\nVideo: {vp}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"gemini timeout after {timeout_s}s") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"gemini failed: {proc.stderr.strip()[:500]}")
        text = proc.stdout.strip()
        raw = None
        try:
            raw = json.loads(text)
        except Exception:
            raw = None
        return BackendResult(backend="gemini_cli", text=text, raw=raw, model="gemini_cli",
                             elapsed_s=time.time() - t0)


class LocalMetricsBackend:
    name = "local"

    def available(self) -> bool:
        return True

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        return BackendResult(backend="local", text="", raw=None, model="local")


def select_backend(preferred=None, *, allow_mock=False):
    if preferred:
        p = preferred.lower()
        if p == "mock":
            return MockBackend()
        if p == "agy":
            return AgyBackend()
        if p in ("gemini", "gemini_cli"):
            return GeminiCliBackend()
        if p == "local":
            return LocalMetricsBackend()
    for b in (AgyBackend(), GeminiCliBackend()):
        if b.available():
            return b
    return LocalMetricsBackend()


def extract_json(text):
    import re
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None

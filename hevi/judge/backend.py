"""Pluggable video-understanding backends."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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


class OpencodeJudgeBackend:
    name = "opencode"

    def __init__(self, model: str = "opencode-go/crouton-alpha-free",
                 bin_path: str = "/snap/bin/opencode", timeout_s: int = 120):
        self.model = model
        self.bin_path = bin_path
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return _which(self.bin_path)

    def _build_contact_sheet(self, video_path, out_path):
        import subprocess as _sp
        cmd = ["ffmpeg", "-y", "-i", str(video_path),
               "-vf", "fps=1/2,scale=320:-1,tile=4x4", "-frames:v", "1", str(out_path)]
        _sp.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
        return Path(out_path).is_file()

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        import tempfile

        from hevi.judge.hard_checks import (
            _black_ratio,
            _freeze_count,
            _mean_volume,
            _repetition_ratio,
            probe_video,
        )

        t0 = time.time()
        vp = str(Path(video_path).resolve())
        tmpdir = Path(tempfile.mkdtemp(prefix="opencode_judge_"))
        contact = tmpdir / "contact.png"
        metrics = tmpdir / "metrics.txt"
        self._build_contact_sheet(vp, contact)
        info = probe_video(vp)
        lines = []
        lines.append(f"probe: {info}")
        mv = _mean_volume(vp)
        lines.append(f"mean_volume_db: {mv}")
        lines.append(f"black_ratio: {_black_ratio(vp):.4f}")
        lines.append(f"freeze_count: {_freeze_count(vp)}")
        lines.append(f"repetition_ratio: {_repetition_ratio(vp):.4f}")
        # sidecar subtitles
        sp = Path(vp).with_suffix(".srt")
        if not sp.is_file():
            sp2 = Path(vp).parent / (Path(vp).stem + ".srt")
            if sp2.is_file():
                sp = sp2
        if sp.is_file():
            import contextlib
            with contextlib.suppress(Exception):
                lines.append("subtitles:\n" + sp.read_text(encoding="utf-8", errors="ignore")[:4000])
        metrics.write_text("\n".join(lines), encoding="utf-8")

        full_prompt = prompt + "\n\nDo not run any tools or code. Answer directly with the requested JSON only."
        cmd = [self.bin_path, "run", "-m", self.model, full_prompt]
        if contact.is_file():
            cmd += ["-f", str(contact)]
        cmd += ["-f", str(metrics)]
        to = timeout_s if timeout_s else self.timeout_s
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=to)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"opencode timeout after {to}s") from exc
        text = (proc.stdout or "").strip()
        if proc.returncode != 0 and not text:
            raise RuntimeError(f"opencode failed: {(proc.stderr or '').strip()[:500]}")
        raw = None
        try:
            raw = json.loads(text)
        except Exception:
            raw = extract_json(text)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return BackendResult(backend="opencode", text=text, raw=raw, model=self.model,
                             calls=1, elapsed_s=time.time() - t0)

class LocalMetricsBackend:
    name = "local"

    def available(self) -> bool:
        return True

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        return BackendResult(backend="local", text="", raw=None, model="local")


class LocalJudgeBackend:
    """Pure-local pairwise judge: splits a composite A+B clip, hard-checks each half."""

    name = "local"

    def available(self) -> bool:
        return True

    def run(self, video_path, prompt, *, json_schema=None, timeout_s=300):
        import tempfile

        from hevi.judge.hard_checks import probe_video, run_hard_checks

        t0 = time.time()
        vp = str(Path(video_path).resolve())
        info = probe_video(vp)
        duration = float(info.get("duration") or 0.0)
        if duration <= 0:
            data = {"winner": "TIE", "reason": "cannot probe composite", "improvements": [],
                    "hard_defects": {"A": [], "B": []}}
            return BackendResult(backend="local", text=__import__("json").dumps(data, ensure_ascii=False),
                                 raw=data, model="local_metrics", calls=1, elapsed_s=time.time() - t0)
        half = duration / 2.0
        tmpdir = Path(tempfile.mkdtemp(prefix="judge_local_"))
        a_path = tmpdir / "A.mp4"
        b_path = tmpdir / "B.mp4"
        for outp, start in ((a_path, 0.0), (b_path, half)):
            cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", vp, "-t", f"{half:.3f}",
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac",
                   "-movflags", "+faststart", str(outp)]
            subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        ra = run_hard_checks(str(a_path)) if a_path.is_file() else None
        rb = run_hard_checks(str(b_path)) if b_path.is_file() else None

        def score(rep):
            if rep is None:
                return 0.0
            s = 100.0
            for f in rep.findings:
                if f.severity == "blocker":
                    s -= 40.0
                elif f.severity == "major":
                    s -= 15.0
                elif f.severity == "minor":
                    s -= 3.0
            return s

        sa = score(ra)
        sb = score(rb)
        defects = {
            "A": [f"{f.severity}:{f.name}" for f in (ra.findings if ra else [])],
            "B": [f"{f.severity}:{f.name}" for f in (rb.findings if rb else [])],
        }
        if abs(sa - sb) >= 8:
            winner = "A" if sa > sb else "B"
        else:
            winner = "TIE"
        improvements = []
        if winner == "A":
            improvements = [f.detail for f in (rb.findings if rb else [])] or ["raise overall watchability"]
        elif winner == "B":
            improvements = [f.detail for f in (ra.findings if ra else [])] or ["raise overall watchability"]
        data = {"winner": winner, "reason": f"local scores A={sa:.1f} B={sb:.1f}",
                "improvements": improvements, "hard_defects": defects}
        import json as _json
        text = _json.dumps(data, ensure_ascii=False)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return BackendResult(backend="local", text=text, raw=data, model="local_metrics",
                             calls=1, elapsed_s=time.time() - t0)


def select_backend(preferred=None, *, allow_mock=False, model=None):
    if preferred:
        p = preferred.lower()
        if p == "mock":
            return MockBackend()
        if p == "agy":
            return AgyBackend()
        if p in ("gemini", "gemini_cli"):
            return GeminiCliBackend()
        if p == "opencode":
            return OpencodeJudgeBackend(model=model) if model else OpencodeJudgeBackend()
        if p == "local":
            return LocalJudgeBackend()
    for b in (AgyBackend(), GeminiCliBackend(), OpencodeJudgeBackend()):
        if b.available():
            return b
    return LocalJudgeBackend()


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

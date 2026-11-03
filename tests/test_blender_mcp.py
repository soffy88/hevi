"""Tests for video.blender_mcp (M-13/M-16/M-17, C-03/C-04, S-07).

Everything here is mocked: no Blender binary, no xvfb session, no MCP
bridge, no ffmpeg run.  The tests pin the contract surface that the
audit flagged — own-pid-only stopping, port-occupied refusal, queue
semantics, resolved-engine qa, schema lock, and the preview gate —
not the real render pipeline (which was verified by hand on
ubuntu26 on 2026-10-25 and is deliberately not re-run in CI).
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hevi.capabilities.blender_mcp as bm
from hevi.capabilities import get as cap_get
from hevi.capabilities.errors import CapabilityError


class _FakeProc:
    def __init__(self, pid: int = 99991) -> None:
        self.pid = pid


class _FakeClient:
    def __init__(self, blend_path: Path | None = None) -> None:
        self.codes: list[str] = []
        self.closed = False
        self.blend_path = blend_path

    def execute_code(self, code: str) -> str:
        self.codes.append(code)
        if "save_mainfile" in code and self.blend_path is not None:
            self.blend_path.write_bytes(b"BLEND")
        return "ok"

    def scene_info(self) -> str:
        return "scene ok"

    def close(self) -> None:
        self.closed = True


def _fake_run_factory(out_dir: Path):
    """Simulate blender background render + ffmpeg assemble + ffprobe.

    ``_ffprobe`` itself is monkeypatched separately; this fake only
    needs the two subprocess calls render() makes directly.
    """

    def fake_run(argv: Any, **kwargs: Any) -> SimpleNamespace:
        argv = list(argv)
        if "--background" in argv:
            frames_dir = out_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            # duration=1.0, fps=24 in the happy-path tests below.
            for i in range(1, 25):
                (frames_dir / f"frame_{i:04d}.png").write_bytes(b"PNG")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv and "ffmpeg" in str(argv[0]):
            Path(argv[-1]).write_bytes(b"MP4")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {argv}")

    return fake_run


def _install_happy_path(monkeypatch: pytest.MonkeyPatch, out_dir: Path):
    stopped: list[Any] = []
    monkeypatch.setattr(bm, "_resolve_blender_bin", lambda: Path("/fake/blender"))
    monkeypatch.setattr(bm, "_port_listening", lambda port: False)
    monkeypatch.setattr(bm, "_start_session", lambda blender_bin: _FakeProc())
    monkeypatch.setattr(bm, "_stop_session", lambda proc=None, **kw: stopped.append(proc))
    monkeypatch.setattr(bm, "_MCPClient", lambda: _FakeClient(out_dir / "scene.blend"))
    monkeypatch.setattr(bm, "_ffprobe", lambda path: {
        "format": {"duration": 1.0},
        "streams": [{"codec_name": "h264", "width": 640, "height": 360}],
    })
    monkeypatch.setattr(bm.subprocess, "run", _fake_run_factory(out_dir))
    return stopped


def test_render_reports_resolved_engine_not_requested_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_happy_path(monkeypatch, tmp_path)
    cap = cap_get("video.blender_mcp")
    result = cap.render_safe(
        {"code": "import bpy"}, tmp_path, duration=1.0, aspect="16:9", seed=42
    )
    # C-03: NEXT does not exist in Blender 5.x; qa must name the engine
    # that actually ran, and the Workbench-only cost hint must not be
    # presented as an EEVEE measurement.
    assert result.qa["engine"] == "BLENDER_EEVEE"
    assert result.qa["engine_requested"] == "BLENDER_EEVEE_NEXT"
    assert result.qa["cpu_cost_hint"] is None
    assert "not re-measured" in result.qa["cpu_cost_note"]
    assert Path(result.mp4).is_file()


def test_render_workbench_reports_measured_cost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(bm, "_ffprobe", lambda path: {
        "format": {"duration": 1.0},
        "streams": [{"codec_name": "h264", "width": 640, "height": 360}],
    })
    cap = cap_get("video.blender_mcp")
    result = cap.render_safe(
        {"code": "import bpy", "engine": "BLENDER_WORKBENCH"},
        tmp_path, duration=1.0, aspect="16:9", seed=42,
    )
    assert result.qa["engine"] == "BLENDER_WORKBENCH"
    assert result.qa["cpu_cost_hint"] == 30.0


def test_stop_session_kills_only_its_own_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    # C-04: _stop_session must never scan the port for a victim; it
    # kills exactly the pid it was handed (here via the Popen object).
    kills: list[tuple[int, int]] = []
    alive = {99991: True}

    def fake_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))
        if sig == 0:
            if not alive.get(pid, False):
                raise ProcessLookupError(pid)
            return
        if sig == 15:  # SIGTERM
            alive[pid] = False

    monkeypatch.setattr(os, "kill", fake_kill)
    bm._stop_session(proc=_FakeProc(pid=99991))
    assert kills, "expected _stop_session to signal its own pid"
    assert {pid for pid, _ in kills} == {99991}
    # A bare call (this render started nothing) kills nobody.
    kills.clear()
    bm._stop_session()
    assert kills == []


def test_start_failure_stops_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # C-04/M-16: if the session never starts, the render finally-block
    # must not stop any process (previously _stop_session() scanned
    # the port and could kill a foreign session).
    stopped: list[Any] = []
    monkeypatch.setattr(bm, "_resolve_blender_bin", lambda: Path("/fake/blender"))
    monkeypatch.setattr(bm.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(bm, "_start_session", lambda blender_bin: (_ for _ in ()).throw(
        CapabilityError("localhost:9876 is already occupied by another session")
    ))
    monkeypatch.setattr(bm, "_stop_session", lambda proc=None, **kw: stopped.append(proc))
    cap = cap_get("video.blender_mcp")
    with pytest.raises(CapabilityError, match="occupied"):
        cap.render_safe({"code": "import bpy"}, tmp_path, duration=1.0, aspect="16:9", seed=42)
    assert stopped == []


def test_start_session_refuses_occupied_port_without_killing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Direct check of the real _start_session guard (Popen stubbed so
    # nothing is actually launched).
    calls: list[Any] = []
    monkeypatch.setattr(bm, "_port_listening", lambda port: True)
    monkeypatch.setattr(bm.subprocess, "Popen", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(bm.shutil, "which", lambda name: "/usr/bin/xvfb-run")
    with pytest.raises(CapabilityError, match="already occupied"):
        bm._start_session(Path("/fake/blender"))
    assert calls == []


def test_queue_timeout_when_another_render_holds_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # M-16: a second render queues behind the first instead of failing
    # instantly — but the wait is bounded, and the timeout surfaces as
    # a CapabilityError rather than a hang.
    import fcntl

    monkeypatch.setattr(bm, "_resolve_blender_bin", lambda: Path("/fake/blender"))
    monkeypatch.setattr(bm.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setenv("HEVI_BLENDER_MCP_QUEUE_TIMEOUT_S", "0.2")
    lock_path = Path(os.path.expanduser("~/.cache/hevi-blender-mcp.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = open(lock_path, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        cap = cap_get("video.blender_mcp")
        with pytest.raises(CapabilityError, match="timed out waiting"):
            cap.render_safe({"code": "import bpy"}, tmp_path, duration=1.0, aspect="16:9", seed=42)
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()


def test_schema_locked_and_description_current() -> None:
    cap = cap_get("video.blender_mcp")
    assert cap.params_schema.get("additionalProperties") is False
    with pytest.raises(CapabilityError):
        cap.validate_params({"code": "import bpy", "bogus": 1})
    # S-07: no more factory-reset wording; S-17 gate flag is set.
    code_desc = cap.params_schema["properties"]["code"]["description"]
    assert "select-all + delete" in code_desc
    assert "factory reset" not in code_desc
    assert cap.preview_restricted is True
    assert "arbitrary" in cap.description

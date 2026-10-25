"""Live-Blender-over-MCP capability (upstream mcp-for-blender bridge).

Registers one ``hevi.capabilities`` entry:

* ``video.blender_mcp`` — drive a live Blender session through the
  upstream MCP for Blender addon (Siddharth Ahuja, "MCP for Blender"
  1.8, protocol 15, installed via ``uvx mcp-for-blender``), then render
  the saved scene headlessly and assemble an MP4.  Input is a bpy code
  string that builds/animates the scene; output is the rendered MP4
  plus the editable ``.blend`` and probe info.  This is the article
  pipeline (AI instruction -> Blender editable 3D scene -> MCP bridge
  -> Remotion/ffmpeg delivery check), minus Remotion composition,
  which stays with the existing hevi-remotion line.

How it differs from the two Blender paths already in hevi:

* ``video.blender_clay_render`` (``hevi/capabilities/blender_clay.py``)
  is headless-only: it generates a bpy script and runs
  ``blender --background``.  It cannot hold a live, editable session
  open, cannot be re-driven interactively, and has no asset search.
* ``hevi/blendercmd/mcp_server.py`` is hevi's own op-list MCP server
  (``blender_add_object`` / ``blender_keyframe`` / ...).  It speaks a
  hevi-native op list, not the upstream MCP tool surface, and has no
  Poly Haven asset search/import.

This capability uses ONE FRESH live session per render (GUI Blender
under xvfb-run, addon server on localhost:9876) and talks to it with a
stdlib-only JSON-RPC client over the ``uvx mcp-for-blender`` stdio
bridge, then stops the session.  No new Python dependency is
introduced.  A shared long-lived session proved fragile in testing
(the addon server stopped responding after the factory-reset sequence
in the first end-to-end test, while Blender itself stayed alive), so
sessions are never reused and the scene is cleared with
select-all + delete instead of a factory reset.

Verified on ubuntu26, 2026-10-25 (do not claim more):

* Blender 5.0.1 (Ubuntu apt build) + addon 1.8 / protocol 15.
* MCP read (default Cube/Light/Camera), create UV sphere named
  MCP_Connection_Test at (3, 0, 0), re-read, save .blend, reopen and
  re-list objects — all through the MCP bridge.
* Background mode (``blender -b``) is REFUSED by the addon server
  itself ("commands would never execute"); the session must be a GUI
  Blender, here under ``xvfb-run -a``.  The headless render step is
  unaffected (background rendering works fine).
* Ubuntu's Blender 5.0.1 build has NO FFMPEG video output
  (``file_format`` enum is image-only), so this capability renders a
  PNG sequence and assembles the MP4 with system ffmpeg — the same
  pattern as ``blender_clay``.

NOT verified (article parity only, do not present as done):

* Poly Haven asset import: the bridge exposes ``search_assets`` /
  ``import_asset`` tools, but no HDRI/material/model import has been
  run through this capability yet.
* Character rigs, glass materials, camera moves beyond keyframes.
* The ``~/.local/blender/blender`` 4.2.17 LTS binary (used by
  ``blender_clay``) with this MCP addon — the addon dir for 4.2 would
  be ``~/.config/blender/4.2/scripts/addons`` and needs its own
  install + port check before it is claimed.

Failure policy (CAPABILITY_CONTRACT.md): a missing Blender binary, a
session that never listens, an MCP error, a non-zero render exit, a
short frame sequence, a missing ffmpeg, or a probe mismatch all raise
:class:`CapabilityError` — never a fake success.  Zero paid calls:
everything is local.

Registration note: this module registers itself on import (guarded,
idempotent) and is wired into ``hevi/capabilities/__init__.py``, so
``import hevi.capabilities`` lists ``video.blender_mcp``.  The
catalogue listing is NOT an execution grant: the generic preview
endpoint refuses this capability (``preview_restricted``) because its
``code`` param executes arbitrary bpy code in a live Blender session;
only trusted direct callers may render it.

CLI (same level as ``python -m hevi.capabilities.manim_render``)::

    python -m hevi.capabilities.blender_mcp --code-file scene.py \\
        --out out_dir --duration 3 --aspect 16:9
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

MCP_PORT = 9876
_ADDON_ENABLE_EXPR = (
    "import addon_utils; addon_utils.enable(\"blender_mcp\"); "
    "import bpy; bpy.ops.blendermcp.start_server()"
)

_DESCRIPTION = (
    "Live Blender session driven over the upstream MCP for Blender bridge: "
    "run caller-supplied bpy code against a GUI Blender (xvfb-run), verify "
    "by re-reading the scene, save the editable .blend, then render the "
    "scene headlessly to a PNG sequence and assemble an MP4 with ffmpeg. "
    "Local and free: no paid calls. CPU cost is scene-dependent; keep "
    "shots short (default 640x360, duration <=10s). Needs a local "
    "Blender binary ($HEVI_BLENDER_BIN / $BLENDER_BIN / PATH / "
    "~/.local/blender/blender / ~/opt/blender/blender), xvfb-run, uvx "
    "(mcp-for-blender), and system ffmpeg; any missing piece raises "
    "CapabilityError. Ubuntu Blender 5.0.1 has no FFMPEG video output, so "
    "the PNG-sequence + ffmpeg path is used unconditionally. "
    "RESTRICTED: the `code` param is arbitrary bpy code executed in a "
    "live Blender session; the generic preview endpoint refuses this "
    "capability (preview_restricted) and only trusted direct callers "
    "may render it. CPU cost hint 30.0 is a BLENDER_WORKBENCH "
    "measurement (2026-10-25); EEVEE cost has not been re-measured."
)

# Wall-clock seconds per second of output video at the verified settings
# (640x360, 24fps, simple cube spin): the 2026-10-25 verification render
# actually ran on WORKBENCH (the script asked for BLENDER_EEVEE_NEXT,
# which does not exist in Blender 5.0.1, and fell back silently) — so
# this hint is a Workbench measurement, not EEVEE. Re-measure for EEVEE
# and for heavier scenes.
_CPU_COST_HINT = 30.0

_DEFAULT_RESOLUTION = {"16:9": (640, 360), "9:16": (360, 640), "1:1": (480, 480)}
_MAX_DURATION_S = 10.0


def _resolve_blender_bin() -> Path:
    for cand in (
        os.environ.get("HEVI_BLENDER_BIN"),
        os.environ.get("BLENDER_BIN"),
        shutil.which("blender"),
        os.path.expanduser("~/.local/blender/blender"),
        os.path.expanduser("~/opt/blender/blender"),
    ):
        if cand and Path(cand).exists():
            return Path(cand)
    raise CapabilityError(
        "no Blender binary found ($HEVI_BLENDER_BIN / $BLENDER_BIN / PATH / "
        "~/.local/blender/blender / ~/opt/blender/blender)"
    )


def _port_listening(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


def _pid_file() -> Path:
    return Path(os.path.expanduser("~/.cache/hevi-blender-mcp.pid"))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_own_pid() -> int | None:
    """PID this capability recorded for its own session, if any."""
    try:
        raw = _pid_file().read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _clear_pid_file(pid: int) -> None:
    if _read_own_pid() == pid:
        try:
            _pid_file().unlink()
        except OSError:
            pass


def _stop_session(proc: Any = None, pid: int | None = None,
                  timeout_s: float = 15.0) -> None:
    """Stop ONLY this capability's own session (C-04).

    The pid comes from the ``Popen`` object this render started, or
    from an explicit ``pid`` argument — never from scanning the
    port, and never from the pid file on a bare call (a bare call
    means "this render started nothing", so there is nothing of
    ours to stop; the pid file is only an audit record of the last
    pid started).  A foreign process listening on the port is never
    killed: if we did not start it, we do not touch it (see
    :func:`_start_session`, which refuses to start when the port is
    already occupied instead of killing the occupant).
    """
    import signal

    target = proc.pid if proc is not None else pid
    if target is None:
        return
    if not _pid_alive(target):
        _clear_pid_file(target)
        return
    try:
        os.kill(target, signal.SIGTERM)
    except ProcessLookupError:
        _clear_pid_file(target)
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_alive(target):
            break
        time.sleep(1.0)
    else:
        try:
            os.kill(target, signal.SIGKILL)
        except ProcessLookupError:
            pass
    _clear_pid_file(target)


def _start_session(blender_bin: Path, port: int = MCP_PORT,
                   timeout_s: float = 90.0) -> Any:
    """Start a fresh GUI Blender + MCP addon server under xvfb-run.

    Returns the Blender ``Popen`` object (its pid is the only pid
    :func:`_stop_session` will ever kill).  If the port is already
    listening, the occupant is somebody else's session: raise
    instead of killing it (C-04).  On a listen timeout, kill the
    session this call itself started, then raise.
    """
    if shutil.which("xvfb-run") is None:
        raise CapabilityError("xvfb-run not found; the MCP addon server refuses background mode")
    if _port_listening(port):
        raise CapabilityError(
            f"localhost:{port} is already occupied by another session; "
            "video.blender_mcp refuses to stop it — stop that session "
            "yourself (or pick a free port) and retry"
        )
    log_path = Path(os.path.expanduser("~/.cache/hevi-blender-mcp.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")
    proc = subprocess.Popen(
        ["xvfb-run", "-a", str(blender_bin), "--python-expr", _ADDON_ENABLE_EXPR],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    _pid_file().write_text(str(proc.pid), encoding="utf-8")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _port_listening(port):
            return proc
        time.sleep(2.0)
    _stop_session(proc=proc)
    raise CapabilityError(
        f"MCP addon server did not listen on localhost:{port} within {timeout_s}s "
        f"(see {log_path})"
    )


class _MCPClient:
    """Minimal stdlib MCP client (newline-delimited JSON-RPC over stdio).

    Speaks to ``uvx mcp-for-blender``: initialize, notifications/
    initialized, tools/list, tools/call.  Only the tools this capability
    needs are wrapped.
    """

    def __init__(self, timeout_s: float = 120.0) -> None:
        env = dict(os.environ)
        local_bin = os.path.expanduser("~/.local/bin")
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
        if shutil.which("uvx", path=env["PATH"]) is None:
            raise CapabilityError("uvx not found (install uv: https://astral.sh/uv)")
        self.proc = subprocess.Popen(
            ["uvx", "mcp-for-blender"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env,
        )
        self._next_id = 0
        self.timeout_s = timeout_s
        self._initialize()

    def _send(self, method: str, params: dict | None = None, notify: bool = False) -> int | None:
        self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            msg["id"] = self._next_id
        if params is not None:
            msg["params"] = params
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return None if notify else self._next_id

    def _read_response(self, want_id: int) -> dict:
        assert self.proc.stdout is not None
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise CapabilityError("MCP bridge closed stdout unexpectedly")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == want_id:
                if "error" in msg:
                    raise CapabilityError(f"MCP error: {msg['error']}")
                return msg.get("result", {})
        raise CapabilityError("MCP response timeout")

    def _initialize(self) -> None:
        req_id = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hevi-blender-mcp", "version": "1.0"},
        })
        assert req_id is not None
        self._read_response(req_id)
        self._send("notifications/initialized", notify=True)

    def call_tool(self, name: str, arguments: dict) -> str:
        req_id = self._send("tools/call", {"name": name, "arguments": arguments})
        assert req_id is not None
        result = self._read_response(req_id)
        texts = [
            block.get("text", "")
            for block in result.get("content", [])
            if isinstance(block, dict)
        ]
        if result.get("isError"):
            raise CapabilityError(f"MCP tool {name} failed: {' '.join(texts)}")
        return "\n".join(texts)

    def execute_code(self, code: str) -> str:
        return self.call_tool("execute_blender_code", {"code": code})

    def scene_info(self) -> str:
        return self.call_tool("get_scene_info", {})

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        finally:
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()


# NOTE: this template is filled with plain .replace() on $TOKENS$, NOT
# .format() — the script body itself contains braces (set comprehension,
# f-string) that .format() would misinterpret as fields (observed twice).
_RENDER_SCRIPT = '''\
import bpy

blend = r"$BLEND$"
out_dir = r"$OUTDIR$"
engine = "$ENGINE$"
width, height = $WIDTH$, $HEIGHT$
fps = $FPS$
frame_start, frame_end = $FRAME_START$, $FRAME_END$

bpy.ops.wm.open_mainfile(filepath=blend)
scene = bpy.context.scene
# Blender 5.0 renamed EEVEE-NEXT back to BLENDER_EEVEE; accept the old
# name as an alias instead of failing on an enum mismatch.
valid_engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
if engine not in valid_engines:
    if engine == "BLENDER_EEVEE_NEXT" and "BLENDER_EEVEE" in valid_engines:
        engine = "BLENDER_EEVEE"
    else:
        raise RuntimeError(f"engine {engine} not available in this Blender build: {sorted(valid_engines)}")
scene.render.engine = engine
scene.render.resolution_x = width
scene.render.resolution_y = height
scene.render.resolution_percentage = 100
scene.render.fps = fps
scene.frame_start = frame_start
scene.frame_end = frame_end
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = out_dir + "/frame_"
bpy.ops.render.render(animation=True)
print("HEVI_BLENDER_MCP_RENDER_DONE")
'''


def _ffprobe(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise CapabilityError("ffprobe not found")
    out = subprocess.run(
        [exe, "-v", "error", "-show_entries",
         "format=duration", "-show_entries", "stream=codec_name,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise CapabilityError(f"ffprobe failed on {path}: {out.stderr.strip()}")
    return json.loads(out.stdout or "{}")


def render(params: dict, out_dir: str | Path, *, duration: float,
           aspect: str, seed: int = 0) -> CapabilityResult:
    """Render params['code'] (bpy) in a live MCP session, then to MP4."""
    del seed  # deterministic for a fixed code string; seed unused by design
    code = params.get("code", "")
    if not isinstance(code, str) or not code.strip():
        raise CapabilityError("video.blender_mcp needs params['code'] (bpy code string)")
    if duration <= 0 or duration > _MAX_DURATION_S:
        raise CapabilityError(f"duration must be in (0, {_MAX_DURATION_S}]s, got {duration}")
    if aspect not in _DEFAULT_RESOLUTION:
        raise CapabilityError(f"unsupported aspect {aspect!r} (want one of {sorted(_DEFAULT_RESOLUTION)})")
    engine = params.get("engine", "BLENDER_EEVEE_NEXT")
    if engine not in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        raise CapabilityError(f"unsupported engine {engine!r}")
    # C-03: BLENDER_EEVEE_NEXT does not exist in Blender 5.x; the render
    # script used to remap it silently while qa still reported NEXT.
    # Resolve here, once, so qa reports the engine that actually ran.
    resolved_engine = "BLENDER_EEVEE" if engine == "BLENDER_EEVEE_NEXT" else engine
    width, height = params.get("resolution") or _DEFAULT_RESOLUTION[aspect]
    fps = int(params.get("fps", 24))
    if fps <= 0:
        raise CapabilityError("fps must be positive")
    frame_start = 1
    frame_end = max(1, int(round(duration * fps)))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames_dir = out / "frames"
    frames_dir.mkdir(exist_ok=True)
    blend_path = out / "scene.blend"
    mp4_path = out / "blender_mcp.mp4"

    blender_bin = _resolve_blender_bin()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CapabilityError("ffmpeg not found")

    # One fresh session per render, guarded by a single-flight lock: the
    # MCP port is a shared resource, and a shared long-lived session
    # proved fragile in testing.  The scene is cleared with select-all +
    # delete (never a factory reset, which preceded the observed server
    # death).  The lock covers only the session phase; the headless
    # render and ffmpeg steps below use unique output dirs.
    import fcntl

    # M-16 concurrency: a single GUI session / single MCP port means
    # renders serialize.  A second render QUEUES behind the first
    # (bounded wait, default 600s via HEVI_BLENDER_MCP_QUEUE_TIMEOUT_S)
    # instead of failing outright, and the queue is documented in the
    # capability description.  Per-task port isolation is not used:
    # the addon server port is fixed by the addon invocation.
    lock_path = Path(os.path.expanduser("~/.cache/hevi-blender-mcp.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")
    queue_timeout = float(os.environ.get("HEVI_BLENDER_MCP_QUEUE_TIMEOUT_S", "600"))
    queue_deadline = time.time() + queue_timeout
    while True:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= queue_deadline:
                lock_file.close()
                raise CapabilityError(
                    "video.blender_mcp: timed out waiting for another "
                    "render to finish (queued behind the live session)"
                ) from None
            time.sleep(1.0)
    proc = None
    try:
        proc = _start_session(blender_bin)
        client = _MCPClient()
        try:
            client.execute_code(
                "import bpy\n"
                "bpy.ops.object.select_all(action='SELECT')\n"
                "bpy.ops.object.delete()\n"
            )
            client.execute_code(code)
            scene_summary = client.scene_info()
            client.execute_code(
                "import bpy\n"
                f"bpy.ops.wm.save_mainfile(filepath={str(blend_path)!r})\n"
            )
        finally:
            client.close()
    finally:
        if proc is not None:
            _stop_session(proc=proc)
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
    if not blend_path.exists() or blend_path.stat().st_size == 0:
        raise CapabilityError(f"scene .blend was not saved: {blend_path}")

    script_path = out / "render_scene.py"
    script_path.write_text(
        _RENDER_SCRIPT
        .replace("$BLEND$", str(blend_path))
        .replace("$OUTDIR$", str(frames_dir))
        .replace("$ENGINE$", resolved_engine)
        .replace("$WIDTH$", str(width))
        .replace("$HEIGHT$", str(height))
        .replace("$FPS$", str(fps))
        .replace("$FRAME_START$", str(frame_start))
        .replace("$FRAME_END$", str(frame_end))
    )
    # --python-exit-code is required: without it Blender exits 0 even
    # when the --python script raises, which would masquerade a broken
    # render as success (observed with the EEVEE enum rename).
    proc = subprocess.run(
        [str(blender_bin), "--background", str(blend_path),
         "--python", str(script_path), "--python-exit-code", "1"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise CapabilityError(
            f"headless Blender render failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()[-500:]}"
        )
    frames = sorted(frames_dir.glob("frame_*.png"))
    expected = frame_end - frame_start + 1
    if len(frames) != expected:
        raise CapabilityError(
            f"frame sequence short: got {len(frames)} PNGs, expected {expected}")
    if any(p.stat().st_size == 0 for p in frames):
        raise CapabilityError("frame sequence contains an empty PNG")

    ff = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-framerate", str(fps),
         "-i", str(frames_dir / "frame_%04d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4_path)],
        capture_output=True, text=True, check=False,
    )
    if ff.returncode != 0 or not mp4_path.exists():
        raise CapabilityError(f"ffmpeg assemble failed: {ff.stderr.strip()[-500:]}")

    probe = _ffprobe(mp4_path)
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_name") == "h264"), None)
    actual_s = float(fmt.get("duration", 0.0))
    if video is None or video.get("width") != width or video.get("height") != height:
        raise CapabilityError(f"probe mismatch on {mp4_path}: {probe}")
    if abs(actual_s - duration) > 0.5:
        raise CapabilityError(f"duration mismatch: probe {actual_s}s vs requested {duration}s")

    return CapabilityResult(
        mp4=str(mp4_path),
        duration_s=actual_s,
        sha256=compute_sha256(mp4_path),
        qa={
            "engine": resolved_engine,
            "engine_requested": engine,
            "cpu_cost_hint": 30.0 if resolved_engine == "BLENDER_WORKBENCH" else None,
            "cpu_cost_note": (
                "Workbench-measured 30.0 CPU-s/s (2026-10-25)"
                if resolved_engine == "BLENDER_WORKBENCH"
                else "EEVEE cost not re-measured; 30.0 hint is Workbench-only"
            ),
            "resolution": [width, height],
            "fps": fps,
            "frames": len(frames),
            "blend": str(blend_path),
            "scene_summary": scene_summary,
            "blender_bin": str(blender_bin),
        },
    )


def register_blender_mcp_capabilities_once() -> None:
    global _Registered
    if _Registered:
        return
    register(
        Capability(
            name="video.blender_mcp",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "bpy code that builds/animates the scene "
                        "(runs in the live session after select-all + delete "
                        "clears the scene; arbitrary code execution: only "
                        "trusted direct callers, never the generic preview "
                        "endpoint)",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"],
                        "default": "BLENDER_EEVEE_NEXT",
                        "description": "BLENDER_EEVEE_NEXT is an alias for BLENDER_EEVEE on Blender 5.x",
                    },
                    "resolution": {
                        "type": "array", "items": {"type": "integer"},
                        "description": "Overrides the aspect default [w, h]",
                    },
                    "fps": {"type": "integer", "default": 24},
                },
                "required": ["code"],
                "additionalProperties": False,
            },
            cpu_cost_hint=_CPU_COST_HINT,
            render=render,
            description=_DESCRIPTION,
            preview_restricted=True,
            line="blender-mcp",
        )
    )
    _Registered = True


register_blender_mcp_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render one video.blender_mcp shot")
    parser.add_argument("--code-file", required=True, help="bpy scene code file")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--aspect", default="16:9")
    parser.add_argument("--engine", default="BLENDER_EEVEE_NEXT")
    parser.add_argument("--fps", type=int, default=24)
    args = parser.parse_args(argv)
    code = Path(args.code_file).read_text()
    result = render(
        {"code": code, "engine": args.engine, "fps": args.fps},
        args.out, duration=args.duration, aspect=args.aspect,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

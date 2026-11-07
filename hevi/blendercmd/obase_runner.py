"""External-tool adapter: run a JSON op list in headless Blender."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .oskill_ops import validate_ops

RUNTIME = Path(__file__).with_name("bpy_runtime.py")
KNOWN = ("~/.local/blender/blender", "/home/soffy/.local/blender/blender",
         "~/opt/blender/blender", "/usr/bin/blender", "/usr/local/bin/blender")


def find_blender(explicit: str | None = None) -> str | None:
    for c in (explicit, os.environ.get("HEVI_BLENDER_BIN"), os.environ.get("BLENDER_BIN"), shutil.which("blender"), *KNOWN):
        if c and os.path.isfile(os.path.expanduser(c)) and os.access(os.path.expanduser(c), os.X_OK):
            return os.path.expanduser(c)
    return None


def build_command(blender: str, ops_path: str, res_path: str) -> list[str]:
    return [blender, "--background", "--factory-startup", "-noaudio",
            "--python-exit-code", "3", "--python", str(RUNTIME), "--", ops_path, res_path]


def run_ops(ops: list[dict], workdir: str | None = None, blender: str | None = None,
            timeout: float = 1800) -> dict[str, Any]:
    ops = validate_ops(ops)
    bl = find_blender(blender)
    if not bl:
        return {"ok": False, "error": {"message": "blender binary not found (set HEVI_BLENDER_BIN)"}}
    wd = Path(workdir or tempfile.mkdtemp(prefix="blcmd_"))
    wd.mkdir(parents=True, exist_ok=True)
    for o in ops:  # relative outputs land in workdir
        if "out" in o and not os.path.isabs(o["out"]):
            o["out"] = str(wd / o["out"])
    stamp = f"{int(time.time()*1000)}"
    ops_path, res_path = wd / f"ops_{stamp}.json", wd / f"result_{stamp}.json"
    ops_path.write_text(json.dumps(ops, indent=1))
    t = time.time()
    p = subprocess.run(build_command(bl, str(ops_path), str(res_path)), capture_output=True, text=True, timeout=timeout)
    wall = round(time.time() - t, 2)
    if res_path.exists():
        res = json.loads(res_path.read_text())
    else:
        res = {"ok": False, "error": {"message": f"blender exit {p.returncode}", "stderr": (p.stdout + p.stderr)[-2000:]}}
    res["wall_seconds"] = wall
    res["ops_file"] = str(ops_path)
    return res

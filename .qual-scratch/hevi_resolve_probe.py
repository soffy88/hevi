"""Resolve which hevi tree the canonical runner actually imports."""

from __future__ import annotations

import json
import sys

out: dict = {"cwd": None, "sys_path": list(sys.path)}
import os

out["cwd"] = os.getcwd()

import hevi

out["hevi_file"] = getattr(hevi, "__file__", None)

try:
    import hevi.distribution.adapters.local_file as lf

    out["local_file_file"] = getattr(lf, "__file__", None)
    out["local_file_import"] = "OK"
except Exception as exc:  # noqa: BLE001
    out["local_file_import"] = f"{type(exc).__name__}: {exc}"

try:
    from hevi.studio.veya import produce  # noqa: F401

    out["veya_import"] = "OK"
except Exception as exc:  # noqa: BLE001
    out["veya_import"] = f"{type(exc).__name__}: {exc}"

import subprocess

out["worktree_head"] = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=os.getcwd()
).stdout.strip()
out["main_head"] = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd="/data/soffy/projects/hevi"
).stdout.strip()

print(json.dumps(out, ensure_ascii=False, indent=2))

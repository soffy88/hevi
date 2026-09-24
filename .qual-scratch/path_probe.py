"""Probe sys.path[0] / safe_path semantics under the canonical runner."""

from __future__ import annotations

import json
import os
import sys

print(json.dumps({
    "sys_path": list(sys.path),
    "path0": sys.path[0] if sys.path else None,
    "safe_path": bool(getattr(sys.flags, "safe_path", False)),
    "no_user_site": bool(getattr(sys.flags, "no_user_site", False)),
    "isolated": bool(getattr(sys.flags, "isolated", False)),
    "PYTHONSAFEPATH": os.environ.get("PYTHONSAFEPATH"),
    "PYTHONPATH": os.environ.get("PYTHONPATH"),
    "PYTHONHOME": os.environ.get("PYTHONHOME"),
    "cwd": os.getcwd(),
    "argv0": sys.argv[0],
    "executable": sys.executable,
    "venv_prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
}, ensure_ascii=False, indent=2))

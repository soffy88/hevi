"""Probe installed 3O package pins (direct_url.json) for qualification lineage."""

from __future__ import annotations

import json
import importlib.metadata as md

REQUIRED = {
    "oprim": "25653ba2874bf0f9a5011f2a23ac3164ee673125",
    "obase": "7d31719d8411b4fb34952ae4098ab320625d14dd",
    "oskill": "cac39df03778d4e4e44db3c006f8fc788dc757f6",
    "omodul": "bdb48f52032e69818281c779169959e0650a558d",
    "oservi": "2527968d4d7e2455a48b280cb191012f4266d0bb",
}

out: dict = {"required_pins": REQUIRED, "installed": {}}
match = True
for name in REQUIRED:
    row: dict = {}
    try:
        dist = md.distribution(name)
        row["version"] = dist.version
        raw = dist.read_text("direct_url.json")
        direct = json.loads(raw) if raw else None
        row["direct_url"] = direct
        commit = None
        if isinstance(direct, dict):
            commit = (direct.get("vcs_info") or {}).get("commit_id")
        row["installed_commit"] = commit
        row["pin_match"] = commit == REQUIRED[name]
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["pin_match"] = False
    if not row["pin_match"]:
        match = False
    out["installed"][name] = row
out["pins_match"] = match

try:
    import hevi

    out["hevi_file"] = getattr(hevi, "__file__", None)
except Exception as exc:  # noqa: BLE001
    out["hevi_file"] = f"MISSING: {type(exc).__name__}"

import os

out["cwd"] = os.getcwd()
out["sys_path_head"] = __import__("sys").path[:6]
print(json.dumps(out, ensure_ascii=False, indent=2))

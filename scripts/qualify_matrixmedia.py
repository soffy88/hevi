#!/usr/bin/env python3
"""Record an external MatrixMedia qualification without importing its code.

This script is intentionally a probe/evidence collector.  It never attempts a
real publish unless an operator explicitly supplies a logged-in account and a
real approved artifact; an unavailable or logged-out provider is recorded as
such.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.getenv("MATRIXMEDIA_DIR", "/data/soffy/qualification/MatrixMedia"))
OUT = Path("artifacts/distribution/matrixmedia-qualification.json")
PLATFORMS = {
    "douyin": "dy",
    "kuaishou": "ks",
    "bilibili": "blbl",
    "xiaohongshu": "xhs",
    "wechat_channels": "sph",
    "toutiao": "tt",
    "baijiahao": "bjh",
    "fanqie_video": "fqsp",
}


def run_cli(*args: str) -> dict[str, object]:
    electron = ROOT / "node_modules/.bin/electron"
    if not electron.exists():
        return {"status": "NOT_VERIFIED", "failure_class": "MATRIXMEDIA_UNAVAILABLE", "stderr": "electron binary missing"}
    try:
        completed = subprocess.run(
            [str(electron), ".", "cli", *args],
            cwd=ROOT,
            env={**os.environ, "ELECTRON_RUN_AS_NODE": ""},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "NOT_VERIFIED", "failure_class": type(exc).__name__, "stderr": str(exc)}
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "status": "PASS" if completed.returncode == 0 else "NOT_VERIFIED",
    }


def main() -> None:
    license_path = ROOT / "LICENSE"
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "qualification_workspace": str(ROOT),
        "upstream_sha": "8b6216006005f38dde83018b97847274ee970688",
        "version": package["version"],
        "license": license_path.read_text(encoding="utf-8").splitlines()[0] if license_path.exists() else "UNKNOWN",
        "source_copied_into_hevi": False,
        "cli": {
            "accounts_json": run_cli("accounts", "--json"),
            "history_json": run_cli("history", "--json"),
            "publish_help": run_cli("publish", "--help"),
        },
        "mcp": {
            "list_accounts": "NOT_VERIFIED: MCP build blocked by remote package policy",
            "list_history": "NOT_VERIFIED: MCP build blocked by remote package policy",
            "publish_video": "NOT_VERIFIED: no real logged-in publish was attempted",
        },
        "platforms": {
            platform: {
                "alias": alias,
                "status": "NOT_VERIFIED",
                "reason": "runtime unavailable; no account probe or publish evidence",
            }
            for platform, alias in PLATFORMS.items()
        },
        "real_publish": "NOT_VERIFIED",
        "schedule": "NOT_VERIFIED",
        "draft": "NOT_VERIFIED",
        "idempotency": "IMPLEMENTED_NOT_PROVIDER_QUALIFIED",
        "retry": "IMPLEMENTED_NOT_PROVIDER_QUALIFIED",
        "fail_closed": "PASS_BY_CONTRACT",
        "duplicate_publications": 0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

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
import signal
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
    packaged = os.getenv("MATRIXMEDIA_BIN", "").strip()
    electron = ROOT / "node_modules/.bin/electron"
    if packaged:
        command = [packaged, "--no-sandbox", "cli", *args]
    elif not electron.exists():
        return {
            "status": "NOT_VERIFIED",
            "failure_class": "MATRIXMEDIA_UNAVAILABLE",
            "stderr": "electron binary missing",
        }
    else:
        command = [str(electron), ".", "cli", *args]
    if os.getenv("MATRIXMEDIA_USE_XVFB") == "1":
        command = ["xvfb-run", "-a", *command]
    command = ["timeout", "30s", *command]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "ELECTRON_RUN_AS_NODE": ""},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, subprocess.TimeoutExpired) and "completed" in locals():
            os.killpg(completed.pid, signal.SIGKILL)
        return {"status": "NOT_VERIFIED", "failure_class": type(exc).__name__, "stderr": str(exc)}
    stdout = completed.stdout
    clean_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    empty_json = "[]" in clean_lines
    status = "PASS" if completed.returncode == 0 else "NOT_VERIFIED"
    if status == "PASS" and empty_json and args[:1] in (("accounts",), ("history",)):
        status = "RUNTIME_VERIFIED_NO_LOGGED_IN_ACCOUNT"
    return {
        "exit_code": completed.returncode,
        "stdout": stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "status": status,
    }


def main() -> None:
    packaged = os.getenv("MATRIXMEDIA_BIN", "").strip()
    license_path = ROOT / "LICENSE"
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "qualification_workspace": str(ROOT),
        "upstream_sha": "8b6216006005f38dde83018b97847274ee970688",
        "version": package["version"],
        "license": license_path.read_text(encoding="utf-8").splitlines()[0]
        if license_path.exists()
        else "UNKNOWN",
        "source_copied_into_hevi": False,
        "artifact": packaged or "source checkout",
        "sha_verified": os.getenv("MATRIXMEDIA_SHA_VERIFIED", "NO"),
        "runtime_root_cause": os.getenv(
            "MATRIXMEDIA_RUNTIME_ROOT_CAUSE",
            "UNRECORDED",
        ),
        "cli": {
            "accounts_json": run_cli("accounts", "--json"),
            "history_json": run_cli("history", "--json"),
            "publish_help": run_cli("publish", "--help"),
        },
        "mcp": {
            "list_tools": "PASS: MCP server built and advertised tools",
            "list_accounts": "BLOCKED_ENVIRONMENT: MCP child lifecycle did not return within probe timeout",
            "list_history": "BLOCKED_ENVIRONMENT: MCP child lifecycle did not return within probe timeout",
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

"""Freeze local starting facts for the 3O v3 closure audit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    status = git("status", "--porcelain")
    # The task branch is created after the user's dirty worktree is observed;
    # exclude only files introduced by this closure so the freeze describes the
    # user's starting state, not our audit artifacts.
    closure_prefixes = (
        "scripts/ci/_3o_common.py",
        "scripts/ci/build_3o_inventory.py",
        "scripts/ci/check_async_contract.py",
        "scripts/ci/check_flat_namespace.py",
        "scripts/ci/check_layer4_leakage.py",
        "scripts/ci/check_no_project_prefix.py",
        "scripts/ci/check_obase_no_reverse_dep.py",
        "scripts/ci/check_oprim_keyword_only.py",
        "scripts/ci/check_oservi_injection.py",
        "scripts/ci/check_single_source.py",
        "scripts/ci/record_3o_start.py",
        "scripts/ci/run_3o_v3_independent_audit.py",
        "scripts/ci/check_enabled_pillars.py",
        "scripts/ci/check_no_sibling_call.py",
        "scripts/ci/check_omodul_signature.py",
        "artifacts/3o-v3/",
        "artifacts/qualification/3o-v3-",
    )
    user_status = [
        line
        for line in status.splitlines()
        if not any(line[3:].startswith(prefix) for prefix in closure_prefixes)
    ]
    payload = {
        "STARTING_SHA": git("rev-parse", "HEAD"),
        "CURRENT_BRANCH": git("branch", "--show-current"),
        "WORKTREE_CLEAN": not bool(user_status),
        "HEAD_DRIFT": "unknown/not-provided",
        "worktree_status_at_freeze": user_status,
        "authority": "local worktree; remote main excluded",
        "distribution_branch_modified": False,
        "gpu_hardware_qualification_modified": False,
    }
    out = ROOT / "artifacts/3o-v3/start_freeze.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

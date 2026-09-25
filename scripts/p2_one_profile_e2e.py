#!/usr/bin/env python3
"""Run a single P2 profile E2E (for long sequential runs)."""

from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, "/data/soffy/projects/hevi")

from scripts.p2_all_profiles_e2e import PROFILES, run_one


async def main() -> int:
    want = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = next((s for s in PROFILES if s["profile_id"] == want), None)
    if spec is None:
        print(f"unknown profile {want!r}; choices: {[s['profile_id'] for s in PROFILES]}")
        return 2
    r = await run_one(spec)
    print(json.dumps({k: r.get(k) for k in ("profile_id", "final_mp4", "proof_mp4", "gates", "adversarial")}, indent=2))
    return 0 if "error" not in r else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

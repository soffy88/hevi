#!/usr/bin/env python
"""DRAMAPLAN LLM 通道探测 —— 记录哪条免费通道可用/延迟/JSON 稳定性。

用法:
    .venv/bin/python scripts/dramaplan/llm_channel_probe.py \
        --env-file /data/soffy/projects/hevi/.env \
        --out output/dramaplan_e2e/_llm_probe.json

只走免费/本地通道（见 hevi/providers/free_llm.py），不触发任何付费端点。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env_file(path: Path) -> int:
    """把 KEY=VALUE 灌进 os.environ（不覆盖已存在的 key）。返回载入条数。"""
    if not path.is_file():
        return 0
    count = 0
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


async def _main_async(args: argparse.Namespace) -> int:
    for env_file in args.env_file:
        loaded = _load_env_file(Path(env_file).expanduser())
        print(f"[env] {env_file}: loaded {loaded} keys")
    for key in args.unset:
        os.environ.pop(key, None)
        print(f"[env] unset {key}")
    for pair in args.set:
        key, _, value = pair.partition("=")
        os.environ[key.strip()] = value.strip()
        print(f"[env] set {key.strip()}")

    from hevi.providers.free_llm import FREE_CHANNEL_ORDER, probe_channel

    channels = args.channel or list(FREE_CHANNEL_ORDER)
    results = []
    for name in channels:
        print(f"[probe] {name} ...", flush=True)
        result = await probe_channel(name, timeout=args.timeout)
        results.append(result)
        status = "OK" if result.get("available") else "FAIL"
        print(f"        {status} {json.dumps(result, ensure_ascii=False)[:200]}")

    report = {"channels": results}
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[out] {out_path}")

    usable = [r["channel"] for r in results if r.get("available") and r.get("json_stable")]
    print(f"[summary] json-stable channels: {usable}")
    return 0 if usable else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="额外加载的 .env（可重复；不覆盖已存在环境变量）",
    )
    parser.add_argument("--channel", action="append", help="只探测指定通道（可重复）")
    parser.add_argument("--unset", action="append", default=[], help="探测前清除的环境变量（可重复）")
    parser.add_argument(
        "--set", action="append", default=[], help="探测前设置 KEY=VALUE（可重复）"
    )
    parser.add_argument("--out", help="探测报告输出 JSON 路径")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    if not args.env_file:
        args.env_file = [str(Path("/data/soffy/projects/hevi/.env"))]
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

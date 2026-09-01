"""hevi-media CLI —— media-use 台账的执行入口。

用法:
    uv run python -m hevi.skills.media_cli resolve --type bgm --intent "温暖背景钢琴" \
        [--out-dir <dir>] [--ledger <path>]
    uv run python -m hevi.skills.media_cli candidates --type bgm --intent "温暖" [--ledger <path>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from hevi.sourcing.media_use import (
    MEDIA_TYPES,
    MediaLedger,
    MediaProviders,
    ResolveError,
    resolve_media,
)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="hevi-media: 媒体 resolve + 台账")
    sub = parser.add_subparsers(dest="verb", required=True)

    r = sub.add_parser("resolve", help="resolve 一个媒体需求")
    r.add_argument("--type", choices=MEDIA_TYPES, required=True)
    r.add_argument("--intent", required=True, help="一句话需求")
    r.add_argument("--out-dir", type=Path, default=None)
    r.add_argument("--ledger", type=Path, default=None, help="台账 JSON(默认不持久化)")

    c = sub.add_parser("candidates", help="列台账复用候选")
    c.add_argument("--type", choices=MEDIA_TYPES, required=True)
    c.add_argument("--intent", required=True)
    c.add_argument("--ledger", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.verb == "candidates":
        ledger = MediaLedger.load(args.ledger)
        for cand in ledger.reuse_candidates(args.type, args.intent):
            print(f"{cand.id} {cand.source} -> {cand.path} ({cand.provider})")
        return 0

    # resolve 使用 HEVI 的真实 provider 链：本地库优先，stock 负责检索并冻结
    # 到本地缓存，生成 provider 只在明确可用时参与。没有密钥或服务时仍然
    # fail-closed，不伪造远程 URL/产物。
    resolve_ledger: MediaLedger | None = (
        MediaLedger.load(args.ledger) if args.ledger else None
    )
    from hevi.sourcing.media_providers import default_providers

    providers: MediaProviders = default_providers()
    try:
        resolution = resolve_media(
            args.type,
            args.intent,
            providers=providers,
            ledger=resolve_ledger,
            out_dir=args.out_dir,
            verify_paths=True,
        )
    except ResolveError as e:
        print(f"resolve failed: {e}", file=sys.stderr)
        print("提示: 请检查 providers_cli status、素材 API Key、缓存目录和本地库。", file=sys.stderr)
        return 1
    print(
        f"resolved {resolution.id} -> {resolution.path} "
        f"({resolution.media_type}, {resolution.source})"
    )
    if resolve_ledger is not None and args.ledger:
        resolve_ledger.save(args.ledger)
        print(f"ledger updated: {args.ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

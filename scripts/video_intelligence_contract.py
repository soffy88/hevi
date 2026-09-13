#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from hevi.video_intelligence.contracts import contract_snapshot


def main() -> int:
    destination = Path("artifacts/video_intelligence/v1-contract.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(contract_snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

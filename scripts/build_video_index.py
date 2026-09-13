#!/usr/bin/env python3
"""Build a temporal metadata index from existing analysis JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.video_intelligence.models import ReelAnalysis
from hevi.video_intelligence.retrieval import VideoTemporalIndex


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    analyses = [ReelAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
                for path in sorted(args.source.rglob("analysis.json"))]
    entries: list[dict[str, object]] = []
    for analysis in analyses:
        entries.extend(VideoTemporalIndex.from_analysis(analysis).entries)
    index = VideoTemporalIndex(entries=entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {"status": "SUCCEEDED", "entries": len(entries), "output": str(args.output)}
    print(json.dumps(payload, ensure_ascii=False) if args.json_output else payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

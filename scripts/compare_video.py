#!/usr/bin/env python3
"""Compare a structured intent profile with an analyzed artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.video_intelligence.comparison import compare_intent_to_artifact
from hevi.video_intelligence.models import IntentProfile, ReelAnalysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    intent = IntentProfile.model_validate_json(args.expected.read_text(encoding="utf-8"))
    analysis = ReelAnalysis.model_validate_json(args.artifact.read_text(encoding="utf-8"))
    comparison = compare_intent_to_artifact(intent, analysis)
    payload = {"status": comparison.status.value, "comparison": comparison.model_dump(mode="json")}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json_output else payload)
    return 0 if comparison.status.value != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())

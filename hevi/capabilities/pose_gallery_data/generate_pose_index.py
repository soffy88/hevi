"""Regenerate pose_index.json from an ai-pose-gallery-zh checkout.

Reads ``data/pose-zh.json`` from a gallery checkout (default:
``$HEVI_POSE_GALLERY_HOME`` or
``~/workspace/references/ai-pose-gallery-zh``) and writes the
grouped index next to this script. The output contains metadata
and relative paths only, never image bytes. Re-run after any
upstream pose-data change and commit the regenerated JSON; if the
record count changes, update POSE_GALLERY_ATTRIBUTION.md and the
tests in tests/test_pose_library.py to the new verified numbers.

Usage:
    python3 generate_pose_index.py [--gallery HOME] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import OrderedDict
from pathlib import Path

VIEW_ORDER = ["正面", "斜侧", "侧面", "俯视", "仰视"]
SYSTEM_KEYS = {
    "全身单人・标准系": "full_standard",
    "全身单人・性感系": "full_sexy",
    "上半身单人": "upper_body",
    "双人缠绵": "two_person",
}


def build_index(records: list[dict], data_sha256: str) -> dict:
    from collections import Counter

    groups: "OrderedDict[str, dict]" = OrderedDict()
    for record in records:
        key = SYSTEM_KEYS[record["体系"]] + "_" + record["姿势编号"]
        group = groups.get(key)
        if group is None:
            group = {
                "key": key,
                "system": SYSTEM_KEYS[record["体系"]],
                "system_name": record["体系"],
                "code": record["姿势编号"],
                "category": record["分类"],
                "name": record["姿势名称"],
                "search_text": record["检索"],
                "views": {},
            }
            groups[key] = group
        if record["角度"] in group["views"]:
            raise ValueError(f"duplicate view for {key}: {record['角度']}")
        group["views"][record["角度"]] = {
            "id": record["id"],
            "thumb": record["缩略图"],
            "image": record["原图"],
        }
    out_groups = []
    for group in groups.values():
        views = {angle: group["views"].get(angle) for angle in VIEW_ORDER}
        missing = [a for a in VIEW_ORDER if views[a] is None]
        out_groups.append(
            {
                **group,
                "views": views,
                "view_count": 5 - len(missing),
                "missing_views": missing,
                "complete": not missing,
            }
        )
    system_counts = Counter(r["体系"] for r in records)
    return {
        "source": {
            "repo": "anhao/ai-pose-gallery-zh",
            "original_author": "ギア (@giaaibusi)",
            "original_site": "https://ai-pose-gallery.pages.dev/",
            "data_file": "data/pose-zh.json",
            "data_sha256": data_sha256,
            "license_note": (
                "MIT covers source code only (index.html, scripts/, "
                "_headers). Images under img/ and thumbs/ and original "
                "data under data/ belong to the original author; "
                "non-commercial reference use only, remove on objection."
            ),
            "non_commercial": True,
        },
        "counts": {
            "records": len(records),
            "groups": len(out_groups),
            "distinct_names": len({r["姿势名称"] for r in records}),
            "categories": len({r["分类"] for r in records}),
            "systems": {SYSTEM_KEYS[k]: v for k, v in system_counts.items()},
            "views": {
                angle: sum(1 for r in records if r["角度"] == angle)
                for angle in VIEW_ORDER
            },
        },
        "systems": [
            {
                "key": SYSTEM_KEYS[name],
                "name": name,
                "records": system_counts[name],
                "groups": sum(1 for g in out_groups if g["system"] == SYSTEM_KEYS[name]),
            }
            for name in SYSTEM_KEYS
        ],
        "categories": sorted({r["分类"] for r in records}),
        "views": VIEW_ORDER,
        "groups": out_groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gallery", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    import os

    home = Path(
        args.gallery
        or os.environ.get("HEVI_POSE_GALLERY_HOME")
        or "~/workspace/references/ai-pose-gallery-zh"
    ).expanduser()
    data_path = home / "data" / "pose-zh.json"
    raw = data_path.read_bytes()
    records = json.loads(raw)
    index = build_index(records, hashlib.sha256(raw).hexdigest())
    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "pose_index.json"
    out.write_text(
        json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} ({index['counts']['records']} records, {index['counts']['groups']} groups)")


if __name__ == "__main__":
    main()

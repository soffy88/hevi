#!/usr/bin/env python3
"""Build portrait_vocab_index.json from the transcribed VOCAB.md tables.

Source of truth: ~/workspace/references/portrait-prompt-vocab/VOCAB.md
(Soffy forwarded 2026-10-23; original image pages in media_library).
The transcription is verbatim: zh / en / how / feeling are copied
character-for-character from the markdown tables; nothing is added,
removed or reworded.  The expression category is absent in the source
(the author left it to free description) and is NOT invented here.

Usage:
    python3 build_portrait_index.py [VOCAB.md] [out.json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# section heading (prefix match) -> (category key, id prefix)
SECTIONS = [
    ("视频微动作", "video_micro", "VM"),
    ("姿态", "posture", "PO"),
    ("头发与头部", "hair_head", "HH"),
    ("手与持物", "hands", "HA"),
    ("动态", "motion", "MO"),
    ("坐姿", "sitting", "SI"),
    ("站姿", "standing", "ST"),
    ("视线", "gaze", "GA"),
]

EXPECTED_COUNTS = {
    "video_micro": 6,
    "posture": 8,
    "hair_head": 8,
    "hands": 9,
    "motion": 8,
    "sitting": 8,
    "standing": 9,
    "gaze": 10,
}

_ZH_EN_RE = re.compile(r"^([一-鿿]+)\s+(.+)$")


def parse_vocab(md_text: str) -> dict:
    entries: list[dict] = []
    current: tuple[str, str] | None = None  # (category, prefix)
    counters: dict[str, int] = {}
    for line in md_text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current = None
            for prefix_text, category, id_prefix in SECTIONS:
                if heading.startswith(prefix_text):
                    current = (category, id_prefix)
                    break
            continue
        if current is None:
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("提示词",) or set(cells[0]) <= {"-", " "}:
            continue
        m = _ZH_EN_RE.match(cells[0])
        if not m:
            raise ValueError(f"cannot split zh/en cell: {cells[0]!r}")
        category, id_prefix = current
        counters[category] = counters.get(category, 0) + 1
        entries.append(
            {
                "id": f"{id_prefix}-{counters[category]:02d}",
                "category": category,
                "zh": m.group(1),
                "en": m.group(2),
                "how": cells[1],
                "feeling": cells[2],
            }
        )
    counts = {cat: counters.get(cat, 0) for cat in EXPECTED_COUNTS}
    if counts != EXPECTED_COUNTS:
        raise ValueError(f"category counts mismatch: {counts} != {EXPECTED_COUNTS}")
    if len(entries) != 66:
        raise ValueError(f"expected 66 entries, got {len(entries)}")
    ids = [e["id"] for e in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate entry ids")
    return {
        "source": (
            "Portrait prompt vocabulary transcribed verbatim from the "
            "image pages Soffy forwarded on 2026-10-23 "
            "(archive: ~/workspace/references/portrait-prompt-vocab/VOCAB.md). "
            "The expression category is absent in the source and is not "
            "invented here."
        ),
        "version": "1.0",
        "counts": counts,
        "total": len(entries),
        "entries": entries,
    }


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "~/workspace/references/portrait-prompt-vocab/VOCAB.md"
    ).expanduser()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        "portrait_vocab_index.json"
    )
    index = parse_vocab(src.read_text(encoding="utf-8"))
    out.write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"wrote {out}: {index['total']} entries, counts={index['counts']}")


if __name__ == "__main__":
    main()

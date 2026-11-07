"""Build ``samples_index.json`` for the vendored VCSL sample subset.

Reads the *upstream* mg-styles-15 checkout (``lib/audio``), keeps only
the sample files actually vendored into ``samples/`` here, and writes a
filtered index in upstream mgaudio's format (per instrument: items with
``file`` / ``name`` / ``midi`` (detected, fractional) / ``peak`` /
``dur``), plus a per-instrument normalisation ``gain`` (upstream rule:
0.5 / median peak of the loudest velocity layer) and a ``pitched`` flag
(items carry a detected midi).

Rebuild from a fresh upstream checkout with:

```
HEVI_MG_AUDIO_HOME=~/projects/_refs/mg-styles-15/lib/audio \
    python3 build_sample_index.py
```

Upstream: https://github.com/Vincentwei1021/mg-styles-15 (MIT);
samples: VCSL, CC0 — see ``ATTRIBUTION.md`` in this directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

_VEL = {
    "ppp": 0.12, "pp": 0.2, "p": 0.35, "mp": 0.5, "mf": 0.65, "med": 0.6,
    "medium": 0.6, "f": 0.8, "loud": 0.85, "ff": 0.92, "fff": 1.0,
    "soft": 0.35, "quiet": 0.3, "hard": 0.85, "v1": 0.3, "v2": 0.5,
    "v3": 0.72, "v4": 0.9, "v5": 0.95, "v7": 1.0,
}


def _vel_of(name: str) -> float:
    toks = re.split(r"[_\-\s]+", name.lower())
    for t in toks:
        if t in _VEL:
            return _VEL[t]
    return 0.7


def main() -> None:
    src = Path(
        os.environ.get(
            "HEVI_MG_AUDIO_HOME",
            str(Path.home() / "projects/_refs/mg-styles-15/lib/audio"),
        )
    )
    upstream_index = json.loads((src / "samples" / "index.json").read_text())
    on_disk = {
        p.relative_to(src / "samples").as_posix()
        for p in (src / "samples").rglob("*.flac")
    }
    instruments: dict[str, dict] = {}
    total = 0
    for key, items in sorted(upstream_index.items()):
        kept = []
        for it in items:
            if it["file"] not in on_disk:
                continue
            kept.append(
                {
                    "file": it["file"],
                    "name": it["name"],
                    "midi": it.get("midi"),
                    "peak": it.get("peak"),
                    "dur": it.get("dur"),
                }
            )
        if not kept:
            continue
        kept.sort(key=lambda i: i["file"])
        # upstream gain rule: 0.5 / median peak of the loudest layer
        vels = [_vel_of(i["name"]) for i in kept]
        top = max(vels)
        peaks = sorted(
            float(i["peak"] or 0.0)
            for i, v in zip(kept, vels, strict=True)
            if v >= top - 1e-6 and i["peak"]
        )
        median_peak = peaks[len(peaks) // 2] if peaks else 0.5
        instruments[key] = {
            "pitched": any(i["midi"] is not None for i in kept),
            "gain": round(0.5 / (median_peak + 1e-9), 4),
            "items": kept,
        }
        total += len(kept)
    out = {
        "source": "mg-styles-15 lib/audio/samples (VCSL subset, CC0)",
        "upstream_repo": "https://github.com/Vincentwei1021/mg-styles-15",
        "sample_count": total,
        "instruments": instruments,
    }
    dest = HERE / "samples_index.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {dest}: {total} samples, {len(instruments)} instruments")


if __name__ == "__main__":
    main()

"""停顿剪辑模块：silencedetect → 可编辑时间线 JSON →（可选）导出。

CLI: python -m hevi.avcraft.omodul.pause_cut IN OUT_DIR [--noise -35] [--min-pause 0.5] [--margin 0.12] [--no-export]
     python -m hevi.avcraft.omodul.pause_cut --export TIMELINE.json OUT_MEDIA   # 改完时间线后重新导出
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.avcraft.obase.media import probe_duration, render_keep_ranges, run_silencedetect
from hevi.avcraft.oskill.timeline import (
    build_pause_timeline,
    keep_ranges,
    load_timeline,
    save_timeline,
)


def export_timeline(
    timeline: dict | str | Path, dst: str | Path, src: str | Path | None = None
) -> dict:
    tl = timeline if isinstance(timeline, dict) else load_timeline(timeline)
    src = src or tl["source"]
    ranges = keep_ranges(tl)
    out = render_keep_ranges(src, ranges, dst)
    kept = sum(b - a for a, b in ranges)
    return {
        "output": str(out),
        "kept_s": round(kept, 3),
        "ranges": len(ranges),
        "output_duration_s": round(probe_duration(out), 3),
    }


def pause_cut(
    src: str | Path,
    out_dir: str | Path,
    *,
    noise_db: float = -35.0,
    min_silence: float = 0.4,
    margin: float = 0.12,
    min_pause: float = 0.5,
    keep_pause_max: float = 0.0,
    export: bool = True,
) -> dict:
    src = Path(src).resolve()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dur = probe_duration(src)
    sil = run_silencedetect(src, noise_db=noise_db, min_silence=min_silence)
    tl = build_pause_timeline(
        sil, dur, margin=margin, min_pause=min_pause, keep_pause_max=keep_pause_max, source=str(src)
    )
    tl["params"].update({"noise_db": noise_db, "min_silence": min_silence})
    tl_path = save_timeline(tl, out / f"{src.stem}.timeline.json")
    res = {
        "source": str(src),
        "duration_s": round(dur, 3),
        "silences": len(sil),
        "timeline": str(tl_path),
        "clips": len(tl["clips"]),
        "removed": sum(1 for c in tl["clips"] if not c["keep"]),
    }
    if export:
        res.update(export_timeline(tl, out / f"{src.stem}.cut{src.suffix}", src))
    return res


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--export", action="store_true", help="src 是 timeline.json，out 是输出媒体")
    ap.add_argument("--noise", type=float, default=-35.0)
    ap.add_argument("--min-silence", type=float, default=0.4)
    ap.add_argument("--margin", type=float, default=0.12)
    ap.add_argument("--min-pause", type=float, default=0.5)
    ap.add_argument("--keep-pause", type=float, default=0.0)
    ap.add_argument("--no-export", action="store_true")
    a = ap.parse_args()
    if a.export:
        r = export_timeline(a.src, a.out)
    else:
        r = pause_cut(
            a.src,
            a.out,
            noise_db=a.noise,
            min_silence=a.min_silence,
            margin=a.margin,
            min_pause=a.min_pause,
            keep_pause_max=a.keep_pause,
            export=not a.no_export,
        )
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _main()

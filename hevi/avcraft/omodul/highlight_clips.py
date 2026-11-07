"""多信号高光拆条：信号采集（音量/运动/场景，CPU）+ 可选 ASR → oskill.score_highlights →
写入 avcraft 时间线（markers + 保留区）→ 每段导出成片 + SRT（+ 可选 9:16 跟随说话人竖版）。

CLI:
  python -m hevi.avcraft.omodul.highlight_clips VIDEO OUT_DIR [--cues CUES.json] [--top 3] [--min 15] [--max 60]
         [--keywords "a,b"] [--vertical] [--size 720x1280]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.avcraft.obase.media import (
    has_video,
    probe_duration,
    render_keep_ranges,
    run_visual_detect,
)
from hevi.avcraft.oskill.highlight import highlights_to_timeline, score_highlights
from hevi.avcraft.oskill.subtitle import to_srt
from hevi.avcraft.oskill.timeline import render_cues, save_timeline, timeline_from_cues


def _cues(video: Path, cues) -> list[dict]:
    if cues is None:
        from hevi.avcraft.obase.asr_runtime import transcribe_words
        from hevi.avcraft.oskill.subtitle import segment_sentences

        r = transcribe_words(video)
        return [{**c, "id": i + 1} for i, c in enumerate(segment_sentences(r["words"]))]
    if isinstance(cues, (str, Path)):
        d = json.loads(Path(cues).read_text())
        cues = d["cues"] if isinstance(d, dict) else d
    return cues


def collect_signals(video: str | Path, *, hop: float = 0.5, sample_fps: float = 2.0,
                    scene_th: float = 10.0) -> dict:
    from hevi.avcraft.obase.vision import analyze_frames, audio_energy

    video = Path(video)
    sig = {"audio": audio_energy(video, hop=hop), "motion": None, "scenes": None}
    if has_video(video):
        ana = analyze_frames(video, sample_fps=sample_fps, faces=False)
        sig["motion"] = [(s["t"], s["motion"]) for s in ana["samples"][1:]]
        sig["scenes"] = [t for t, _ in run_visual_detect(video, scene_th=scene_th)["scene"]]
    return sig


def highlight_clips(
    video: str | Path,
    out_dir: str | Path,
    *,
    cues: list[dict] | str | Path | None = None,
    top_n: int = 3,
    min_len: float = 15.0,
    max_len: float = 60.0,
    keywords: list[str] | tuple = (),
    weights: dict | None = None,
    export: bool = True,
    vertical: bool = False,
    size: tuple[int, int] = (1080, 1920),
    signals: dict | None = None,
) -> dict:
    video, out = Path(video).resolve(), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cs = _cues(video, cues)
    sig = signals or collect_signals(video)
    hs = score_highlights(cs, audio=sig.get("audio"), motion=sig.get("motion"), scenes=sig.get("scenes"),
                          keywords=keywords, top_n=top_n, min_len=min_len, max_len=max_len, weights=weights)
    dur = probe_duration(video)
    tl = highlights_to_timeline(timeline_from_cues(cs, dur, source=str(video)), hs)
    save_timeline(tl, out / f"{video.stem}.highlights.timeline.json")
    clips = []
    for h in hs if export else []:
        stem = f"{video.stem}.hl{h['rank']}"
        one = highlights_to_timeline(timeline_from_cues(cs, dur, source=str(video)), hs, only=h["rank"])
        mp4 = render_keep_ranges(video, [(h["start"], h["end"])], out / f"{stem}{video.suffix}")
        sub = render_cues(one)
        (out / f"{stem}.srt").write_text(to_srt(sub, "src"))
        save_timeline(one, out / f"{stem}.timeline.json")
        rec = {"rank": h["rank"], "video": str(mp4), "srt": str(out / f"{stem}.srt"),
               "output_s": round(probe_duration(mp4), 3)}
        if vertical and has_video(video):
            from hevi.avcraft.omodul.reframe_vertical import reframe_vertical

            v = reframe_vertical(mp4, out / f"{stem}.9x16.mp4", cues=sub, size=size)
            rec["vertical"] = {k: v[k] for k in ("detector", "stats", "files")}
            Path(mp4).unlink(missing_ok=True)  # 省空间：竖版已含画面，横版中间件删掉
            rec["video"] = None
        clips.append(rec)
    report = {"source": str(video), "duration": dur, "cues": len(cs),
              "signals": {k: (len(v) if v is not None else None) for k, v in sig.items()},
              "highlights": hs, "clips": clips,
              "timeline": str(out / f"{video.stem}.highlights.timeline.json")}
    (out / f"{video.stem}.highlights.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video"), ap.add_argument("out")
    ap.add_argument("--cues")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--min", type=float, default=15.0)
    ap.add_argument("--max", type=float, default=60.0)
    ap.add_argument("--keywords", default="")
    ap.add_argument("--vertical", action="store_true")
    ap.add_argument("--size", default="1080x1920")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))
    r = highlight_clips(a.video, a.out, cues=a.cues, top_n=a.top, min_len=a.min, max_len=a.max,
                        keywords=[k.strip() for k in a.keywords.split(",") if k.strip()],
                        vertical=a.vertical, size=(w, h))
    print(json.dumps({"highlights": [{k: x[k] for k in ("rank", "start", "end", "score", "reasons")}
                                     for x in r["highlights"]], "clips": r["clips"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _main()

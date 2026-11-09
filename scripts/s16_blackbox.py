"""S16 black-box validation: 3 themes per line, sample frames, score /5.

Usage:
    python scripts/s16_blackbox.py --line series --series-dir DIR --out DIR
    python scripts/s16_blackbox.py --line handdraw --out DIR
    python scripts/s16_blackbox.py --video FILE --out DIR

The scorer is deterministic: resolution/aspect/duration, audio presence and
loudness, motion (not frozen), clarity (not blank/dark) and garbled-text OCR.
A line is recommended for the GA whitelist only when its average score is >= 4.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from hevi.ai_drama.segment_gate import detect_text_artifacts

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    video = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams") or [] if s.get("codec_type") == "audio"), None)
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration_s": float((data.get("format") or {}).get("duration") or 0),
        "has_audio": audio is not None,
    }


def _loudness(path: Path) -> float | None:
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path), "-af",
         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r'"input_i"\s*:\s*"([^"]+)"', proc.stderr)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _frames(path: Path, count: int = 5) -> list[Image.Image]:
    with tempfile.TemporaryDirectory(prefix="s16-frames-") as tmp:
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-i", str(path), "-vf", f"fps=1/{max(2, 8)}",
             "-frames:v", str(count), str(Path(tmp) / "f%02d.png")],
            check=False,
        )
        return [Image.open(p).convert("RGB") for p in sorted(Path(tmp).glob("f*.png"))]


def score_video(path: str | Path) -> dict[str, Any]:
    video = Path(path)
    probe = _probe(video)
    width, height, duration = probe.get("width", 0), probe.get("height", 0), probe.get("duration_s", 0.0)
    frames = _frames(video)
    dims: dict[str, float] = {}

    spec_ok = width == 1080 and height == 1920 and 8.0 <= duration <= 120.0
    dims["spec"] = 5.0 if spec_ok else (3.0 if width and height and duration >= 3 else 0.0)

    have_audio = bool(probe.get("has_audio"))
    loud = _loudness(video) if have_audio else None
    if not have_audio:
        dims["audio"] = 0.0
    elif loud is None:
        dims["audio"] = 3.0
    else:
        dims["audio"] = 5.0 if -17.0 <= loud <= -11.0 else (3.0 if -20.0 <= loud <= -8.0 else 1.0)
    dims["audio_lufs"] = round(loud, 2) if loud is not None else None  # type: ignore[assignment]

    if len(frames) >= 2:
        diffs = []
        for a, b in itertools.pairwise(frames):
            aa, bb = ImageStat.Stat(a).mean, ImageStat.Stat(b).mean
            diffs.append(sum(abs(x - y) for x, y in zip(aa, bb, strict=False)) / 3.0)
        motion = sum(diffs) / len(diffs)
    else:
        motion = 0.0
    dims["motion"] = 5.0 if motion >= 1.5 else (3.0 if motion >= 0.4 else 0.0)
    dims["motion_delta"] = round(float(motion), 3)  # type: ignore[assignment]

    if frames:
        means = [ImageStat.Stat(f).mean[0] for f in frames]
        stds = [ImageStat.Stat(f).stddev[0] for f in frames]
        mean_luma = sum(means) / len(means)
        mean_std = sum(stds) / len(stds)
        dims["clarity"] = 5.0 if 20 <= mean_luma <= 235 and mean_std >= 10 else (3.0 if mean_std >= 4 else 0.0)
        dims["mean_luma"] = round(mean_luma, 1)  # type: ignore[assignment]
        with tempfile.TemporaryDirectory(prefix="s16-ocr-") as tmp:
            paths = []
            for i, frame in enumerate(frames):
                path = Path(tmp) / f"f{i}.png"
                frame.save(path)
                paths.append(path)
            texts = [detect_text_artifacts(p) for p in paths]
        dims["text"] = 5.0 if all(t["passed"] for t in texts) else 0.0
        dims["garbled_frames"] = sum(0 if t["passed"] else 1 for t in texts)  # type: ignore[assignment]
    else:
        dims["clarity"] = 0.0
        dims["text"] = 0.0

    numeric = [v for k, v in dims.items() if k in ("spec", "audio", "motion", "clarity", "text")]
    total = round(sum(numeric) / len(numeric), 2)
    return {
        "file": str(video),
        "exists": video.is_file(),
        "size_bytes": video.stat().st_size if video.is_file() else 0,
        "probe": probe,
        "dimensions": dims,
        "score": total,
        "pass": total >= 4.0,
    }


def _score_all(results: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [r["score"] for r in results if r.get("exists")]
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return {
        "results": results,
        "count": len(results),
        "average_score": avg,
        "pass": bool(results) and all(r.get("pass") for r in results) and avg >= 4.0,
    }


def _run_handdraw(out: Path) -> list[dict[str, Any]]:
    import asyncio

    from hevi.layer4_legacy.handdraw.line import render_handdraw_line

    topics = ["复利为什么反直觉", "手机屏幕为什么让人停不下来", "城市里的树怎么降温"]
    results = []
    for index, topic in enumerate(topics, start=1):
        dest = out / f"handdraw_{index}"
        dest.mkdir(parents=True, exist_ok=True)
        try:
            res = asyncio.run(render_handdraw_line(
                {"topic": topic, "width": 1080, "height": 1920, "audience": "general",
                 "job_id": f"s16-handdraw-{index}"}, dest))
            score = score_video(res["video_path"])
            score["topic"] = topic
            score["line_status"] = res.get("status")
            score["audience"] = "general"
        except Exception as exc:
            score = {"topic": topic, "exists": False, "score": 0.0, "pass": False,
                     "error": f"{type(exc).__name__}: {exc}"}
        results.append(score)
    return results


def _run_series(series_dir: Path, out: Path) -> list[dict[str, Any]]:
    from hevi.ai_drama.series import load_series
    from hevi.ai_drama.series_pipeline import run_series_episode
    from hevi.ai_drama.topics import suggest_topics

    series = load_series(series_dir)
    topics = suggest_topics(series)
    ids = [i["id"] for i in topics["ideas"]]
    results = []
    for index, idea_id in enumerate(ids, start=1):
        dest = out / f"series_{index}"
        try:
            res = run_series_episode(series_dir, idea_id=idea_id, out_dir=dest,
                                     render_images=True, gated=True, lipsync=False, trim=True)
            video = (res.get("episode") or {}).get("deliverable")
            score = score_video(video) if video else {"exists": False, "score": 0.0, "pass": False}
            score["topic"] = (res.get("episode") or {}).get("title")
            score["genre"] = (res.get("episode") or {}).get("genre")
        except Exception as exc:
            score = {"topic": idea_id, "exists": False, "score": 0.0, "pass": False,
                     "error": f"{type(exc).__name__}: {exc}"}
        results.append(score)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", choices=["series", "handdraw"])
    ap.add_argument("--series-dir")
    ap.add_argument("--video")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.video:
        report = _score_all([score_video(args.video)])
    elif args.line == "handdraw":
        report = _score_all(_run_handdraw(out))
    elif args.line == "series":
        report = _score_all(_run_series(Path(args.series_dir), out))
    else:
        raise SystemExit("give --video or --line")
    (out / "blackbox.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

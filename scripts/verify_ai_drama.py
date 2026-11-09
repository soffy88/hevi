"""Verify an ai_drama output directory (frame, subtitle, audio, lipsync checks).

Usage:
    python scripts/verify_ai_drama.py <episode_out_dir> [--json report.json]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _probe(path: Path) -> dict[str, Any]:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration",
         "-of", "json", str(path)], text=True,
    )
    return json.loads(out)


def _frame(path: Path, t: float, out: Path) -> np.ndarray:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", str(out)],
                   check=True)
    return np.asarray(Image.open(out).convert("RGB"), dtype=np.float32)


def _loudness(path: Path) -> float | None:
    proc = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True)
    value = None
    for line in proc.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            with contextlib.suppress(ValueError, IndexError):
                value = float(line.split("I:")[1].split("LUFS")[0].strip())
    return value


def verify(out: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    final = out / "final.mp4"
    add("final_exists", final.is_file() and final.stat().st_size > 0, str(final))
    if not final.is_file():
        return {"passed": False, "checks": checks}
    info = _probe(final)
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float((info.get("format") or {}).get("duration") or 0)
    add("video_9x16", (video.get("width"), video.get("height")) == (1080, 1920),
        {"width": video.get("width"), "height": video.get("height")})
    add("fps_30", video.get("r_frame_rate") == "30/1", video.get("r_frame_rate"))
    add("audio_stream", audio is not None, audio)
    add("duration", duration >= 20, round(duration, 3))
    loud = _loudness(final)
    add("loudness", loud is not None and abs(loud + 14) <= 1.5, loud)

    script = json.loads((out / "script.json").read_text(encoding="utf-8"))
    sb = json.loads((out / "storyboard.json").read_text(encoding="utf-8"))
    edit = json.loads((out / "edit_list.json").read_text(encoding="utf-8"))
    segments = sb.get("segments") or []
    game_pov = script.get("style") == "game_pov"
    add("segments_min", len(segments) >= (4 if game_pov else 6), len(segments))
    if not game_pov:
        add("two_characters", len(script.get("characters") or []) >= 2, len(script.get("characters") or []))
    script_lines = [(d.get("speaker"), d.get("text"), d.get("kind", "said"))
                    for sc in script.get("scenes") or [] for b in sc.get("beats") or []
                    for d in b.get("dialogue") or []]
    edit_lines = [(s.get("speaker"), s.get("text"), s.get("kind")) for s in edit.get("subtitles") or []]
    add("subtitles_verbatim", script_lines == edit_lines, {"script": len(script_lines), "edit": len(edit_lines)})
    text = (out / "final.srt").read_text(encoding="utf-8")
    add("subtitles_burned_source", all(str(t) in text for _, t, _ in script_lines), None)
    ass = (out / "assemble" / "final.ass").read_text(encoding="utf-8")
    add("inner_monologue_colour", "Style: Inner" in ass and "Style: Said" in ass and
        "&H0066D1FF" in ass and "&H00FFFFFF" in ass, None)
    add("ai_label", "AI 生成" in ass, None)

    meta = (json.loads((out / "segments.json").read_text(encoding="utf-8")).get("shots") or {}).get("meta") or {}
    lip = {k: v for k, v in meta.items() if v.get("lipsync")}
    good = [v for v in lip.values() if float(v.get("lipsync_corr") or 0) >= 0.35]
    if not game_pov:
        add("lipsync_present", len(lip) >= 3, len(lip))
        add("lipsync_correlated", len(good) >= 1, [round(float(v.get("lipsync_corr") or 0), 3) for v in lip.values()])

    ledger = out / "credit_ledger.jsonl"
    paid = 0.0
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "settle":
                paid += float(row.get("charged_cny") or 0)
    add("offline_no_spend", paid == 0.0, paid)

    frames_dir = out / "verify_frames"
    times = [2.0, duration * 0.2, duration * 0.4, duration * 0.6, duration * 0.8, max(1.0, duration - 2.0)]
    stats = []
    prev = None
    for i, t in enumerate(times):
        arr = _frame(final, t, frames_dir / f"f{i}_{t:.1f}.jpg")
        mean, std = float(arr.mean()), float(arr.std())
        diff = float(np.abs(arr - prev).mean()) if prev is not None else None
        stats.append({"t": round(t, 2), "mean": round(mean, 2), "std": round(std, 2),
                      "diff_from_prev": None if diff is None else round(diff, 2)})
        prev = arr
    add("frames_not_black", all(s["mean"] > 15 and s["std"] > 8 for s in stats), stats)
    add("frames_change", all(s["diff_from_prev"] is None or s["diff_from_prev"] > 1.0 for s in stats), stats)
    add("no_bgm", edit.get("bgm") is None, edit.get("bgm"))
    add("canvas_graph", (out / "canvas_graph.json").is_file(), str(out / "canvas_graph.json"))
    passed = all(c["ok"] for c in checks)
    return {"passed": passed, "checks": checks, "frames": stats}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    report = verify(Path(args.out_dir))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

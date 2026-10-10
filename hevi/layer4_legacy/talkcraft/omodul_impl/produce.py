"""Talkcraft production transaction (omodul layer: owns the side effects).

narration segments -> Piper TTS per sentence -> CPU word-level alignment ->
deterministic SHOTBOOK plan -> Remotion render of the vendored workbench
``Main`` composition (``hevi-remotion-talkcraft``) -> loudness normalise ->
9:16 reframe -> measured gates -> ``record.json`` + contact sheets.

Fail-closed: any missing local dependency raises; a failed gate is reported
as ``status="failed"`` with the measured numbers, never silently passed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.talkcraft.omodul_impl._whisper import WhisperAligner
from hevi.layer4_legacy.talkcraft.oprim_impl.sync import (
    FPS,
    AlignedChar,
    NarrationSegment,
    SentenceTiming,
    TalkcraftRecord,
)
from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG, concat_with_gaps, duration, piper_tts, run, sha256
from hevi.layer4_legacy.talkcraft.oskill_impl.shotbook import plan_project
from hevi.layer4_legacy.talkcraft.omodul_impl._gates import contact_sheet, measure

REPO = Path(__file__).resolve().parents[4]
REMOTION_DIR = Path(os.environ.get("HEVI_TALKCRAFT_REMOTION", REPO / "hevi-remotion-talkcraft"))
NODE_BIN = os.environ.get("HEVI_NODE_BIN", str(Path.home() / ".nvm/versions/node/v26.4.0/bin"))
GAP_S = 0.35
LEAD_S = 0.4


class TalkcraftError(RuntimeError):
    pass


def _load_cached_timings(path: Path, key: str) -> list[SentenceTiming] | None:
    """Reuse TTS+alignment only when the narration (and settings) are identical."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("key") != key:
        return None
    out = []
    for t in data["timings"]:
        chars = tuple(AlignedChar(**c) for c in t.pop("chars"))
        out.append(SentenceTiming(chars=chars, **t))
    return out


def _render(*, props_path: Path, out: Path, log: Path) -> float:
    cli = REMOTION_DIR / "node_modules/.bin/remotion"
    if not cli.exists():
        raise TalkcraftError(f"remotion CLI missing under {REMOTION_DIR} (run npm ci there)")
    env = dict(os.environ)
    env["PATH"] = NODE_BIN + os.pathsep + env.get("PATH", "")
    t0 = time.monotonic()
    cmd = [
        str(cli), "render", "src/remotion/index.ts", "Main", str(out),
        f"--props={props_path}", "--scale=2", "--log=error",
        f"--concurrency={os.environ.get('HEVI_TALKCRAFT_CONCURRENCY', '1')}",
    ]
    with open(log, "w") as fh:
        r = subprocess.run(cmd, cwd=REMOTION_DIR, env=env, stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode or not out.is_file():
        raise TalkcraftError(f"remotion render failed (exit {r.returncode}); see {log}")
    return time.monotonic() - t0


def _finish_landscape(raw: Path, out: Path) -> None:
    run([FFMPEG, "-y", "-v", "error", "-i", str(raw), "-c:v", "copy",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(out)])


def _reframe_portrait(src: Path, out: Path) -> None:
    """16:9 card stage centred on a blurred, slowly scaled copy of itself (9:16)."""
    fc = (
        "[0:v]split[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2,eq=brightness=-0.04[bg];"
        "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
    )
    run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)])


def produce_talkcraft(
    *,
    segments: list[NarrationSegment],
    output_dir: Path,
    line: str = "explainer",
    lang: str = "zh",
    name: str = "talkcraft",
    portrait: bool = True,
    aligner: WhisperAligner | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    work = output_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    t_all = time.monotonic()

    # 1) TTS per sentence (sentence edges are exact; ASR only refines inside)
    texts = [s for seg in segments for s in seg.sentences]
    if not texts:
        raise TalkcraftError("no narration sentences")
    key = hashlib.sha256(json.dumps([lang, GAP_S, LEAD_S, texts], ensure_ascii=False).encode()).hexdigest()
    voice = work / "voice.wav"
    ts_file = work / "timestamps.json"
    cached = _load_cached_timings(ts_file, key) if voice.is_file() else None
    al: WhisperAligner | None = aligner
    if cached is not None:
        timings = cached
        alignment_cache = "hit"
    else:
        alignment_cache = "miss"
        parts = []
        for i, text in enumerate(texts):
            p = work / f"vo_{i:03d}.wav"
            piper_tts(text=text, out_wav=p, lang=lang)
            parts.append(p)
        starts = concat_with_gaps(parts=parts, gap_s=GAP_S, lead_s=LEAD_S, out_wav=voice)

        # 2) word-level alignment on CPU
        al = al or WhisperAligner()
        timings = []
        for i, (text, p, st) in enumerate(zip(texts, parts, starts, strict=True)):
            timings.append(al.align(index=i, text=text, audio_path=str(p), start_s=st, end_s=st + duration(p), language=lang))
        ts_file.write_text(json.dumps({"key": key, "timings": [asdict(t) for t in timings]}, ensure_ascii=False, indent=1))
    total_s = duration(voice)

    # 3) plan
    job = output_dir.name
    pub = REMOTION_DIR / "public/runs" / job
    pub.mkdir(parents=True, exist_ok=True)
    shutil.copy2(voice, pub / "voice.wav")
    plan = plan_project(name=name, segments=segments, timings=timings, voice_file=f"runs/{job}/voice.wav", total_s=total_s)
    (output_dir / "shotbook.json").write_text(json.dumps(plan.to_json(), ensure_ascii=False, indent=1))
    props = work / "props.json"
    props.write_text(json.dumps({"project": plan.project, "renderExact": True}, ensure_ascii=False))
    end_frame = max(c["start"] + c["duration"] for t in plan.project["tracks"] for c in t["clips"])
    expected_s = end_frame / FPS

    # 4) render + finish
    raw = work / "render_raw.mp4"
    render_s = _render(props_path=props, out=raw, log=work / "render.log")
    landscape = output_dir / f"{line}_landscape.mp4"
    _finish_landscape(raw, landscape)
    outputs = [(landscape, 1920, 1080)]
    if portrait:
        port = output_dir / f"{line}_portrait.mp4"
        _reframe_portrait(landscape, port)
        outputs.append((port, 1080, 1920))

    # 5) gates
    records = []
    for path, w, h in outputs:
        gates, facts = measure(path=path, expected_s=expected_s, timings=timings, cards=plan.card_ids(), expect_w=w, expect_h=h)
        sheet = contact_sheet(path=path, out=path.with_suffix(".sheet.jpg"), total_s=facts["duration_s"])
        rec = TalkcraftRecord(
            line=line,
            video_path=str(path),
            sha256=sha256(path),
            width=facts["width"],
            height=facts["height"],
            duration_s=round(facts["duration_s"], 3),
            fps=round(facts["fps"], 3),
            render_seconds=round(render_s, 1),
            cards_used=plan.card_ids(),
            alignment={
                "aligner": timings[0].aligner,
                "model": getattr(al, "model_dir", "") if al else "cached",
                "cache": alignment_cache,
                "sentences": len(timings),
                "match_ratio": [t.match_ratio for t in timings],
                "anchors": [{"word": b.anchor_word, "offset_s": b.anchor_offset_s} for b in plan.beats],
            },
            gates=gates,
            provenance={
                "renderer": "hevi-remotion-talkcraft (workbench Main, vendored from video-talkcraft 4cd673d)",
                "tts": "piper local (" + lang + ")",
                "paid_calls": 0,
                "gpu": False,
                "contact_sheet": str(sheet),
                "freeze_spans": facts["freeze_spans"],
            },
        )
        rec.passed = all(g.passed for g in gates)
        records.append(rec.to_json())
    status = "succeeded" if all(r["passed"] for r in records) else "failed"
    result = {"status": status, "line": line, "wall_seconds": round(time.monotonic() - t_all, 1), "records": records}
    (output_dir / "record.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    return result

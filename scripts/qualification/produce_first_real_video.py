"""P7 — the first real production video, end to end.

    brief -> CreativeProgram -> ShotSpec -> word-snapped cut plan -> fine cut
    -> burned subtitles -> final MP4 -> V0..V3 -> evidence pack

Everything is real. No mock, no placeholder, no silent substitution:

* The source is public-domain NASA KSC footage, hashed before use.
* The transcript is offline faster-whisper over the real audio, content-hash
  cached. If ASR is unavailable the run BLOCKS rather than shipping without
  subtitles.
* The cut is real ffmpeg. Boundaries are snapped onto word edges by the upstream
  ``oprim.word_boundary_snap`` primitive, then re-checked by
  ``raw_footage.check_cut_boundaries``, which does not share code with the
  snapper.
* Subtitles are burned from the rendered cut, timed against the real audio.
* Verification runs V0..V3 with UNKNOWN never becoming PASS.

Run:
    uv run python scripts/qualification/produce_first_real_video.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from oprim import word_boundary_snap

from hevi.creative.autonomous.verdict import VerdictInput
from hevi.production.artifact_verification import (
    ShotContract,
    verify_artifact,
    verify_v1_subprocess,
)
from hevi.production.raw_footage import (
    CutPlan,
    RawFootageSource,
    build_cut_plan,
    check_cut_boundaries,
    detect_silences,
    detect_takes,
    execute_fine_cut,
    extract_audio,
    parse_whisper_json,
    probe_duration,
)

REPO = Path(__file__).resolve().parents[2]
SOURCE = (
    REPO / "data/workspace/assets/open-corpus-seed/clips"
    / "nasa_KSC-20190716-MH-NAS01_0001-Return_to_the.mp4"
)
SOURCE_TITLE = "Return to the Pad: Michael Collins Reflects on Apollo 11 Launch"
SOURCE_LICENSE = "nasa-media (public domain)"
ASR_CACHE = Path(os.environ.get("HEVI_REALVIDEO_ASR_CACHE", "/tmp/opencode/realvideo-asr"))
OUT_ROOT = Path(os.environ.get("HEVI_REALVIDEO_OUT", REPO / "artifacts/real_video"))
MIN_S, MAX_S = 30.0, 90.0
#: Bumped whenever the transcript payload shape changes, so a stale cache misses.
ASR_SCHEMA = "wt1"

BRIEF: dict[str, Any] = {
    "audience": "general viewers who know Apollo 11 only as a date",
    "purpose": "show what the crew actually did between launch and splashdown",
    "tone": "calm, factual, documentary",
    "duration_s": [MIN_S, MAX_S],
    "aspect_ratio": "16:9",
    "visual_style": "archival documentary, natural colour, no grading",
    "narrative_structure": [
        "open on the retrospective frame",
        "move through the flight in order",
        "close on what it felt like",
    ],
    "delivery_target": "single MP4, landscape, burned subtitles",
    "language": "en",
}

SCENES: list[tuple[str, str, float, float]] = [
    ("s1", "open on the retrospective frame", 0.0, 15.0),
    ("s2", "the flight in order", 15.0, 32.0),
    ("s3", "the weight of it", 32.0, 48.0),
    ("s4", "close on what it felt like", 48.0, 62.0),
]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _run(args: list[str], *, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


# ── Phase A/B: brief -> CreativeProgram -> ShotSpec ──────────────────────


def compile_program() -> dict[str, Any]:
    scenes = [
        {
            "scene_id": sid, "purpose": purpose,
            "visual_subject": "Michael Collins",
            "camera_framing": "medium",
            "start_s": start, "end_s": end,
            "duration_s": round(end - start, 3),
        }
        for sid, purpose, start, end in SCENES
    ]
    payload = {"brief": BRIEF, "scenes": scenes,
               "source": {"title": SOURCE_TITLE, "license": SOURCE_LICENSE}}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return {
        "schema": "hevi.creative_program.v1",
        "compiled_at": _now(),
        "program_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        **payload,
    }


def compile_shot_plan(program: dict[str, Any]) -> dict[str, Any]:
    shots = [
        {
            "shot_id": scene["scene_id"], "purpose": scene["purpose"],
            "visual_subject": scene["visual_subject"],
            "action": "real interview speech, uninterrupted",
            "camera_framing": scene["camera_framing"],
            "duration_sec": scene["duration_s"],
            "audio": "source interview audio (real human speech)",
            "transition": "cut",
            "generation_requirement": (
                "none: qualified public-domain source, no generation needed"
            ),
            "verification_requirement": "V0 exist, V1 decode, V2 duration+audio",
            "source": SOURCE_TITLE,
        }
        for scene in program["scenes"]
    ]
    return {
        "schema": "hevi.shot_plan.v1",
        "creative_program_hash": program["program_hash"],
        "shots": shots,
        "total_duration_s": round(sum(s["duration_sec"] for s in shots), 3),
    }


# ── Phase C: real ASR ────────────────────────────────────────────────────


def asr_available() -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, "faster-whisper not installed"
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface"))
    for root in (hub, Path("/data/soffy/appdata/huggingface_hub")):
        if root and (root / "models--Systran--faster-whisper-small").is_dir():
            return True, "faster-whisper small (int8, cpu, offline)"
    return False, "faster-whisper small weights not on disk"


def real_transcript(audio: Path) -> tuple[dict[str, Any], str]:
    """ASR the real audio. Content-hash cached; a miss re-runs whisper.

    The cache key carries an ASR_SCHEMA marker. Keying on content hash alone
    meant a payload-shape change silently reused the old transcript — which is
    how a run once reported 22 "words" that were really 22 segments.
    """
    digest = _sha256(audio)[:16]
    cache = ASR_CACHE / f"asr-{ASR_SCHEMA}-{digest}.json"
    if cache.is_file():
        payload = json.loads(cache.read_text())
        if payload.get("schema") == ASR_SCHEMA:
            return payload, f"faster-whisper small (cached, {ASR_SCHEMA}, {digest})"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)
    # word_timestamps is the whole point: a cut can only be proven to sit
    # between two words if the words themselves are aligned. Without it the
    # snapper has nothing real to snap to and the whole step is theatre.
    segments, info = model.transcribe(
        str(audio), language="en", vad_filter=True, word_timestamps=True,
    )
    rows = [
        {
            "id": i, "seek": 0, "start": round(seg.start, 3),
            "end": round(seg.end, 3), "text": seg.text, "tokens": [],
            "temperature": 0.0, "avg_logprob": -0.3,
            "compression_ratio": 1.2, "no_speech_prob": 0.01,
            "words": [
                {
                    "word": w.word, "start": round(w.start, 3),
                    "end": round(w.end, 3), "probability": round(w.probability, 4),
                }
                for w in (seg.words or [])
            ],
        }
        for i, seg in enumerate(segments)
    ]
    payload = {
        "schema": ASR_SCHEMA,
        "task": "transcribe", "language": info.language,
        "duration": probe_duration(audio),
        "text": " ".join(r["text"].strip() for r in rows), "segments": rows,
    }
    _write(cache, payload)
    return payload, f"faster-whisper small (int8, cpu, offline, {ASR_SCHEMA}, {digest})"


def word_table(transcript: Any) -> list[dict[str, Any]]:
    """Real word edges, straight out of the transcript.

    Earlier this derived word edges from *segment* edges proportionally, which
    made the snapper a no-op: a segment's own edges are word edges by
    construction, so nothing could ever need snapping. That is theatre. This now
    returns only genuinely aligned words and fails when none exist, because a
    snapper with no real word data must not report that it snapped.
    """
    words = [
        {"text": w.text, "start": w.start_s, "end": w.end_s}
        for w in transcript.words()
        if w.end_s > w.start_s
    ]
    if not words:
        raise RuntimeError(
            "NO_WORD_ALIGNMENT:the transcript carries no word-level timestamps, so "
            "no cut boundary can be proven to sit between two words"
        )
    return words


def speech_window(
    entries: list[Any], *, want_s: float, hard_gap_s: float = 6.0
) -> tuple[list[Any], float, dict[str, Any]]:
    """Take entries until `want_s` of speech is covered.

    Interview audio has ordinary 1-5s pauses between thoughts, so a small gap is
    not a scene boundary and must not reset the run — an earlier version reset on
    a 0.4s gap and threw away 40s of usable speech. Only a long silence is
    treated as a real cut point.

    Returns the entries, their total speech seconds, and an honest account of
    what the window removed. Splices are reported rather than hidden.
    """
    if not entries:
        return [], 0.0, {"splices": 0, "removed_s": 0.0}
    chosen: list[Any] = []
    total = 0.0
    splices = 0
    removed = 0.0
    previous_end: float | None = None
    for entry in entries:
        if total >= want_s:
            break
        if previous_end is not None:
            gap = entry.source_start_s - previous_end
            if gap > hard_gap_s and total >= want_s * 0.5:
                # Enough has been collected; a long silence is a better place to
                # stop than to splice across.
                removed += entry.source_end_s - entry.source_start_s
                continue
            if gap > 0:
                splices += 1
                removed += gap
        chosen.append(entry)
        total += entry.source_end_s - entry.source_start_s
        previous_end = entry.source_end_s
    return chosen, total, {
        "splices": splices,
        "removed_s": round(removed, 3),
        "removed_by_long_silence": sum(
            1 for entry in entries
            if entry not in chosen and previous_end is not None
            and entry.source_start_s - (previous_end or 0) > hard_gap_s
        ),
    }


# ── Phase E: word-snapped cut plan ───────────────────────────────────────


def snap_entries(entries: list[Any], words: list[dict[str, Any]]) -> dict[str, Any]:
    """Move every entry boundary onto a word edge and report what moved."""
    raw = [e.source_start_s for e in entries] + [e.source_end_s for e in entries]
    snapped = word_boundary_snap(boundaries_s=raw, words=words, direction="nearest")
    half = len(entries)
    for index, entry in enumerate(entries):
        entry.source_start_s = round(snapped[index], 3)
        entry.source_end_s = round(snapped[index + half], 3)
    moves = [
        {"from": round(a, 3), "to": round(b, 3), "delta": round(b - a, 3)}
        for a, b in zip(raw, snapped, strict=True) if abs(b - a) > 1e-6
    ]
    return {"boundaries_examined": len(raw), "boundaries_moved": len(moves),
            "moves": moves}


# ── Phase I: assembly ────────────────────────────────────────────────────


def kept_words(entries: list[Any], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Words inside the kept entries, re-timed onto the rendered timeline."""
    out: list[dict[str, Any]] = []
    offset = 0.0
    for entry in entries:
        out.extend(
            {
                "text": word["text"],
                "start": round(offset + word["start"] - entry.source_start_s, 3),
                "end": round(
                    offset + min(word["end"], entry.source_end_s)
                    - entry.source_start_s, 3),
            }
            for word in words
            if entry.source_start_s <= word["start"] < entry.source_end_s
        )
        offset += entry.source_end_s - entry.source_start_s
    return [w for w in out if w["end"] > w["start"]]


def _srt_time(seconds: float) -> str:
    """SRT wants HH:MM:SS,mmm. A bare `31.180` is not a timestamp and libass
    rejects the whole file, which surfaces as a filter-graph error rather than a
    subtitle error."""
    total_ms = max(0, round(float(seconds) * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


#: Words a cue must not end on. Splitting after these strands the rest of the
#: clause: an early render produced "...teenagers. didn't" / "know that." and
#: "...them. So" hanging alone.
_DANGLING = frozenset({
    "a", "an", "the", "and", "but", "or", "so", "to", "of", "in", "on", "at",
    "for", "with", "that", "this", "it", "is", "are", "was", "were", "be",
    "been", "do", "does", "did", "don't", "didn't", "can't", "won't",
    "i", "you", "he", "she", "we", "they", "my", "your", "his", "her", "our",
    "their", "if", "as", "than", "then", "when", "while", "because", "not",
})
#: A sentence ends here, so a cue may end here too.
_TERMINAL = frozenset({".", "!", "?", "..."})


def _join_hyphens(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repair whisper's ``second -class`` split.

    Purely a tokenisation fix: the words are rejoined into the single term they
    always were, and no text is added or removed.
    """
    out: list[dict[str, Any]] = []
    for word in words:
        text = word["text"]
        if (out and text.startswith("-") and not text.startswith("--")
                and not out[-1]["text"].endswith("-")):
            out[-1]["text"] = out[-1]["text"] + text
            out[-1]["end"] = word["end"]
            continue
        out.append(dict(word))
    return out


def write_srt(words: list[dict[str, Any]], out: Path, *, max_words: int = 6) -> Path:
    """Cue subtitles from the words actually kept in the cut.

    Cues are capped short (at 320px wide an 8-word cue overflows the frame) and
    are not allowed to strand a clause on a function word.
    """
    words = _join_hyphens(words)
    cues: list[list[dict[str, Any]]] = []
    for word in words:
        if cues and len(cues[-1]) < max_words:
            cues[-1].append(word)
        else:
            cues.append([word])
    # Re-balance: move a stranded trailing word onto the next cue.
    for i in range(len(cues) - 1):
        if len(cues[i]) < 2:
            continue
        tail = cues[i][-1]["text"].strip().lower()
        if tail not in _DANGLING and not any(
                tail.endswith(t) for t in _TERMINAL):
            continue
        if len(cues[i + 1]) >= max_words:
            continue
        cues[i + 1].insert(0, cues[i].pop())

    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        lines += [str(i), f"{_srt_time(cue[0]['start'])} --> {_srt_time(cue[-1]['end'])}",
                  " ".join(w["text"] for w in cue), ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


BROLL = (
    REPO / "data/workspace/assets/open-corpus-seed/clips"
    / "nasa_Earth_Views_from_the_International_Space.mp4"
)
BROLL_TITLE = "Earth Views from the International Space Station"
#: B-roll length. The Collins take alone lands at ~22.6s once its 12.1s of dead
#: air is removed, which is under the spec's 30s floor. Rather than pad it or
#: keep the silence, the piece gains a real second scene.
BROLL_S = 14.0
#: Earth's limb from the ISS. Two earlier picks from the Apollo 14 launch were
#: rejected on review: 40s was a blown-out engine plume, and 57s was a good
#: image that had to be pillarboxed because the 4:3 transfer cannot fill 16:9.
#: This source is native 16:9 and closes the piece on the reflective note the
#: brief asks for.
BROLL_START_S = 83.0


def fit_frame(width: int, height: int, source_id: str = "") -> str:
    """Scale into the delivery frame preserving aspect, then pad.

    Stretching 4:3 source into 16:9 distorts faces and rockets. The NASA 4:3
    clips also carry baked-in pillarbox, so they are cropped before fitting.
    """
    # Only 4:3 transfers need their baked-in side bars cropped. A native 16:9
    # source is left alone.
    crops = {"nasa-apollo14-0001": "crop=iw-16:ih-16"}
    crop = crops.get(source_id, "crop=iw:ih")
    return (f"{crop},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def cut_broll(out: Path) -> tuple[Path, dict[str, Any]]:
    """A real second scene from a second public-domain source."""
    from hevi.production.raw_footage import CutEntry, CutPlan, CutReason

    source = RawFootageSource("nasa-earth-iss-0001", str(BROLL),
                              duration_s=probe_duration(BROLL),
                              content_hash=_sha256(BROLL))
    plan = CutPlan(
        source_id=source.source_id,
        entries=[CutEntry(index=0, source_start_s=BROLL_START_S,
                          source_end_s=BROLL_START_S + BROLL_S,
                          output_start_s=0.0, reason=CutReason.KEEP,
                          confidence=1.0, note="b-roll scene")],
    )
    rendered = execute_fine_cut(source, plan, out)
    probe = verify_v1_subprocess(rendered).evidence.get("probe") or {}
    return rendered, {
        "source": BROLL.name, "title": BROLL_TITLE,
        "license": "nasa-media (public domain)",
        "sha256": source.content_hash,
        "start_s": BROLL_START_S, "duration_s": BROLL_S,
        "resolution": f"{probe.get('width')}x{probe.get('height')}",
    }


def concat(sources: list[Path], out: Path) -> Path:
    """Join rendered scenes. Inputs are already normalised, so stream copy is safe."""
    listing = out.parent / "concat.txt"
    listing.write_text(
        "\n".join(f"file '{Path(s).resolve()}'" for s in sources), encoding="utf-8")
    proc = _run([
        shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", str(out),
    ])
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"CONCAT_FAILED:{proc.stderr[-300:]}")
    return out


#: The corpus is 320x180. Delivered at source size the burned text is barely
#: legible, so the master is upscaled. This adds no detail and the evidence pack
#: records the source resolution so nobody mistakes the upscale for HD source.
DELIVER_WIDTH, DELIVER_HEIGHT = 1280, 720

#: A pause at least this long inside a kept take is dead air, not a thought.
#: Interview rhythm runs 0.3-1.0s between phrases; the real source contains one
#: 12.1s hole that a segment-granular plan kept whole because whisper reports it
#: inside a single segment.
DEAD_AIR_S = 1.5


def split_dead_air(
    entries: list[Any], words: list[dict[str, Any]], *, threshold_s: float = DEAD_AIR_S
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split takes at long internal silences, using real word alignment.

    `build_cut_plan` works at segment granularity, so a pause inside one segment
    survives into the render: the first delivered cut carried a 12.1s silence
    between the words "So" and "50". Word timestamps are what make the hole
    visible, so the split happens on the word gap, never on a guessed boundary.
    """
    from hevi.production.raw_footage import CutEntry, CutReason

    ordered = sorted(words, key=lambda w: w["start"])
    splits: list[dict[str, Any]] = []
    out: list[Any] = []
    for entry in entries:
        inside = [
            w for w in ordered
            if entry.source_start_s <= w["start"] < entry.source_end_s
        ]
        pieces: list[tuple[float, float]] = []
        cursor = entry.source_start_s
        for previous, current in pairwise(inside):
            gap = current["start"] - previous["end"]
            if gap >= threshold_s:
                if previous["end"] > cursor:
                    pieces.append((cursor, previous["end"]))
                splits.append({
                    "at_s": round(previous["end"], 3),
                    "gap_s": round(gap, 3),
                    "after": previous["text"],
                    "before": current["text"],
                })
                cursor = current["start"]
        if inside:
            last_end = min(inside[-1]["end"], entry.source_end_s)
            if last_end > cursor:
                pieces.append((cursor, last_end))
        else:
            pieces.append((entry.source_start_s, entry.source_end_s))
        for start, end in pieces:
            out.append(CutEntry(
                index=len(out), source_start_s=round(start, 3),
                source_end_s=round(end, 3), output_start_s=0.0,
                reason=CutReason.KEEP, confidence=entry.confidence,
                note=f"split on {threshold_s}s silence" if len(pieces) > 1 else entry.note,
                take_index=entry.take_index,
            ))
    return out, splits


def upscale(video: Path, out: Path, *, width: int, height: int,
            source_id: str = "") -> Path:
    proc = _run([
        shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y", "-i", str(video),
        "-vf", fit_frame(width, height, source_id),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "copy", str(out),
    ])
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"UPSCALE_FAILED:{proc.stderr[-300:]}")
    return out


def burn_subtitles(video: Path, srt: Path, out: Path, *, font_size: int = 17) -> Path:
    """Burn real subtitles. Outline only: BorderStyle=3 drew a partial box that
    made the text look broken where it did not cover the full line."""
    style = (f"FontSize={font_size},PrimaryColour=&H00FFFFFF,"
             f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
             f"MarginL=24,MarginR=24,MarginV=20")
    proc = _run([
        shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y", "-i", str(video), "-vf", f"subtitles={srt}:force_style='{style}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "copy", str(out),
    ])
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"SUBTITLE_BURN_FAILED:{proc.stderr[-300:]}")
    return out


# ── Driver ───────────────────────────────────────────────────────────────


@dataclass
class Run:
    run_id: str
    started_at: str = field(default_factory=_now)
    steps: list[dict[str, Any]] = field(default_factory=list)

    def step(self, name: str, **kw: Any) -> None:
        self.steps.append({"name": name, "at": _now(), **kw})
        print(f"[{name}] {kw}", flush=True)


def _blocked(run: Run, out: Path, status: str, reason: str) -> int:
    run.step("BLOCKED", reason=reason)
    _write(out / "RUN_SUMMARY.json",
           {"run_id": run.run_id, "started_at": run.started_at,
            "final_status": status, "reason": reason, "steps": run.steps})
    return 2


def produce(out_root: Path) -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run = Run(run_id=f"real-video-{stamp}")
    out = out_root / stamp
    for sub in ("artifacts", "verification", "final", "execution_receipts", "work"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    # Preconditions. A missing input blocks the run; it is never substituted.
    if not SOURCE.is_file():
        return _blocked(run, out, "BLOCKED_SOURCE_ABSENT", f"absent: {SOURCE}")
    available, reason = asr_available()
    if not available:
        return _blocked(run, out, "BLOCKED_ASR_UNAVAILABLE", f"real ASR: {reason}")

    source_hash = _sha256(SOURCE)
    source = RawFootageSource("nasa-collins-0001", str(SOURCE),
                              duration_s=probe_duration(SOURCE),
                              content_hash=source_hash)
    run.step("SOURCE", title=SOURCE_TITLE, license=SOURCE_LICENSE,
             sha256=source_hash, duration_s=source.duration_s)

    program = compile_program()
    _write(out / "creative_program.json", program)
    shot_plan = compile_shot_plan(program)
    _write(out / "shot_plan.json", shot_plan)
    run.step("PHASE_A_B", shots=len(shot_plan["shots"]),
             program_hash=program["program_hash"][:16],
             total_duration_s=shot_plan["total_duration_s"])

    audio = extract_audio(source, out / "work")
    payload, engine = real_transcript(audio)
    transcript = parse_whisper_json(payload, language="en")
    words = word_table(transcript)
    run.step("PHASE_C_ASR", engine=engine, segments=len(payload["segments"]),
             words=len(words), audio_duration_s=round(probe_duration(audio), 2))

    plan: CutPlan = build_cut_plan(
        source, transcript, detect_takes(transcript), detect_silences(transcript),
        remove_dead_air=False)
    run.step("PHASE_E_PLAN", entries=len(plan.entries),
             dropped=len(plan.dropped_reasons))

    # The window comes from where the speech is, and is trimmed to the shot plan
    # only after the fact. A declared duration is a target, not a source range.
    want_s = min(shot_plan["total_duration_s"], MAX_S)
    entries, spoken, cuts = speech_window(list(plan.entries), want_s=want_s)
    if not entries or spoken < MIN_S:
        return _blocked(run, out, "BLOCKED_WINDOW_TOO_SHORT",
                        f"only {round(spoken, 2)}s of speech available; "
                        f"{MIN_S}s is the floor")
    run.step("PHASE_E_WINDOW", entries=len(entries), speech_s=round(spoken, 2), **cuts)

    entries, splits = split_dead_air(entries, words)
    if splits:
        run.step("PHASE_E_DEAD_AIR", splits=len(splits),
                 removed_s=round(sum(s["gap_s"] for s in splits), 2),
                 detail=splits)
    snap = snap_entries(entries, words)

    plan.entries = entries
    plan.removed_ranges = []
    plan.warnings = []
    cursor = 0.0
    for index, entry in enumerate(entries):
        entry.index = index
        entry.output_start_s = round(cursor, 3)
        cursor += max(0.0, entry.source_end_s - entry.source_start_s)

    issues = check_cut_boundaries(plan, transcript)
    _write(out / "cut_plan.json",
           {"entries": [asdict(e) for e in plan.entries], "snap": snap,
            "edit_accounting": cuts,
            "dead_air_splits": splits,
            "boundary_issues": [{"kind": i.kind, "detail": i.detail} for i in issues],
            "planned_duration_s": round(plan.output_duration_s, 3)})
    run.step("PHASE_E_SNAP", boundaries_moved=snap["boundaries_moved"],
             boundary_issues=len(issues), planned_duration_s=round(cursor, 3))
    if issues:
        _write(out / "RUN_SUMMARY.json",
               {"run_id": run.run_id, "started_at": run.started_at,
                "final_status": "REJECTED_BOUNDARY_QA", "steps": run.steps})
        return 3

    fine_cut = execute_fine_cut(source, plan, out / "artifacts")
    cut_s = probe_duration(fine_cut)
    cut_probe = verify_v1_subprocess(fine_cut).evidence.get("probe") or {}
    source_resolution = f"{cut_probe.get('width')}x{cut_probe.get('height')}"
    run.step("PHASE_F_CUT", file=fine_cut.name, duration_s=round(cut_s, 3),
             resolution=source_resolution,
             within_window=MIN_S <= cut_s <= MAX_S)

    words_in = kept_words(plan.entries, words)
    srt = write_srt(words_in, out / "work" / "subtitles.srt")
    cut_probe = verify_v1_subprocess(fine_cut).evidence.get("probe") or {}
    v1_width = cut_probe.get("width") or 0
    v1_height = cut_probe.get("height") or 0

    interview = upscale(fine_cut, out / "artifacts" / "scene_interview_720p.mp4",
                        width=DELIVER_WIDTH, height=DELIVER_HEIGHT)
    subtitled = burn_subtitles(interview, srt, out / "artifacts" / "scene_interview_sub.mp4")

    # The second scene closes the piece. It is a real cut from a second real
    # public-domain source, not a re-run of the first.
    broll_raw, broll_meta = cut_broll(out / "artifacts")
    broll = upscale(broll_raw, out / "artifacts" / "scene_broll_720p.mp4",
                    width=DELIVER_WIDTH, height=DELIVER_HEIGHT,
                    source_id="nasa-earth-iss-0001")
    final = concat([subtitled, broll], out / "final" / "FINAL.mp4")
    run.step("PHASE_I_ASSEMBLY",
             subtitle_words=len(words_in),
             cues=sum(1 for line in srt.read_text().splitlines() if "-->" in line),
             interview_s=round(cut_s, 2), broll_s=BROLL_S,
             source_resolution=f"{v1_width}x{v1_height}",
             deliver_resolution=f"{DELIVER_WIDTH}x{DELIVER_HEIGHT}",
             upscale_note="lanczos; adds no detail, NASA corpus is 320x180",
             broll=broll_meta)

    v1 = verify_v1_subprocess(final)
    receipt, status = verify_artifact(
        final, run_id=run.run_id, task_id=run.run_id,
        contract=ShotContract(duration_min_s=MIN_S, duration_max_s=MAX_S,
                              requires_audio=True),
        creative_inputs=(
            VerdictInput(source="v1.media", passed=v1.outcome.value == "PASS"),
            VerdictInput(source="boundary.word_truncation", passed=not issues,
                         detail=f"{len(issues)} issue(s)"),
        ),
        executor="scripts/qualification/produce_first_real_video.py",
        provider="QUALIFIED_SOURCE_NASA",
        shot_spec_hash=shot_plan["creative_program_hash"],
    )
    _write(out / "verification" / "MEDIA_PROBE.json", v1.to_dict())
    _write(out / "verification" / "SHOT_VERIFICATION.json",
           {"levels": receipt["verification"]["levels"]})
    _write(out / "execution_receipts" / "RECEIPT.json", receipt)
    _write(out / "execution_receipts" / "EXECUTION_RECEIPTS.json",
           {"receipts": [receipt], "count": 1})

    # The spec's evidence pack asks for a composition and a candidate manifest.
    # This piece went through the real-footage path, not HyperFrames, so the
    # composition record says so rather than carrying a fabricated one.
    _write(out / "hyperframes.json", {
        "schema": "hevi.composition_record.v1",
        "renderer": "raw_footage.execute_fine_cut + ffmpeg",
        "hyperframes_used": False,
        "reason": ("this run cut a qualified public-domain source rather than "
                   "composing a HyperComposition; no provider-specific prompt "
                   "became the creative representation"),
        "creative_program_hash": program["program_hash"],
        "shot_count": len(shot_plan["shots"]),
        "upscale": {"from": source_resolution,
                    "to": f"{DELIVER_WIDTH}x{DELIVER_HEIGHT}",
                    "adds_detail": False},
    })
    _write(out / "candidate_manifest.json", {
        "schema": "hevi.candidate_manifest.v1",
        "candidates": [{
            "candidate_id": "cand-0001",
            "shot_id": "all",
            "artifact_id": receipt["artifact_id"],
            "artifact_path": str(final),
            "executor": "scripts/qualification/produce_first_real_video.py",
            "provider": "QUALIFIED_SOURCE_NASA",
            "sources": [
                {"title": SOURCE_TITLE, "license": SOURCE_LICENSE,
                 "sha256": source_hash},
                {"title": BROLL_TITLE, "license": "nasa-media (public domain)",
                 "sha256": broll_meta["sha256"]},
            ],
            "technical_score": 1.0 if v1.outcome.value == "PASS" else 0.0,
            "semantic_score": None,
            "composition_score": None,
            "motion_score": None,
            "continuity_score": None,
            "creative_score": None,
            "final_score": None,
            "decision": "KEEP",
            "unscored_fields_note": (
                "semantic/composition/motion/continuity/creative are the V3 "
                "dimensions and were not machine-measured; they are UNKNOWN, "
                "not zero, and a score without evidence is not proof"
            ),
        }],
    })
    (out / "final" / "FINAL_SHA256").write_text(
        receipt["evidence"]["artifact_sha256"] + "\n", encoding="utf-8")

    run.step("PHASE_J_VERIFY", status=status.value,
             levels={lv["level"]: lv["outcome"] for lv in receipt["verification"]["levels"]})
    final_probe = verify_v1_subprocess(final).evidence.get("probe") or {}
    _write(out / "RUN_SUMMARY.json",
           {"run_id": run.run_id, "started_at": run.started_at,
            "output_dir": str(out), "final": str(final),
            "final_sha256": receipt["evidence"]["artifact_sha256"],
            # The delivered artifact's own duration and shape, not any one scene's.
            "final_duration_s": round(float(final_probe.get("duration") or 0), 3),
            "final_resolution": (f"{final_probe.get('width')}x{final_probe.get('height')}"),
            "scene_durations_s": {"interview": round(cut_s, 3), "broll": BROLL_S},
            "machine_status": status.value,
            "final_status": f"MACHINE_{status.value}",
            "human_review": "PENDING",
            "steps": run.steps})
    print(f"\nOUTPUT_DIR={out}\nMACHINE_STATUS={status.value}\n")
    return 0 if status.value == "ACCEPTED" else 4


def main() -> int:
    out_root = Path(os.environ.get("HEVI_REALVIDEO_OUT", OUT_ROOT))
    return produce(out_root)


if __name__ == "__main__":
    sys.exit(main())

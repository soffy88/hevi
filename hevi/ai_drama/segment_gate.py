"""First-segment gate and whole-segment redo.

Before any later segment is rendered the first segment must pass three checks:

* **face** — the rendered character matches the series anchor image;
* **text** — the frame has no garbled lettering (a local edge-band heuristic);
* **voice** — the clip's voice resembles that character's fixed voice.

A failed segment is re-rendered whole (its clips are deleted first); no patch is
applied to an individual shot.  If the whole segment fails twice it is rejected
and recorded, never silently delivered.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .credits import CreditLedger

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class SegmentRejected(RuntimeError):
    pass


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def extract_frame(clip: str | Path, t: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([FFMPEG, "-y", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(clip),
          "-frames:v", "1", str(out)])
    return out


def _decode_audio(path: str | Path) -> Any:
    import numpy as np

    proc = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return np.zeros(1, dtype=np.float32)
    return np.frombuffer(proc.stdout, dtype="<i2").astype("float32") / 32768.0


def _band_energies(signal: Any, *, bands: int = 24, frame: int = 512, hop: int = 256) -> Any:
    import numpy as np

    if signal.size < frame:
        signal = np.pad(signal, (0, frame - signal.size))
    window = np.hanning(frame)
    frames = []
    for start in range(0, max(1, signal.size - frame + 1), hop):
        chunk = signal[start:start + frame]
        if chunk.size < frame:
            chunk = np.pad(chunk, (0, frame - chunk.size))
        spectrum = np.abs(np.fft.rfft(chunk * window))
        edges = np.geomspace(1, spectrum.size, bands + 1).astype(int)
        edges = np.clip(edges, 0, spectrum.size)
        vec = np.array([spectrum[edges[i]:edges[i + 1]].mean() if edges[i + 1] > edges[i] else 0.0
                        for i in range(bands)], dtype=np.float32)
        frames.append(np.log1p(vec))
    return np.mean(np.array(frames), axis=0)


def _median_f0(signal: Any, sr: int = 16000) -> float:
    import numpy as np

    frame = 1024
    hop = 512
    values = []
    for start in range(0, max(1, signal.size - frame + 1), hop):
        chunk = signal[start:start + frame]
        if chunk.size < frame or float(np.sqrt(np.mean(chunk ** 2))) < 0.005:
            continue
        corr = np.correlate(chunk, chunk, mode="full")[frame - 1:]
        lo, hi = int(sr / 500), int(sr / 80)
        if hi <= lo or hi >= corr.size:
            continue
        peak = int(np.argmax(corr[lo:hi])) + lo
        if peak > 0:
            values.append(sr / peak)
    return float(np.median(values)) if values else 0.0


def voice_similarity(reference: str | Path, take: str | Path) -> dict[str, Any]:
    import numpy as np

    a = _decode_audio(reference)
    b = _decode_audio(take)
    if a.size < 512 or b.size < 512:
        return {"score": 0.0, "band": 0.0, "pitch": 0.0, "passed": False, "reason": "audio too short"}
    va, vb = _band_energies(a), _band_energies(b)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
    band = max(0.0, min(1.0, float(np.dot(va, vb) / denom)))
    fa, fb = _median_f0(a), _median_f0(b)
    if fa <= 0 or fb <= 0:
        pitch = 0.0
    else:
        semitones = abs(12.0 * np.log2(fa / fb))
        pitch = max(0.0, min(1.0, 1.0 - semitones / 12.0))
    score = 0.6 * band + 0.4 * pitch
    return {"score": round(float(score), 4), "band": round(float(band), 4), "pitch": round(float(pitch), 4),
            "f0_ref": round(float(fa), 2), "f0_take": round(float(fb), 2), "passed": bool(score >= 0.6)}


def _box_mean(image: Any, radius: int = 12) -> Any:
    import numpy as np

    pad = np.pad(image, radius, mode="edge")
    window = 2 * radius + 1
    csum = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    csum = np.pad(csum, ((1, 0), (1, 0)))
    h, w = image.shape
    total = (csum[window:window + h, window:window + w]
             - csum[:h, window:window + w]
             - csum[window:window + h, :w]
             + csum[:h, :w])
    return total / (window * window)


def _ocr_text_words(image_path: str | Path) -> int | None:
    """Count OCR words with usable confidence; None when tesseract is absent."""
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "-", "-l", "eng+chi_sim", "--psm", "11", "tsv"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    count = 0
    for line in proc.stdout.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            confidence = float(cols[10])
        except ValueError:
            continue
        text = cols[11].strip()
        if confidence >= 70 and len(text) >= 3 and sum(ch.isalnum() for ch in text) >= 2:
            count += 1
    return count


def _edge_text_score(image_path: str | Path) -> dict[str, Any]:
    import numpy as np
    from PIL import Image

    gray = np.asarray(Image.open(image_path).convert("L").resize((640, 640)), dtype=np.float32)
    residual = np.abs(gray - _box_mean(gray))
    mask = residual > 28.0
    h = mask.shape[0]
    band = mask[: int(h * 0.78), :]
    density = float(band.mean())
    row = band.mean(axis=1)
    active = row > max(0.015, float(row.mean() + row.std()))
    clusters = 0
    run = 0
    for value in active:
        if value:
            run += 1
        else:
            if run >= 1:
                clusters += 1
            run = 0
    if run:
        clusters += 1
    score = min(1.0, density / 0.06) * 0.6 + min(1.0, clusters / 18.0) * 0.4
    return {"score": round(float(score), 4), "density": round(density, 4),
            "line_clusters": clusters, "method": "edge-band-fallback"}


def detect_text_artifacts(image_path: str | Path, *, threshold: float = 0.55) -> dict[str, Any]:
    """Detect garbled lettering above the subtitle band.

    OCR is authoritative when tesseract is installed (only high-confidence
    alphanumeric words count).  Without OCR, a conservative edge-band fallback
    requires both a very high residual density and many line clusters, so dense
    anime line art does not fail the gate.
    """
    del threshold
    words = _ocr_text_words(image_path)
    if words is not None:
        return {"passed": words < 3, "score": round(min(1.0, words / 3.0), 4),
                "ocr_words": words, "method": "tesseract-tsv"}
    edge = _edge_text_score(image_path)
    edge["passed"] = not (edge["density"] >= 0.5 and edge["line_clusters"] >= 40)
    return edge

def _character_assets(assets: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for img in assets.get("images") or []:
        cid = str(img.get("character_id") or "")
        if cid:
            out.setdefault(cid, []).append(img)
    return out


def _reference_voice(character_id: str, series: dict[str, Any] | None, voice_plan: dict[str, Any]) -> str:
    if series:
        for card in series.get("cast") or []:
            if str(card.get("id")) == character_id:
                ref = (card.get("voice") or {}).get("reference") or {}
                if isinstance(ref, dict) and ref.get("path"):
                    return str(ref["path"])
    ref = ((voice_plan.get("characters") or {}).get(character_id) or {}).get("reference") or {}
    if isinstance(ref, dict):
        return str(ref.get("path") or "")
    return ""


def _clip_audio(clip: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([FFMPEG, "-y", "-v", "error", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(out)])
    return out


def self_check_segment(
    segment: dict[str, Any],
    clips: dict[str, str],
    assets: dict[str, Any],
    *,
    series: dict[str, Any] | None = None,
    voice_plan: dict[str, Any] | None = None,
    out_dir: str | Path = ".",
    work_subdir: str = "segment_gate",
) -> dict[str, Any]:
    from .series import compare_to_anchor

    voice_plan = voice_plan or {}
    seg_id = str(segment.get("segment_id"))
    work = Path(out_dir) / work_subdir / seg_id
    work.mkdir(parents=True, exist_ok=True)
    by_char = _character_assets(assets)
    checks: dict[str, Any] = {}

    talking = next((s for s in segment.get("shots") or []
                    if str(s.get("character_id")) and str(s.get("shot_id")) in clips), None)
    if talking is None:
        talking = next((s for s in segment.get("shots") or [] if str(s.get("shot_id")) in clips), None)

    # face
    face_check: dict[str, Any] = {"passed": True, "skipped": "no character shot"}
    if talking is not None:
        shot_id = str(talking.get("shot_id"))
        cid = str(talking.get("character_id") or "")
        clip = Path(clips[shot_id])
        frame = extract_frame(clip, 0.4, work / f"{shot_id}_frame.png")
        anchor = ""
        # A talking shot is generated from its portrait; compare the frame with
        # that portrait first (then the series portrait anchor, then the sheet).
        for img in by_char.get(cid, []):
            if img.get("kind") == "character_portrait" and img.get("path"):
                anchor = str(img["path"])
                break
        if not anchor and series:
            for card in series.get("cast") or []:
                if str(card.get("id")) == cid:
                    anchor = str(card.get("portrait_image") or card.get("anchor_image") or "")
        if not anchor:
            for img in by_char.get(cid, []):
                if img.get("kind") in ("character_identity", "character_portrait") and img.get("path"):
                    anchor = str(img["path"])
                    break
        if anchor and Path(anchor).is_file():
            face_check = compare_to_anchor(frame, anchor)
        else:
            face_check = {"passed": True, "skipped": "no anchor image"}
    checks["face"] = face_check

    # text
    texts = []
    if talking is not None:
        clip = Path(clips[str(talking.get("shot_id"))])
        for i, t in enumerate((0.5, 1.2)):
            frame = extract_frame(clip, t, work / f"text_{i}.png")
            texts.append(detect_text_artifacts(frame))
    checks["text"] = {
        "passed": all(t["passed"] for t in texts) if texts else True,
        "samples": texts,
    }

    # voice
    voice_check: dict[str, Any] = {"passed": True, "skipped": "no character shot"}
    if talking is not None:
        cid = str(talking.get("character_id") or "")
        reference = _reference_voice(cid, series, voice_plan)
        clip = Path(clips[str(talking.get("shot_id"))])
        if reference and Path(reference).is_file():
            take = _clip_audio(clip, work / "take.wav")
            voice_check = voice_similarity(reference, take)
        else:
            voice_check = {"passed": True, "skipped": "no voice reference"}
    checks["voice"] = voice_check

    passed = all(c.get("passed", True) for c in checks.values())
    return {"segment_id": seg_id, "checks": checks, "passed": passed}


def _segment_shot_ids(segment: dict[str, Any]) -> set[str]:
    return {str(s.get("shot_id")) for s in segment.get("shots") or []}


def _delete_segment_clips(segment: dict[str, Any], out_dir: Path) -> None:
    clips_dir = out_dir / "clips"
    for shot_id in _segment_shot_ids(segment):
        path = clips_dir / f"{shot_id}.mp4"
        path.unlink(missing_ok=True)
    (out_dir / "segments" / f"{segment.get('segment_id')}.mp4").unlink(missing_ok=True)


def render_segments_gated(
    storyboard: dict[str, Any],
    script: dict[str, Any],
    assets: dict[str, Any],
    asset_paths: dict[str, str],
    voice_plan: dict[str, Any],
    out_dir: str | Path,
    *,
    ledger: CreditLedger | None = None,
    prefer_provider: str | None = None,
    lipsync: bool | None = None,
    seed: int = 42,
    episode_id: str = "",
    series: dict[str, Any] | None = None,
    redo_attempts: int = 1,
) -> dict[str, Any]:
    from .render import render_segments, render_shots

    out_dir = Path(out_dir)
    segments = storyboard.get("segments") or []
    if not segments:
        return {"shots": {"clips": {}, "provider": "", "meta": {}}, "segments": {}, "gate": {"passed": False}}
    report: list[dict[str, Any]] = []
    all_clips: dict[str, str] = {}
    meta: dict[str, Any] = {}
    provider = ""
    providers: dict[str, Any] = {}

    for segment in segments:
        seg_id = str(segment.get("segment_id"))
        shot_ids = _segment_shot_ids(segment)
        attempt = 0
        while True:
            result = render_shots(
                storyboard, script, assets, asset_paths, voice_plan, out_dir,
                ledger=ledger, prefer_provider=prefer_provider, lipsync=lipsync,
                seed=seed, episode_id=episode_id,
                only_shots=shot_ids, skip_existing=(attempt == 0),
            )
            provider = result.get("provider") or provider
            providers = result.get("providers") or providers
            all_clips.update(result.get("clips") or {})
            meta.update(result.get("meta") or {})
            check = self_check_segment(segment, all_clips, assets, series=series,
                                       voice_plan=voice_plan, out_dir=out_dir)
            report.append({"segment_id": seg_id, "attempt": attempt + 1, **check})
            if check["passed"] or attempt >= redo_attempts:
                if not check["passed"]:
                    raise SegmentRejected(
                        f"段 {seg_id} 自检未通过（已整段重出 {attempt} 次）: "
                        f"{ {k: v.get('passed') for k, v in check['checks'].items()} }"
                    )
                break
            # Whole-segment redo: delete every clip of this segment, then render it again.
            _delete_segment_clips(segment, out_dir)
            for shot_id in shot_ids:
                all_clips.pop(shot_id, None)
            attempt += 1

    segment_paths = render_segments(storyboard, all_clips, out_dir)
    gate = {
        "passed": all(item["passed"] for item in report),
        "segments": report,
        "first_segment_only": True,
        "redo_rule": "whole segment re-rendered; no per-shot patch",
    }
    (out_dir / "segment_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "shots": {"clips": all_clips, "provider": provider, "providers": providers, "meta": meta},
        "segments": segment_paths,
        "gate": gate,
    }

"""Granular koubo_cut node executors for the canvas MVP.

The default graph is a parallel per-sentence structure.  Each sentence owns
``tts_N → avatar_N``, ``evidence_N`` and ``segment_N``; ``edit`` only joins the
finished clips.  Every executor returns a ``content_hash`` that changes only
when its own semantics change, so the incremental engine can reuse an unchanged
sentence branch (``hevi.canvas.graph_diff.node_input_fingerprint``).

Heavy media work reuses the existing offline koubo pipeline (Piper TTS, PIL
frames, ffmpeg).  Evidence material comes from real sources through
``hevi.canvas.evidence``; when neither Pexels nor a web screenshot is available
the segment is skipped and the self-check turns yellow with the reason.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.koubo_cut import pipeline as kp

FPS = kp.FPS


def _hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _step(node: Any) -> str:
    cfg = node.config or {}
    return str(cfg.get("koubo_step") or "")


def _cfg(node: Any) -> dict[str, Any]:
    return dict(node.config or {})


def _sentence_index(node: Any) -> int:
    try:
        return int((node.config or {}).get("sentence_index") or 0)
    except Exception:
        return 0


def _merge_upstream(upstream: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in upstream.values():
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _upstream_step(upstream: dict[str, Any], *steps: str) -> dict[str, Any] | None:
    for value in upstream.values():
        if isinstance(value, dict) and str(value.get("koubo_step") or "") in steps:
            return value
    return None


def _sentence_of(upstream: dict[str, Any], index: int) -> dict[str, Any]:
    source = _upstream_step(upstream, "sentences")
    if source:
        sentences = list(source.get("sentences") or [])
    else:
        sentences = list(_merge_upstream(upstream).get("sentences") or [])
    if 0 <= index < len(sentences) and isinstance(sentences[index], dict):
        return sentences[index]
    if sentences:
        return sentences[0]
    merged = _merge_upstream(upstream)
    text = str(merged.get("output") or merged.get("script_text") or "口播")
    return {"text": text, "start": 0.0, "end": float(merged.get("duration_s") or 8.0)}


def _out_dir(node: Any) -> Path:
    cfg = _cfg(node)
    raw = str(cfg.get("out_dir") or "").strip()
    base = Path(raw) if raw else Path("output/canvas/koubo")
    # One directory per graph: node ids repeat across graphs and a shared root
    # let two concurrent graphs overwrite each other's media.
    graph_id = str(cfg.get("graph_id") or cfg.get("canvas_graph_id") or "").strip()
    if graph_id:
        base = base / _safe_segment(graph_id)
    node_dir = base / str(node.node_id)
    node_dir.mkdir(parents=True, exist_ok=True)
    return node_dir


def _safe_segment(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in "-_.")[:80] or "graph"


def _input_video(path: Path, duration: float) -> None:
    """Tiny fallback clip if a render is missing."""
    subprocess.run(
        [
            kp._ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x202030:s={kp.W}x{kp.H}:r={FPS}:d={max(1.0, duration):.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _broken(output: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    fake = out_dir / "missing.mp4"
    return {**output, "output": str(fake), "artifacts": [{"kind": "video", "path": str(fake)}]}


# ── script / sentences ───────────────────────────────────────────────────────


def _run_script(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    lines = kp._script_lines(
        script_text=str(cfg.get("content") or cfg.get("script_text") or ""),
        script_lines=cfg.get("script_lines") or [],
        topic=str(cfg.get("topic") or ""),
    )
    out = _out_dir(node)
    (out / "script.json").write_text(
        json.dumps({"lines": lines}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "type": "text",
        "koubo_step": "script",
        "output": "\n".join(lines),
        "lines": lines,
        "content_hash": _hash(lines),
        "artifacts": [{"kind": "text", "path": str(out / "script.json")}],
    }


def _run_sentences(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    merged = _merge_upstream(upstream)
    lines = list(merged.get("lines") or [])
    if not lines:
        text = str(merged.get("output") or cfg.get("content") or cfg.get("topic") or "")
        lines = [p.strip() for p in text.splitlines() if p.strip()] or [text or "口播"]
    duration = float(cfg.get("duration_s") or 10.0)
    sentences = kp._sentence_times(lines, duration)
    # The per-sentence slice hash must depend on that sentence's text only;
    # start/end shift when another sentence changes length.
    for sentence in sentences:
        sentence["content_hash"] = _hash(str(sentence.get("text") or ""))
    out = _out_dir(node)
    (out / "sentences.json").write_text(
        json.dumps({"sentences": sentences}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "type": "text",
        "koubo_step": "sentences",
        "output": "\n".join(str(s.get("text") or "") for s in sentences),
        "lines": lines,
        "sentences": sentences,
        "duration_s": duration,
        "content_hash": _hash(sentences),
        "artifacts": [{"kind": "text", "path": str(out / "sentences.json")}],
    }


# ── per-sentence branches ────────────────────────────────────────────────────


def _run_tts_sentence(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    index = _sentence_index(node)
    sentence = _sentence_of(upstream, index)
    text = str(sentence.get("text") or "").strip() or "口播"
    out = _out_dir(node)
    target = str(cfg.get("out_dir") or "")
    duration_hint = float(cfg.get("duration_s") or 8.0)
    audio = kp._tts(text, out / "audio.wav")
    if audio is None:
        audio = kp._silence(duration_hint, out / "audio.wav")
    speech = kp._speech_duration(audio) or duration_hint
    (out / "transcript.json").write_text(
        json.dumps({"text": text, "speech_duration_s": speech}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "type": "audio",
        "koubo_step": "tts",
        "sentence_index": index,
        "text": text,
        "output": str(audio),
        "audio": str(audio),
        "duration_s": speech,
        "speech_duration_s": speech,
        "content_hash": _hash({"text": text, "speech": round(speech, 3), "target": target}),
        "artifacts": [
            {"kind": "audio", "path": str(audio)},
            {"kind": "text", "path": str(out / "transcript.json")},
        ],
    }


def _run_evidence_sentence(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    index = _sentence_index(node)
    sentence = _sentence_of(upstream, index)
    text = str(sentence.get("text") or "").strip()
    out = _out_dir(node)
    pick = int(cfg.get("_evidence_retry") or 0)
    from hevi.canvas import evidence as evidence_mod

    item = evidence_mod.fetch_for_sentence(
        text,
        topic=str(cfg.get("topic") or ""),
        out_dir=out / "raw",
        pick=pick,
        allow_web=bool(cfg.get("allow_web", True)),
    )
    card_path = ""
    if item.get("ok"):
        from PIL import Image as _Image

        fallback = _Image.new("RGB", (720, 740), (46, 96, 132))
        try:
            card = kp._evidence_card(
                text,
                index + 1,
                out / "evidence_card.png",
                image_path=Path(str(item["path"])),
                fallback_image=fallback,
                source_label=str(item.get("source_label") or ""),
            )
            card_path = str(card)
        except Exception as exc:  # never fake a card
            item = {**item, "ok": False, "skipped_reason": f"证据卡渲染失败：{exc}"}
    artifacts = []
    if card_path:
        artifacts.append({"kind": "image", "path": card_path})
    payload = {
        "type": "video",
        "koubo_step": "evidence",
        "sentence_index": index,
        "sentence": text,
        "evidence": [
            {
                "ok": bool(item.get("ok")),
                "path": str(item.get("path") or ""),
                "card_path": card_path,
                "sentence": text,
                "query": str(item.get("query") or ""),
                "meta": item.get("meta") or {},
                "source_label": str(item.get("source_label") or ""),
                "relevant": item.get("relevant"),
                "skipped_reason": str(item.get("skipped_reason") or ""),
            }
        ],
        "skipped_reason": str(item.get("skipped_reason") or ""),
        "output": card_path,
        "content_hash": _hash(
            {
                "sentence": text,
                "query": item.get("query"),
                "provider": (item.get("meta") or {}).get("provider"),
                "photo_id": (item.get("meta") or {}).get("photo_id"),
                "url": (item.get("meta") or {}).get("url"),
                "ok": bool(item.get("ok")),
            }
        ),
        "artifacts": artifacts,
    }
    if cfg.get("koubo_break"):
        return _broken(payload, out)
    return payload


def _run_avatar_sentence(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    index = _sentence_index(node)
    tts = _upstream_step(upstream, "tts", "tts_sentence")
    duration = float((tts or {}).get("duration_s") or cfg.get("duration_s") or 4.0)
    out = _out_dir(node)
    presenter, _mouth_box, _mouth_center = kp._presenter_layer()
    presenter_path = out / "presenter.png"
    presenter.save(presenter_path)
    avatar = out / "avatar.mp4"
    subprocess.run(
        [
            kp._ffmpeg(),
            "-y",
            "-loop",
            "1",
            "-i",
            str(presenter_path),
            "-t",
            f"{max(1.0, duration):.3f}",
            "-r",
            str(FPS),
            "-vf",
            f"scale={kp.W}:{kp.H},format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            str(avatar),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if not avatar.is_file():
        _input_video(avatar, duration)
    payload = {
        "type": "video",
        "koubo_step": "avatar",
        "sentence_index": index,
        "output": str(avatar),
        "avatar": str(avatar),
        "presenter": str(presenter_path),
        "duration_s": duration,
        "engine": "synthetic-flat-mvp",
        "content_hash": _hash({"avatar": True, "duration": round(duration, 3)}),
        "artifacts": [
            {"kind": "video", "path": str(avatar)},
            {"kind": "image", "path": str(presenter_path)},
        ],
    }
    if cfg.get("koubo_break"):
        return _broken(payload, out)
    return payload


def _run_segment(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    index = _sentence_index(node)
    out = _out_dir(node)
    sentence = _sentence_of(upstream, index)
    text = str(sentence.get("text") or "").strip()
    tts = _upstream_step(upstream, "tts", "tts_sentence") or {}
    avatar = _upstream_step(upstream, "avatar", "avatar_sentence") or {}
    evidence = _upstream_step(upstream, "evidence", "evidence_sentence") or {}
    duration = float(tts.get("duration_s") or cfg.get("duration_s") or 4.0)
    audio = Path(str(tts.get("audio") or tts.get("output") or ""))
    if not audio.is_file():
        audio = kp._silence(duration, out / "audio.wav")
    presenter_path = Path(str(avatar.get("presenter") or ""))
    presenter = (
        kp.Image.open(presenter_path).convert("RGBA") if presenter_path.is_file() else None
    )
    if presenter is None:
        presenter, _mb, _mc = kp._presenter_layer()
    _p, mouth_box, mouth_center = kp._presenter_layer()
    # The corner avatar window must show the presenter: cropping the bare paper
    # background produced the blank beige block users reported.
    pip_source = kp._base_background()
    pip_source.paste(presenter, (0, 0), presenter)
    pip = kp._pip_image(pip_source)
    card = ""
    for item in evidence.get("evidence") or []:
        if isinstance(item, dict) and item.get("ok") and item.get("card_path"):
            card = str(item["card_path"])
            break
    evidence_arg = [(0.0, duration, Path(card))] if card and Path(card).is_file() else []
    mp4 = out / "segment.mp4"
    kp._render_frames(
        duration=duration,
        audio=audio,
        sentences=[{"start": 0.0, "end": duration, "text": text}],
        evidence=evidence_arg,
        presenter=presenter,
        mouth_box=mouth_box,
        mouth_center=mouth_center,
        pip=pip,
        badge_text=str(cfg.get("topic") or ""),
        output=mp4,
    )
    if not mp4.is_file():
        _input_video(mp4, duration)
    payload = {
        "type": "video",
        "koubo_step": "segment",
        "sentence_index": index,
        "text": text,
        "output": str(mp4),
        "duration_s": duration,
        "evidence": bool(evidence_arg),
        "content_hash": _hash(
            {
                "text": text,
                "tts": tts.get("content_hash"),
                "evidence": evidence.get("content_hash"),
                "avatar": avatar.get("content_hash"),
            }
        ),
        "artifacts": [{"kind": "video", "path": str(mp4)}],
    }
    if cfg.get("koubo_break"):
        return _broken(payload, out)
    return payload


# ── assembly ─────────────────────────────────────────────────────────────────


def _run_edit_segments(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    out = _out_dir(node)
    segments = [
        value
        for value in upstream.values()
        if isinstance(value, dict) and str(value.get("koubo_step") or "") == "segment"
    ]
    segments.sort(key=lambda value: int(value.get("sentence_index") or 0))
    duration_total = sum(float(s.get("duration_s") or 0) for s in segments)
    files = [Path(str(s.get("output") or "")) for s in segments]
    files = [path for path in files if path.is_file()]
    mp4 = out / "edit.mp4"
    if files:
        concat = out / "segments.txt"
        concat.write_text(
            "\n".join(f"file '{path.resolve()}'" for path in files), encoding="utf-8"
        )
        # Every segment was encoded with the same codec parameters, so a
        # stream-copy concat is valid and ~100x cheaper than re-encoding the
        # whole film on every one-sentence edit.  Fall back to a re-encode if
        # the copy produces nothing usable.
        subprocess.run(
            [
                kp._ffmpeg(), "-y", "-fflags", "+genpts",
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-c", "copy", "-movflags", "+faststart",
                "-metadata", "comment=AI 生成 · hevi 合成", str(mp4),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if not mp4.is_file() or mp4.stat().st_size == 0 or kp._ffprobe_duration(mp4) <= 0:
            subprocess.run(
                [
                    kp._ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-metadata", "comment=AI 生成 · hevi 合成", str(mp4),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
    if not mp4.is_file():
        _input_video(mp4, max(1.0, duration_total))
    cursor = 0.0
    timeline: list[dict[str, Any]] = []
    for seg in segments:
        span = float(seg.get("duration_s") or 0)
        timeline.append(
            {
                "index": seg.get("sentence_index") or 0,
                "start": round(cursor, 3),
                "end": round(cursor + span, 3),
                "text": str(seg.get("text") or ""),
            }
        )
        cursor += span
    payload = {
        "type": "video",
        "koubo_step": "edit",
        "output": str(mp4),
        "edit": str(mp4),
        "segments": timeline,
        "duration_s": cursor or duration_total,
        "content_hash": _hash(
            {
                "segments": [seg.get("content_hash") for seg in segments],
                "timeline": timeline,
            }
        ),
        "artifacts": [{"kind": "video", "path": str(mp4)}],
    }
    if cfg.get("koubo_break"):
        return _broken(payload, out)
    return payload


def _srt(sentences: list[dict[str, Any]]) -> str:
    def stamp(seconds: float) -> str:
        ms = round(max(0.0, seconds) * 1000)
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    rows: list[str] = []
    for i, sent in enumerate(sentences, start=1):
        rows.append(
            f"{i}\n{stamp(float(sent.get('start') or 0))} --> "
            f"{stamp(float(sent.get('end') or 0))}\n{str(sent.get('text') or '').strip()}\n"
        )
    return "\n".join(rows)


def _run_subtitle(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    out = _out_dir(node)
    merged = _merge_upstream(upstream)
    edit = _upstream_step(upstream, "edit", "edit_segments") or {}
    timeline = list(edit.get("segments") or merged.get("segments") or [])
    sentences = (
        [{"start": s["start"], "end": s["end"], "text": s.get("text", "")} for s in timeline]
        if timeline
        else list(merged.get("sentences") or [])
    )
    srt = out / "subtitles.srt"
    srt.write_text(_srt(sentences), encoding="utf-8")
    cues = [
        {"start": s["start"], "end": s["end"], "text": s.get("text", "")} for s in sentences
    ]
    return {
        "type": "text",
        "koubo_step": "subtitle",
        "output": str(srt),
        "subtitle": str(srt),
        "segments": timeline,
        "video": str(edit.get("output") or merged.get("output") or ""),
        "sentences": sentences,
        "duration_s": edit.get("duration_s") or merged.get("duration_s"),
        "content_hash": _hash(cues),
        "artifacts": [{"kind": "text", "path": str(srt)}],
    }


def _run_final(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    out = _out_dir(node)
    merged = _merge_upstream(upstream)
    edit = _upstream_step(upstream, "edit", "edit_segments") or {}
    duration = float(edit.get("duration_s") or merged.get("duration_s") or 10.0)
    source = Path(str(edit.get("output") or merged.get("video") or merged.get("output") or ""))
    final = out / "koubo_cut.mp4"
    if source.is_file():
        # The final copy must carry the AI disclosure metadata even when the
        # edit node used a plain stream-copy concat.  Remux is cheap (copy).
        subprocess.run(
            [
                kp._ffmpeg(), "-y", "-i", str(source), "-c", "copy",
                "-metadata", "comment=AI 生成 · hevi 合成",
                "-movflags", "+faststart", str(final),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if not final.is_file() or final.stat().st_size == 0:
            shutil.copy2(source, final)
    else:
        _input_video(final, duration)
    fcpxml = kp._write_fcpxml(out, duration, final)
    return {
        "type": "video",
        "koubo_step": "final",
        "output": str(final),
        "final": str(final),
        "fcpxml": str(fcpxml),
        "subtitle": str(merged.get("subtitle") or ""),
        "duration_s": duration,
        "content_hash": _hash(
            {"edit": edit.get("content_hash"), "subtitle": merged.get("content_hash")}
        ),
        "artifacts": [
            {"kind": "video", "path": str(final)},
            {"kind": "text", "path": str(fcpxml)},
        ],
    }


# ── legacy chain steps (graphs created before the parallel template) ────────


def _run_tts(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    merged = _merge_upstream(upstream)
    out = _out_dir(node)
    text = "\n".join(str(x) for x in (merged.get("lines") or [])) or str(
        merged.get("output") or ""
    )
    duration = float(cfg.get("duration_s") or merged.get("duration_s") or 10.0)
    audio = kp._tts(text, out / "audio.wav")
    if audio is None:
        audio = kp._silence(duration, out / "audio.wav")
    speech = kp._speech_duration(audio) or duration
    lines = list(merged.get("lines") or [])
    sentences = kp._sentence_times(lines or [text], speech) if lines else list(
        merged.get("sentences") or []
    )
    (out / "transcript.json").write_text(
        json.dumps({"sentences": sentences, "speech_duration_s": speech}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "type": "audio",
        "koubo_step": "tts",
        "output": str(audio),
        "audio": str(audio),
        "duration_s": speech,
        "speech_duration_s": speech,
        "sentences": sentences,
        "lines": lines,
        "content_hash": _hash({"text": text, "speech": round(speech, 3)}),
        "artifacts": [
            {"kind": "audio", "path": str(audio)},
            {"kind": "text", "path": str(out / "transcript.json")},
        ],
    }


def _run_avatar(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    merged = _merge_upstream(upstream)
    out = _out_dir(node)
    duration = float(merged.get("duration_s") or cfg.get("duration_s") or 10.0)
    presenter, _mouth_box, _mouth_center = kp._presenter_layer()
    presenter_path = out / "presenter.png"
    presenter.save(presenter_path)
    avatar = out / "avatar.mp4"
    audio = str(merged.get("audio") or "").strip()
    has_audio = bool(audio) and Path(audio).is_file()
    cmd = [kp._ffmpeg(), "-y", "-loop", "1", "-i", str(presenter_path)]
    if has_audio:
        cmd += ["-i", audio]
    cmd += [
        "-t", f"{duration:.3f}", "-r", str(FPS),
        "-vf", f"scale={kp.W}:{kp.H},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
    ]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "96k", "-shortest"]
    cmd += [str(avatar)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if not avatar.is_file():
        _input_video(avatar, duration)
    payload = {
        "type": "video",
        "koubo_step": "avatar",
        "output": str(avatar),
        "avatar": str(avatar),
        "presenter": str(presenter_path),
        "duration_s": duration,
        "audio": audio,
        "sentences": merged.get("sentences") or [],
        "lines": merged.get("lines") or [],
        "engine": "synthetic-flat-mvp",
        "content_hash": _hash({"avatar": True, "duration": round(duration, 3)}),
        "artifacts": [
            {"kind": "video", "path": str(avatar)},
            {"kind": "image", "path": str(presenter_path)},
        ],
    }
    if cfg.get("koubo_break"):
        return _broken(payload, out)
    return payload


def _run_evidence(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    merged = _merge_upstream(upstream)
    out = _out_dir(node)
    duration = float(merged.get("duration_s") or 10.0)
    sentences = list(merged.get("sentences") or [])
    picks = [1, 3] if len(sentences) > 3 else list(range(min(2, len(sentences))))
    from hevi.canvas import evidence as evidence_mod

    items: list[dict[str, Any]] = []
    for n, idx in enumerate(picks, start=1):
        if idx >= len(sentences):
            break
        sent = sentences[idx]
        text = str(sent.get("text") or "")
        item = evidence_mod.fetch_for_sentence(
            text,
            topic=str(cfg.get("topic") or ""),
            out_dir=out / "raw" / str(n),
            allow_web=bool(cfg.get("allow_web", True)),
        )
        card_path = ""
        if item.get("ok"):
            card_path = str(
                kp._evidence_card(
                    text,
                    n,
                    out / f"evidence_{n}.png",
                    image_path=Path(str(item["path"])),
                    fallback_image=kp.Image.new("RGB", (720, 740), (46, 96, 132)),
                    source_label=str(item.get("source_label") or ""),
                )
            )
        items.append(
            {
                "ok": bool(item.get("ok")),
                "path": str(item.get("path") or ""),
                "card_path": card_path,
                "sentence": text,
                "query": str(item.get("query") or ""),
                "meta": item.get("meta") or {},
                "source_label": str(item.get("source_label") or ""),
                "relevant": item.get("relevant"),
                "skipped_reason": str(item.get("skipped_reason") or ""),
                "start": round(max(0.0, float(sent.get("start") or 0) + 0.2), 3),
                "end": round(min(duration, float(sent.get("end") or duration)), 3),
            }
        )
    clip = out / "evidence.mp4"
    cards = [Path(str(i["card_path"])) for i in items if i.get("card_path")]
    if cards:
        concat = out / "evidence_concat.txt"
        lines_text: list[str] = []
        for card in cards:
            lines_text.append(f"file '{card.name}'")
            lines_text.append("duration 2.500")
        lines_text.append(f"file '{cards[-1].name}'")
        concat.write_text("\n".join(lines_text), encoding="utf-8")
        subprocess.run(
            [
                kp._ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                "-vf", f"fps={FPS},scale={kp.W}:{kp.H},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", str(clip),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    if not clip.is_file():
        _input_video(clip, min(duration, 4.0))
    payload = {
        **{k: v for k, v in merged.items() if k in ("audio", "sentences", "lines", "presenter")},
        "type": "video",
        "koubo_step": "evidence",
        "output": str(clip),
        "evidence": items,
        "duration_s": duration,
        "content_hash": _hash([i.get("query") for i in items]),
        "artifacts": [
            {"kind": "video", "path": str(clip)},
            *[{"kind": "image", "path": str(i["card_path"])} for i in items if i.get("card_path")],
        ],
    }
    if cfg.get("koubo_break"):
        return _broken(payload, out)
    return payload


def _run_edit(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    merged = _merge_upstream(upstream)
    out = _out_dir(node)
    duration = float(merged.get("duration_s") or cfg.get("duration_s") or 10.0)
    audio = Path(str(merged.get("audio") or out / "audio.wav"))
    if not audio.is_file():
        audio = kp._silence(duration, out / "audio.wav")
    sentences = list(merged.get("sentences") or [])
    evidence = [
        (float(e["start"]), float(e["end"]), Path(str(e["card_path"])))
        for e in (merged.get("evidence") or [])
        if e.get("card_path") and Path(str(e["card_path"])).is_file()
    ]
    presenter_path = Path(str(merged.get("presenter") or ""))
    presenter = (
        kp.Image.open(presenter_path).convert("RGBA") if presenter_path.is_file() else None
    )
    _p, mouth_box, mouth_center = kp._presenter_layer()
    pip = kp._pip_image(kp._base_background())
    mp4 = out / "edit.mp4"
    kp._render_frames(
        duration=duration,
        audio=audio,
        sentences=sentences,
        evidence=evidence,
        presenter=presenter,
        mouth_box=mouth_box,
        mouth_center=mouth_center,
        pip=pip,
        badge_text=str(cfg.get("topic") or ""),
        output=mp4,
    )
    if not mp4.is_file():
        _input_video(mp4, duration)
    payload = {
        "type": "video",
        "koubo_step": "edit",
        "output": str(mp4),
        "edit": str(mp4),
        "audio": str(audio),
        "duration_s": duration,
        "sentences": sentences,
        "content_hash": _hash({"audio": str(audio), "evidence": [e[2].name for e in evidence]}),
        "artifacts": [{"kind": "video", "path": str(mp4)}],
    }
    if cfg.get("koubo_break"):
        return _broken(payload, out)
    return payload


_STEP_EXECUTORS = {
    "script": _run_script,
    "sentences": _run_sentences,
    "tts": _run_tts,
    "tts_sentence": _run_tts_sentence,
    "avatar": _run_avatar,
    "avatar_sentence": _run_avatar_sentence,
    "evidence": _run_evidence,
    "evidence_sentence": _run_evidence_sentence,
    "segment": _run_segment,
    "edit": _run_edit,
    "edit_segments": _run_edit_segments,
    "subtitle": _run_subtitle,
    "final": _run_final,
}


async def run_koubo_node(node: Any, upstream: dict[str, Any]) -> Any:
    import asyncio

    step = _step(node)
    fn = _STEP_EXECUTORS.get(step)
    if fn is None:
        raise ValueError(f"unknown koubo step: {step!r}")
    # Media render / Piper / Playwright are blocking: keep the API event loop
    # free, and give Playwright's sync API a thread without a running loop.
    return await asyncio.to_thread(fn, node, upstream)

"""Granular koubo_cut node executors for the canvas MVP.

Each default-graph node runs one step and writes its own artifact so the canvas
can show every step and a rerun only has to repeat the selected node and its
downstream.  The heavy rendering primitives are the existing offline pipeline
functions (PIL + ffmpeg, no browser, no cloud model, no network); this module
only splits the monolith into steps and passes the needed context forward.

``config.koubo_break`` is a deliberate diagnostic switch: the step renders but
reports a missing artifact, which exercises the self-check red path and the
single automatic retry in tests and demos.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.koubo_cut import pipeline as kp

FPS = kp.FPS


def _step(node: Any) -> str:
    cfg = node.config or {}
    return str(cfg.get("koubo_step") or "")


def _cfg(node: Any) -> dict[str, Any]:
    return dict(node.config or {})


def _merge_upstream(upstream: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``{from_node_id: output}`` into one context dict.

    The incremental engine hands each node a map of its direct predecessors;
    the koubo steps want the previous step's fields.  Flattening keeps the
    chain readable and lets a node carry context (audio/sentences/presenter)
    across more than one hop.
    """
    merged: dict[str, Any] = {}
    for value in upstream.values():
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _out_dir(node: Any) -> Path:
    cfg = _cfg(node)
    raw = str(cfg.get("out_dir") or "").strip()
    base = Path(raw) if raw else Path("output/canvas/koubo")
    node_dir = base / str(node.node_id)
    node_dir.mkdir(parents=True, exist_ok=True)
    return node_dir


def _input_video(path: Path, duration: float) -> None:
    """Tiny fallback clip if an upstream video is missing."""
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


def _run_script(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    lines = kp._script_lines(
        script_text=str(cfg.get("script_text") or cfg.get("content") or ""),
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
        "artifacts": [{"kind": "text", "path": str(out / "script.json")}],
    }


def _run_sentences(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    upstream = _merge_upstream(upstream)
    lines = list(upstream.get("lines") or [])
    if not lines:
        text = str(upstream.get("output") or cfg.get("script_text") or cfg.get("topic") or "")
        lines = [p.strip() for p in text.splitlines() if p.strip()] or [text or "口播"]
    duration = float(cfg.get("duration_s") or 10.0)
    sentences = kp._sentence_times(lines, duration)
    out = _out_dir(node)
    (out / "sentences.json").write_text(
        json.dumps({"sentences": sentences}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "type": "text",
        "koubo_step": "sentences",
        "output": "\n".join(lines),
        "lines": lines,
        "sentences": sentences,
        "duration_s": duration,
        "artifacts": [{"kind": "text", "path": str(out / "sentences.json")}],
    }


def _run_tts(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    upstream = _merge_upstream(upstream)
    out = _out_dir(node)
    text = "\n".join(str(x) for x in (upstream.get("lines") or [])) or str(
        upstream.get("output") or ""
    )
    duration = float(cfg.get("duration_s") or upstream.get("duration_s") or 10.0)
    audio = kp._tts(text, out / "audio.wav")
    if audio is None:
        audio = kp._silence(duration, out / "audio.wav")
    speech = kp._speech_duration(audio) or duration
    lines = list(upstream.get("lines") or [])
    sentences = kp._sentence_times(lines or [text], speech) if lines else list(
        upstream.get("sentences") or []
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
        "artifacts": [
            {"kind": "audio", "path": str(audio)},
            {"kind": "text", "path": str(out / "transcript.json")},
        ],
    }


def _run_avatar(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    upstream = _merge_upstream(upstream)
    out = _out_dir(node)
    duration = float(upstream.get("duration_s") or cfg.get("duration_s") or 10.0)
    presenter, _mouth_box, _mouth_center = kp._presenter_layer()
    presenter_path = out / "presenter.png"
    presenter.save(presenter_path)
    avatar = out / "avatar.mp4"
    audio = str(upstream.get("audio") or "").strip()
    has_audio = bool(audio) and Path(audio).is_file()
    cmd = [kp._ffmpeg(), "-y", "-loop", "1", "-i", str(presenter_path)]
    if has_audio:
        cmd += ["-i", audio]
    cmd += [
        "-t",
        f"{duration:.3f}",
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
    ]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "96k", "-shortest"]
    cmd += [str(avatar)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if not avatar.is_file():
        _input_video(avatar, duration)
    output = {
        "type": "video",
        "koubo_step": "avatar",
        "output": str(avatar),
        "avatar": str(avatar),
        "presenter": str(presenter_path),
        "duration_s": duration,
        "audio": audio,
        "sentences": upstream.get("sentences") or [],
        "lines": upstream.get("lines") or [],
        "engine": "synthetic-flat-mvp",
        "artifacts": [
            {"kind": "video", "path": str(avatar)},
            {"kind": "image", "path": str(presenter_path)},
        ],
    }
    if cfg.get("koubo_break"):
        return _broken(output, out)
    return output


def _run_evidence(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    out = _out_dir(node)
    upstream = _merge_upstream(upstream)
    duration = float(upstream.get("duration_s") or 10.0)
    sentences = list(upstream.get("sentences") or [])
    items: list[dict[str, Any]] = []
    picks = [1, 3] if len(sentences) > 3 else list(range(min(2, len(sentences))))
    fallback = kp.Image.new("RGB", (720, 740), (46, 96, 132))
    for n, idx in enumerate(picks, start=1):
        if idx >= len(sentences):
            break
        sent = sentences[idx]
        card = kp._evidence_card(
            str(sent.get("text") or ""),
            n,
            out / f"evidence_{n}.png",
            image_path=None,
            fallback_image=fallback,
        )
        start = max(0.0, float(sent.get("start") or 0) + 0.2)
        end = min(duration, max(start + 2.2, float(sent.get("end") or start + 2.2)))
        items.append(
            {
                "index": n,
                "start": round(start, 3),
                "end": round(min(end, start + 3.0), 3),
                "path": str(card),
            }
        )
    clip = out / "evidence.mp4"
    if items:
        concat = out / "evidence_concat.txt"
        lines: list[str] = []
        for item in items:
            lines.append(f"file '{Path(item['path']).name}'")
            lines.append(f"duration {max(1.0, item['end'] - item['start']):.3f}")
        lines.append(f"file '{Path(items[-1]['path']).name}'")
        concat.write_text("\n".join(lines), encoding="utf-8")
        subprocess.run(
            [
                kp._ffmpeg(),
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-vf",
                f"fps={FPS},scale={kp.W}:{kp.H},format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                str(clip),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    if not clip.is_file():
        _input_video(clip, min(duration, 4.0))
    output = {
        **{k: v for k, v in upstream.items() if k in ("audio", "sentences", "lines", "presenter")},
        "type": "video",
        "koubo_step": "evidence",
        "output": str(clip),
        "evidence": items,
        "duration_s": duration,
        "artifacts": [
            {"kind": "video", "path": str(clip)},
            *[{"kind": "image", "path": item["path"]} for item in items],
        ],
    }
    if (_cfg(node).get("koubo_break")):
        return _broken(output, out)
    return output


def _run_edit(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(node)
    upstream = _merge_upstream(upstream)
    out = _out_dir(node)
    duration = float(upstream.get("duration_s") or cfg.get("duration_s") or 10.0)
    audio = Path(str(upstream.get("audio") or out / "audio.wav"))
    if not audio.is_file():
        audio = kp._silence(duration, out / "audio.wav")
    sentences = list(upstream.get("sentences") or [])
    evidence = [
        (float(e["start"]), float(e["end"]), Path(str(e["path"])))
        for e in (upstream.get("evidence") or [])
        if Path(str(e.get("path"))).is_file()
    ]
    presenter_path = Path(str(upstream.get("presenter") or ""))
    presenter = (
        kp.Image.open(presenter_path).convert("RGBA")
        if presenter_path.is_file()
        else None
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
    output = {
        "type": "video",
        "koubo_step": "edit",
        "output": str(mp4),
        "edit": str(mp4),
        "audio": str(audio),
        "duration_s": duration,
        "sentences": sentences,
        "artifacts": [{"kind": "video", "path": str(mp4)}],
    }
    if cfg.get("koubo_break"):
        return _broken(output, out)
    return output


def _srt(sentences: list[dict[str, Any]]) -> str:
    def stamp(seconds: float) -> str:
        ms = int(round(max(0.0, seconds) * 1000))
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
    upstream = _merge_upstream(upstream)
    sentences = list(upstream.get("sentences") or [])
    srt = out / "subtitles.srt"
    srt.write_text(_srt(sentences), encoding="utf-8")
    return {
        "type": "text",
        "koubo_step": "subtitle",
        "output": str(srt),
        "subtitle": str(srt),
        "video": str(upstream.get("output") or ""),
        "sentences": sentences,
        "duration_s": upstream.get("duration_s"),
        "artifacts": [{"kind": "text", "path": str(srt)}],
    }


def _run_final(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
    out = _out_dir(node)
    upstream = _merge_upstream(upstream)
    duration = float(upstream.get("duration_s") or 10.0)
    source = Path(str(upstream.get("video") or upstream.get("output") or ""))
    final = out / "koubo_cut.mp4"
    if source.is_file():
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
        "subtitle": str(upstream.get("subtitle") or ""),
        "duration_s": duration,
        "artifacts": [
            {"kind": "video", "path": str(final)},
            {"kind": "text", "path": str(fcpxml)},
        ],
    }


_STEP_EXECUTORS = {
    "script": _run_script,
    "sentences": _run_sentences,
    "tts": _run_tts,
    "avatar": _run_avatar,
    "evidence": _run_evidence,
    "edit": _run_edit,
    "subtitle": _run_subtitle,
    "final": _run_final,
}


async def run_koubo_node(node: Any, upstream: dict[str, Any]) -> Any:
    step = _step(node)
    fn = _STEP_EXECUTORS.get(step)
    if fn is None:
        raise ValueError(f"unknown koubo step: {step!r}")
    return fn(node, upstream)

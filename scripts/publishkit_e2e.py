"""Publishkit E2E：对真实成片出完整 publish_bundle。

用法::

    export PATH=$HOME/.local/bin:$PATH
    .venv/bin/python scripts/publishkit_e2e.py

覆盖三条真实产线，每条一个独立 bundle 目录：

* ``talkcraft_explainer`` — ``output/talkcraft_e2e/explainer/explainer_landscape.mp4``
  + ``work/timestamps.json``（逐句旁白 + 成片真实时间戳）
* ``whiteboard_topic_a`` / ``whiteboard_topic_b`` —
  ``output/whiteboard_e2e/topic_{a,b}/whiteboard_landscape.mp4``
  + ``landscape/scenes/script.json``（beat 旁白）

文稿必须是真实文本文件；媒体文件会被 :class:`ScriptError` 拒绝。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hevi.publishkit.adapter import generate_publish_bundle  # noqa: E402

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"
OUT_DIR = ROOT / "output/publishkit_e2e"
COVER_RATIOS = ("3x4", "4x3", "16x9")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _ffprobe(path: Path) -> dict:
    raw = subprocess.check_output([
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    data = json.loads(raw)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    return {
        "width": v.get("width"), "height": v.get("height"),
        "video_codec": v.get("codec_name"), "fps": v.get("r_frame_rate"),
        "audio_codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"),
        "duration_s": round(float(data["format"].get("duration", 0.0)), 3),
        "size_bytes": int(data["format"].get("size", 0)),
    }


def _image_size(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as im:
        return f"{im.size[0]}x{im.size[1]}"


def _grab(video: Path, dest: Path, at_s: float) -> str:
    subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{at_s:.2f}", "-i", str(video),
                    "-frames:v", "1", "-q:v", "2", str(dest)], check=True)
    return str(dest)


def _whiteboard_render_config(project_dir: Path) -> dict:
    """白板成片的字幕安全区 + 片尾卡时长（决定口播结束点之后允许多长尾静默）。"""

    cfg_path = project_dir / "config.json"
    if not cfg_path.is_file():
        return {}
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _caption_box(cfg: dict) -> dict | None:
    caps = cfg.get("captions", {})
    if not caps.get("enabled"):
        return None
    return {
        "frame_width": 1920,
        "frame_height": 1080,
        "baselineY": caps.get("baselineY"),
        "fontSize": caps.get("fontSize"),
    }


def _silent_tail(cfg: dict) -> float:
    end_card = (cfg.get("brand") or {}).get("endCard") or {}
    if not end_card.get("enabled"):
        return 0.0
    return float(end_card.get("seconds", 0.0)) + float(end_card.get("holdSeconds", 0.0))


def _narration_end_from_srt(srt_path: Path) -> float | None:
    """口播结束点 = 字幕文件最后一条 cue 的结束时间（whisper 逐词时间戳产物）。"""

    from hevi.layer4_legacy.publishkit.omodul_impl.qa import parse_srt

    if not srt_path.is_file():
        return None
    cues = parse_srt(srt_path)
    return max((c["end_s"] for c in cues), default=None)


def _run_one(name: str, video: Path, script: Path, *, caption_box: dict | None,
             caption_cues: list[dict] | None, caption_source: str,
             cover_subtitle: str, topic: str = "", brand: str = "",
             narration_end_s: float | None = None, silent_tail_s: float = 0.0) -> dict:
    print(f"\n--- {name} ---")
    print(f"  video : {video.relative_to(ROOT)}")
    print(f"  script: {script.relative_to(ROOT)}")
    out_dir = OUT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)

    res = generate_publish_bundle(
        video_path=video, script_path=script, output_dir=out_dir,
        config={"caption_box": caption_box, "caption_cues": caption_cues,
                "caption_source": caption_source,
                "cover_subtitle": cover_subtitle,
                "topic": topic, "brand": brand,
                "narration_end_s": narration_end_s, "silent_tail_s": silent_tail_s},
    )

    payload = res.as_dict()
    payload["name"] = name
    payload["input_video"] = {
        "path": str(video.relative_to(ROOT)), "sha256": _sha(video), "ffprobe": _ffprobe(video),
    }
    payload["input_script"] = {"path": str(script.relative_to(ROOT))}
    payload["covers"] = {
        ratio: {
            "path": str(Path(res.cover_paths[ratio]).relative_to(ROOT)),
            "sha256": _sha(Path(res.cover_paths[ratio])),
            "measured_size": _image_size(Path(res.cover_paths[ratio])),
        }
        for ratio in COVER_RATIOS
    }

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    duration = payload["input_video"]["ffprobe"]["duration_s"]
    payload["frames"] = [
        _grab(video, frames_dir / f"{name}_frame_mid.jpg", max(duration * 0.5, 0.5)),
        _grab(video, frames_dir / f"{name}_frame_late.jpg", max(duration * 0.8, 0.5)),
    ]
    return payload


def run_e2e() -> dict:
    print("=" * 64)
    print("PUBLISHKIT E2E — real bundles from real final cuts")
    print("=" * 64)

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases: list[dict] = []
    skipped: list[str] = []

    explainer = ROOT / "output/talkcraft_e2e/explainer/explainer_landscape.mp4"
    timings = ROOT / "output/talkcraft_e2e/explainer/work/timestamps.json"
    if explainer.is_file() and timings.is_file():
        talk_timings = json.loads(timings.read_text(encoding="utf-8")).get("timings", [])
        talk_cues = [
            {"index": i + 1, "start_s": float(t["start_s"]), "end_s": float(t["end_s"]),
             "text": str(t.get("text") or "")}
            for i, t in enumerate(talk_timings)
            if t.get("start_s") is not None and t.get("end_s") is not None
        ]
        cases.append(_run_one(
            "talkcraft_explainer", explainer, timings,
            caption_box=None, caption_cues=talk_cues,
            caption_source="talkcraft work/timestamps.json（渲染端同一份 VO 时间戳）",
            cover_subtitle="公开资料整理", topic="复利为什么被称为世界第八大奇迹",
            narration_end_s=max((c["end_s"] for c in talk_cues), default=None),
        ))
    else:
        skipped.append("talkcraft_explainer (缺成片或 timestamps.json)")

    whiteboard_topics = {
        "topic_a": ("白板讲解视频核心优势", ""),
        "topic_b": ("大语言模型如何思考", "极客视界"),
    }
    for topic_key, (title, brand) in whiteboard_topics.items():
        project = ROOT / f"output/whiteboard_e2e/{topic_key}/landscape"
        video = ROOT / f"output/whiteboard_e2e/{topic_key}/whiteboard_landscape.mp4"
        script = project / "scenes/script.json"
        srt = project / "字幕.srt"
        if video.is_file() and script.is_file():
            cfg = _whiteboard_render_config(project)
            from hevi.layer4_legacy.publishkit.omodul_impl.qa import parse_srt

            cues = parse_srt(srt) if srt.is_file() else []
            cases.append(_run_one(
                f"whiteboard_{topic_key}", video, script,
                caption_box=_caption_box(cfg), caption_cues=cues,
                caption_source=f"白板渲染产物 {srt.name}" if cues else "none",
                cover_subtitle="手绘白板讲解", topic=title, brand=brand,
                narration_end_s=_narration_end_from_srt(srt),
                silent_tail_s=_silent_tail(cfg),
            ))
        else:
            skipped.append(f"whiteboard_{topic_key} (缺成片或 script.json)")

    if not cases:
        raise SystemExit(
            "no input videos found — 先跑 scripts/whiteboard_e2e.py 与 talkcraft E2E 生成真实成片"
        )

    summary = {
        "status": "succeeded" if all(c["passed"] for c in cases) else "failed",
        "case_count": len(cases),
        "skipped": skipped,
        "cases": cases,
    }
    (OUT_DIR / "e2e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 64)
    for case in cases:
        print(f"{case['name']}: passed={case['passed']} llm_degraded={case['llm_degraded']}")
        for gate in case["gates"]:
            mark = "PASS" if gate["passed"] else "FAIL"
            print(f"   [{mark}] {gate['name']}: {gate['value']} (need {gate['threshold']})")
    for note in skipped:
        print(f"skipped: {note}")
    print(f"summary -> {OUT_DIR / 'e2e_summary.json'}")
    print("=" * 64)
    return summary


if __name__ == "__main__":
    run_e2e()
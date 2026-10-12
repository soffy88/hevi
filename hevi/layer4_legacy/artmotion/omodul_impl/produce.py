import json
import hashlib
import time
import shutil
import subprocess
import os
import sys
from pathlib import Path
from typing import Any
from dataclasses import asdict

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import NarrationSegment
from hevi.layer4_legacy.talkcraft.omodul_impl.produce import GAP_S, LEAD_S, _load_cached_timings
from hevi.layer4_legacy.talkcraft.omodul_impl._media import piper_tts, concat_with_gaps, duration
from hevi.layer4_legacy.talkcraft.omodul_impl._whisper import WhisperAligner

STYLE_REGISTRY: dict[str, str] = {
    "01_cave": "01_cave",
    "02_egypt": "02_egypt",
    "03_greek": "03_greek",
    "04_roman": "04_roman",
    "05_gothic": "05_gothic",
    "06_renaissance": "06_renaissance",
    "08_impressionism": "08_impressionism",
    "09_postimp": "09_postimp",
    "10_nouveau": "10_nouveau",
    "11_cubism": "11_cubism",
    "12_bauhaus": "12_bauhaus",
    "13_pop": "13_pop",
    "14_8bit": "14_8bit",
    "15_raytrace": "15_raytrace",
    "16_2026": "16_2026",
    "17_ink": "17_ink",
    "18_klimt": "18_klimt",
    "19_munch": "19_munch",
    "20_dunhuang": "20_dunhuang",
    "21_kusama": "21_kusama",
    "22_constructivism": "22_constructivism",
    "23_dali": "23_dali",
    "24_hopper": "24_hopper",
    "25_ghibli": "25_ghibli",
    "26_vaporwave": "26_vaporwave",
    "27_kirby": "27_kirby",
    "28_monet": "28_monet",
    "29_seurat": "29_seurat",
    "30_matisse": "30_matisse",
    "31_haring": "31_haring",
    "32_rembrandt": "32_rembrandt",
    "33_rubberhose": "33_rubberhose",
    "34_shadowpuppet": "34_shadowpuppet",
    "35_shinkai": "35_shinkai",
    "36_picasso_blue": "36_picasso_blue",
}

STYLE_ALIASES: dict[str, str] = {
    "cave": "01_cave",
    "egypt": "02_egypt",
    "greek": "03_greek",
    "roman": "04_roman",
    "gothic": "05_gothic",
    "renaissance": "06_renaissance",
    "impressionism": "08_impressionism",
    "postimp": "09_postimp",
    "nouveau": "10_nouveau",
    "cubism": "11_cubism",
    "bauhaus": "12_bauhaus",
    "pop": "13_pop",
    "8bit": "14_8bit",
    "14": "14_8bit",
    "pixel": "14_8bit",
    "raytrace": "15_raytrace",
    "ink": "17_ink",
    "17": "17_ink",
    "water_ink": "17_ink",
    "klimt": "18_klimt",
    "munch": "19_munch",
    "dunhuang": "20_dunhuang",
    "kusama": "21_kusama",
    "constructivism": "22_constructivism",
    "dali": "23_dali",
    "hopper": "24_hopper",
    "ghibli": "25_ghibli",
    "25": "25_ghibli",
    "vaporwave": "26_vaporwave",
    "kirby": "27_kirby",
    "monet": "28_monet",
    "seurat": "29_seurat",
    "matisse": "30_matisse",
    "haring": "31_haring",
    "rembrandt": "32_rembrandt",
    "rubberhose": "33_rubberhose",
    "shadowpuppet": "34_shadowpuppet",
    "shinkai": "35_shinkai",
    "picasso_blue": "36_picasso_blue",
}

STYLE_THEME_MAP: dict[str, str] = {
    "17_ink": "paper",
    "25_ghibli": "paper",
    "14_8bit": "bauhaus",
    "12_bauhaus": "bauhaus",
    "20_dunhuang": "wood",
    "26_vaporwave": "poster",
    "28_monet": "snow",
}


def resolve_style_id(style_input: str) -> str:
    raw = str(style_input).strip().lower()
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    if raw.endswith(".js"):
        raw = raw[:-3]
    if raw in STYLE_REGISTRY:
        return STYLE_REGISTRY[raw]
    if raw in STYLE_ALIASES:
        return STYLE_ALIASES[raw]
    for k in STYLE_REGISTRY:
        if k.startswith(f"{raw}_") or k.split("_", 1)[0] == raw or k.split("_", 1)[-1] == raw:
            return k
    return raw


def get_sha256(p: Path | str) -> str:
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


def generate_contact_sheet(video_path: Path, sheet_path: Path, total_dur: float, is_vertical: bool = False) -> None:
    fps_val = 6.0 / max(1.0, total_dur)
    scale_filter = "scale=240:-1" if is_vertical else "scale=320:-1"
    vf = f"fps={fps_val:.4f},{scale_filter},tile=3x2"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-vf", vf, "-frames:v", "1", "-update", "1", str(sheet_path)],
            check=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        # Fallback to simple tile if fps filter was slightly off
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-vf", f"fps=1,{scale_filter},tile=3x2", "-frames:v", "1", "-update", "1", str(sheet_path)],
                check=True,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def produce_artmotion(
    *,
    segments: list[NarrationSegment],
    output_dir: Path,
    style_id: str,
    grammar_id: str,
    aspect_ratio: str = "16:9",
    lang: str = "zh",
    tts_length_scale: float = 1.0,
    audio_path: Path | None = None,
) -> dict[str, Any]:
    os.environ["PATH"] = "/home/soffy/.local/bin:" + os.environ.get("PATH", "")

    output_dir = output_dir.resolve()
    work = output_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    t_all = time.monotonic()

    texts = [s for seg in segments for s in seg.sentences]
    if not texts:
        raise RuntimeError("no narration sentences")
    key_parts: list[Any] = [lang, GAP_S, LEAD_S, texts, tts_length_scale, str(audio_path) if audio_path else ""]
    key = hashlib.sha256(json.dumps(key_parts, ensure_ascii=False).encode()).hexdigest()
    voice = work / "voice.wav"
    ts_file = work / "timestamps.json"
    cached = _load_cached_timings(ts_file, key) if voice.is_file() else None
    if cached is not None:
        timings = cached
    elif audio_path is not None and Path(audio_path).is_file():
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "22050", "-ac", "1", str(voice)],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        total_s = duration(voice)
        from hevi.layer4_legacy.talkcraft.oprim_impl.sync import Timing, CharTiming
        timings = []
        dt = total_s / max(1, len(texts))
        for i, text in enumerate(texts):
            st_s = i * dt
            et_s = (i + 1) * dt
            char_dt = (et_s - st_s) / max(1, len(text))
            chars = [CharTiming(char=c, start_s=st_s + j * char_dt, end_s=st_s + (j + 1) * char_dt) for j, c in enumerate(text)]
            timings.append(Timing(index=i, start_s=st_s, end_s=et_s, text=text, chars=chars))
        ts_file.write_text(json.dumps({"key": key, "timings": [asdict(t) for t in timings]}, ensure_ascii=False, indent=1))
    else:
        al = WhisperAligner()
        parts = []
        for i, text in enumerate(texts):
            p = work / f"vo_{i:03d}.wav"
            piper_tts(text=text, out_wav=p, lang=lang, length_scale=tts_length_scale)
            parts.append(p)
        starts = concat_with_gaps(parts=parts, gap_s=GAP_S, lead_s=LEAD_S, out_wav=voice)

        timings = []
        for i, (text, p, st) in enumerate(zip(texts, parts, starts, strict=True)):
            timings.append(al.align(index=i, text=text, audio_path=str(p), start_s=st, end_s=st + duration(p), language=lang))
        ts_file.write_text(json.dumps({"key": key, "timings": [asdict(t) for t in timings]}, ensure_ascii=False, indent=1))
    total_s = duration(voice)

    # 3) Build spec.json
    props_cues = []
    props_data = {}
    for seg in segments:
        if "cues" in seg.props:
            props_cues.extend(seg.props["cues"])
        if "data" in seg.props:
            props_data.update(seg.props["data"])

    cues = []
    for i, (text, timing) in enumerate(zip(texts, timings)):
        at_t = timing.chars[0].start_s if timing.chars else timing.start_s
        if i < len(props_cues):
            cue = props_cues[i].copy()
            cue["at"] = at_t
            if "text" not in cue and cue.get("kind") not in ("bar", "highlight", "equation", "number", "card"):
                cue["text"] = text
            cues.append(cue)
        else:
            cues.append({
                "at": at_t,
                "kind": "point",
                "text": text,
            })
    fps = 30
    w, h = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)
    resolved_style = resolve_style_id(style_id)
    matched_theme = STYLE_THEME_MAP.get(resolved_style, "paper")

    spec = {
        "grammar": grammar_id,
        "style": resolved_style,
        "theme": matched_theme,
        "duration": total_s,
        "fps": fps,
        "width": w,
        "height": h,
        "cues": cues,
    }
    if props_data:
        spec["data"] = props_data
    spec_path = work / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2))

    # 4) Render via render.py
    render_script = Path(__file__).parent / "scripts" / "engine" / "render.py"
    mp4_out = work / "render_raw.mp4"
    st = time.monotonic()
    subprocess.run(
        [".venv/bin/python", str(render_script), "--spec", str(spec_path), "--audio", str(voice), "--out", str(mp4_out)],
        check=True
    )
    render_s = time.monotonic() - st

    out_video = output_dir / f"artmotion_{'landscape' if w > h else 'portrait'}.mp4"
    shutil.copy(mp4_out, out_video)

    # 5) Quality Gates: film_gate & deliver.py
    scripts_dir = Path(__file__).parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import film_gate

    gate_res, gate_rows = film_gate.measure(str(out_video), vertical="yes" if h > w else "no")

    deliver_script = scripts_dir / "deliver.py"
    deliver_out_dir = output_dir / "deliver_out"
    deliver_res = subprocess.run(
        [".venv/bin/python", str(deliver_script), str(out_video), "--spec", str(spec_path), "--out", str(deliver_out_dir)],
        capture_output=True,
        text=True,
    )

    gates = [
        {
            "name": "gate_light",
            "passed": gate_res["gate_light"] == "green",
            "value": gate_res["gate_light"],
            "message": gate_res["explain"]["summary"],
        },
        {
            "name": "fast_ratio",
            "passed": gate_res["lights"].get("fast_ratio") == "green",
            "value": gate_res["fast_ratio"],
            "threshold": ">=0.06 (green)",
            "light": gate_res["lights"].get("fast_ratio"),
        },
        {
            "name": "still_ratio",
            "passed": True,
            "value": gate_res["still_ratio"],
            "light": gate_res["lights"].get("still_ratio", "--"),
        },
        {
            "name": "blank_run_s",
            "passed": gate_res["lights"].get("blank_run_s") == "green",
            "value": gate_res["blank_run_s"],
            "threshold": "<0.3s (green)",
            "light": gate_res["lights"].get("blank_run_s"),
        },
        {
            "name": "blue_purple_share",
            "passed": gate_res["lights"].get("blue_purple_share") == "green",
            "value": gate_res["blue_purple_share"],
            "threshold": "<0.12 (green)",
            "light": gate_res["lights"].get("blue_purple_share"),
        },
        {
            "name": "artmotion_deliver",
            "passed": deliver_res.returncode == 0 and gate_res["gate_light"] == "green",
            "value": deliver_res.returncode,
            "message": deliver_res.stdout[-300:] if deliver_res.returncode != 0 else "Passed deliver.py (green)",
        },
    ]

    # Generate 6-frame contact sheet
    sheet_out = out_video.with_suffix(".sheet.jpg")
    generate_contact_sheet(out_video, sheet_out, total_s, is_vertical=(h > w))

    records = [{
        "video_path": str(out_video),
        "width": w,
        "height": h,
        "duration_s": total_s,
        "render_seconds": render_s,
        "style_id": resolved_style,
        "grammar_id": grammar_id,
        "gate_light": gate_res["gate_light"],
        "fast_ratio": gate_res["fast_ratio"],
        "still_ratio": gate_res["still_ratio"],
        "blank_run_s": gate_res["blank_run_s"],
        "blue_purple_share": gate_res["blue_purple_share"],
        "film_gate": {
            "gate_light": gate_res["gate_light"],
            "fast_ratio": gate_res["fast_ratio"],
            "still_ratio": gate_res["still_ratio"],
            "blank_run_s": gate_res["blank_run_s"],
            "blue_purple_share": gate_res["blue_purple_share"],
            "event_rate": gate_res["event_rate"],
            "longest_still_s": gate_res["longest_still_s"],
            "lights": gate_res["lights"],
            "explain": gate_res["explain"]["summary"],
        },
        "gates": gates,
        "sha256": get_sha256(out_video),
    }]

    result = {
        "status": "succeeded" if (all(g["passed"] for g in gates) and gate_res["gate_light"] == "green") else "failed",
        "records": records,
    }
    (output_dir / "record.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result

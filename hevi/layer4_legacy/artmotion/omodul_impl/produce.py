import json
import hashlib
import time
import shutil
import subprocess
from pathlib import Path
from typing import Any
from dataclasses import asdict
from hevi.layer4_legacy.talkcraft.oprim_impl.sync import NarrationSegment
from hevi.layer4_legacy.talkcraft.omodul_impl.produce import GAP_S, LEAD_S, _load_cached_timings
from hevi.layer4_legacy.talkcraft.omodul_impl._media import piper_tts, concat_with_gaps, duration
from hevi.layer4_legacy.talkcraft.omodul_impl._whisper import WhisperAligner

def produce_artmotion(
    *,
    segments: list[NarrationSegment],
    output_dir: Path,
    style_id: str,
    grammar_id: str,
    aspect_ratio: str = "16:9",
    lang: str = "zh",
    tts_length_scale: float = 1.0,
) -> dict[str, Any]:
    import os
    os.environ["PATH"] = "/home/soffy/.local/bin:" + os.environ.get("PATH", "")
    
    output_dir = output_dir.resolve()
    work = output_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    t_all = time.monotonic()

    texts = [s for seg in segments for s in seg.sentences]
    if not texts:
        raise RuntimeError("no narration sentences")
    key_parts: list[Any] = [lang, GAP_S, LEAD_S, texts, tts_length_scale]
    key = hashlib.sha256(json.dumps(key_parts, ensure_ascii=False).encode()).hexdigest()
    voice = work / "voice.wav"
    ts_file = work / "timestamps.json"
    cached = _load_cached_timings(ts_file, key) if voice.is_file() else None
    al = None
    if cached is not None:
        timings = cached
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
    cues = []
    for i, (text, timing) in enumerate(zip(texts, timings)):
        cues.append({
            "at": timing.chars[0].start_s if timing.chars else timing.start_s,
            "kind": "point",
            "text": text,
        })
    fps = 30
    w, h = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)
    spec = {
        "grammar": grammar_id,
        "theme": style_id,
        "duration": total_s,
        "fps": fps,
        "width": w,
        "height": h,
        "cues": cues,
    }
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
    
    # gates: fast motion etc from deliver.py? We can just do basic gates for now, or use deliver.py.
    # We will use the same measure logic as talkcraft if we can, or just basic.
    # The requirement says: "上游 deliver.py 的「红灯不交付」质检要保留并接进 Hevi 的 gates。"
    deliver_script = Path(__file__).parent / "scripts" / "deliver.py"
    deliver_res = subprocess.run([".venv/bin/python", str(deliver_script), str(out_video), "--spec", str(spec_path), "--out", str(output_dir / "deliver_out")], capture_output=True, text=True)
    
    gates = [{"name": "artmotion_deliver", "passed": deliver_res.returncode == 0, "value": deliver_res.returncode, "message": deliver_res.stdout[-200:] if deliver_res.returncode != 0 else "Passed deliver.py"}]
    
    # produce contact sheet
    sheet_out = out_video.with_suffix(".sheet.jpg")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(out_video), "-vf", "fps=1,scale=320:-1,tile=4x4", "-frames:v", "1", str(sheet_out)], check=True, stderr=subprocess.DEVNULL)
    except:
        pass
    
    def get_sha(p):
        h = hashlib.sha256()
        h.update(Path(p).read_bytes())
        return h.hexdigest()
    
    records = [{
        "video_path": str(out_video),
        "width": w,
        "height": h,
        "duration_s": total_s,
        "render_seconds": render_s,
        "gates": gates,
        "sha256": get_sha(out_video),
    }]
    
    result = {"status": "succeeded" if all(g["passed"] for g in gates) else "failed", "records": records}
    (output_dir / "record.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


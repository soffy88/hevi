"""s2 骊姬之乱 · N9 段装配:N0 9/9 净稿 → 成片段 + EDL。

后端 deterministic_layers(地图/题字) + S12 双半幅(三 cf,清欠账),零 provider。
镜头派发:establish(晋绛/三子分封) / dual_account→S12 双半幅 / hold→题字定格。地图镜成本≈0。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "hevi/tongjian/sandbox")
from s2_episode import build
from s2_mapstates import ms_jin_xiangong

from hevi.tongjian.map_anim import _static_map, animate_establish
from hevi.tongjian.quote_shots import render_dual_panel

OUT = Path("output/s2_liji/assemble")
OUT.mkdir(parents=True, exist_ok=True)
FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
BGM = "assets/audio/bgm/epic/a_generated_pad.wav"
VOICE = "zh-CN-YunjianNeural"
W, H, FPS = 1168, 784, 24

JIN = ms_jin_xiangong()
LOC = {
    "绛": (0.429, 0.564),
    "蒲": (0.329, 0.382),
    "屈": (0.343, 0.509),
    "曲沃": (0.421, 0.636),
    "梁": (0.171, 0.745),
    "翟": (0.443, 0.164),
    "卫": (0.871, 0.655),
}
_PLACES_OF = {"b0": ["绛", "蒲", "屈"], "b2": ["曲沃"], "b3": ["梁", "翟"], "b5": ["卫"]}

BEATS, FACTS, DUALS, ONSCREEN, CF_OF = build()
DUAL_BY = {d.beat_id: d for d in DUALS}


def render_shot(beat, dur: float, d: Path) -> Path:
    b = beat.beat_id
    if b in DUAL_BY:  # S12 双半幅(三 cf)
        return render_dual_panel(DUAL_BY[b], d, size=(W, H), fps=FPS, duration_s=dur)
    if beat.visual_intent == "establish":
        return animate_establish(JIN, d, duration_s=dur, fps=FPS)
    # hold:题字定格(应验/counterpoint)走晋底图
    still = d / "hold.png"
    d.mkdir(parents=True, exist_ok=True)
    _static_map(JIN, W, H).convert("RGB").save(still)
    mp4 = d / "hold.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(still),
            "-t",
            f"{dur}",
            "-r",
            str(FPS),
            "-pix_fmt",
            "yuv420p",
            str(mp4),
        ],
        check=True,
    )
    return mp4


def make_sub_png(vo_text: str, places: list[str], path: Path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 32)
    lines, cur = [], ""
    for ch in vo_text:
        cur += ch
        if len(cur) >= 22:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    lines = lines[:3]
    band_h = 24 + len(lines) * 42
    d.rectangle([0, H - band_h, W, H], fill=(20, 15, 8, 150))
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=f)
        x = (W - (bb[2] - bb[0])) // 2
        y = H - band_h + 14 + i * 42
        d.text((x + 1, y + 1), ln, font=f, fill=(0, 0, 0, 220))
        d.text((x, y), ln, font=f, fill=(240, 232, 210, 255))
    fp = ImageFont.truetype(FONT, 25)
    for name in places:
        if name not in LOC:
            continue
        px, py = int(LOC[name][0] * W), int(LOC[name][1] * H)
        d.text((px + 11, py - 35), name, font=fp, fill=(30, 20, 10, 255))
        d.text((px + 10, py - 36), name, font=fp, fill=(245, 235, 200, 255))
    img.save(path)


SFX_SPECS = {
    "establish": (
        "sine=frequency=110:duration=1.4",
        "afade=t=in:d=0.5,afade=t=out:st=0.9:d=0.5,volume=0.5",
    ),
    "expand": (
        "anoisesrc=d=0.5:c=brown",
        "bandpass=f=900:w=600,afade=t=out:st=0.1:d=0.4,volume=0.7",
    ),
    "hold": (
        "sine=frequency=98:duration=2.4",
        "afade=t=in:d=0.05,afade=t=out:st=0.5:d=1.9,volume=0.55",
    ),
}


def synth_sfx(cue: str, sfx_dir: Path) -> Path:
    sfx_dir.mkdir(parents=True, exist_ok=True)
    wav = sfx_dir / f"{cue}.wav"
    if not wav.exists():
        src, af = SFX_SPECS[cue]
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-af", af, str(wav)],
            check=True,
        )
    return wav


def build_sfx_track(edl, sfx_dir: Path, out_wav: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for e in edl:
        cmd += ["-i", str(synth_sfx(e["sfx_cue"], sfx_dir))]
    n = len(edl)
    parts = "".join(
        f"[{i}:a]adelay={int(e['start_s'] * 1000)}:all=1[s{i}];" for i, e in enumerate(edl)
    )
    graph = parts + "".join(f"[s{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0[a]"
    cmd += ["-filter_complex", graph, "-map", "[a]", str(out_wav)]
    subprocess.run(cmd, check=True)
    return out_wav


def _probe(p: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(p),
        ],
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


async def _tts_once(text: str, path: Path):
    clean = text.replace("——", ",").replace("—", ",").replace("……", ",").replace("…", ",")
    await edge_tts.Communicate(clean, VOICE, rate="-8%", pitch="-2Hz").save(str(path))


async def tts_beat(text: str, path: Path) -> float:
    last = None
    for attempt in range(4):
        try:
            await _tts_once(text, path)
            if path.exists() and path.stat().st_size > 500:
                break
        except Exception as e:
            last = e
        await asyncio.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"TTS 4 次仍失败: {last}")
    return _probe(path)


def _sfx_cue(beat) -> str:
    if beat.beat_id in DUAL_BY:
        return "expand"
    return beat.visual_intent if beat.visual_intent in SFX_SPECS else "hold"


def main():
    edl, clips, vo_mp3s, t = [], [], [], 0.0
    for beat in BEATS:
        d = OUT / beat.beat_id
        d.mkdir(parents=True, exist_ok=True)
        vo, clip = d / "vo.mp3", d / "clip.mp4"
        if vo.exists() and vo.stat().st_size > 500:
            dur = max(_probe(vo), 2.5)
        else:
            dur = max(asyncio.run(tts_beat(beat.vo_text, vo)), 2.5)
        vo_mp3s.append(vo)
        if not clip.exists():
            print(f"{beat.beat_id} [{beat.visual_intent}] VO {dur:.1f}s → 渲染…", flush=True)
            raw = render_shot(beat, dur, d)
            sub = d / "sub.png"
            make_sub_png(beat.vo_text, _PLACES_OF.get(beat.beat_id, []), sub)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(raw),
                    "-i",
                    str(sub),
                    "-filter_complex",
                    "[0][1]overlay=0:0[v]",
                    "-map",
                    "[v]",
                    "-r",
                    str(FPS),
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "18",
                    str(clip),
                ],
                check=True,
            )
        clips.append(clip)
        edl.append(
            {
                "beat": beat.beat_id,
                "intent": beat.visual_intent,
                "shot": "S12双半幅" if beat.beat_id in DUAL_BY else beat.visual_intent,
                "start_s": round(t, 2),
                "dur_s": round(dur, 2),
                "clip": str(clip),
                "sfx_cue": _sfx_cue(beat),
            }
        )
        t += dur

    (OUT / "clips.txt").write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    video = OUT / "video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(OUT / "clips.txt"),
            "-c",
            "copy",
            str(video),
        ],
        check=True,
    )
    (OUT / "vo.txt").write_text("".join(f"file '{c.resolve()}'\n" for c in vo_mp3s))
    vo_all = OUT / "vo_all.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(OUT / "vo.txt"),
            "-c:a",
            "aac",
            str(vo_all),
        ],
        check=True,
    )
    sfx_track = build_sfx_track(edl, OUT / "sfx", OUT / "sfx_track.wav")
    audio = OUT / "audio.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(vo_all),
            "-stream_loop",
            "-1",
            "-i",
            BGM,
            "-i",
            str(sfx_track),
            "-filter_complex",
            "[1:a]volume=0.10[bg];[2:a]volume=0.85[sf];[0:a][bg][sf]amix=inputs=3:duration=first:normalize=0[a]",
            "-map",
            "[a]",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    seg = OUT / "s2_liji_segment.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(seg),
        ],
        check=True,
    )
    (OUT / "edl.json").write_text(
        json.dumps(
            {
                "episode": "ep_jin_decline_s2",
                "version": "s2-N9-v1",
                "total_s": round(t, 2),
                "fps": FPS,
                "vo_voice": VOICE,
                "bgm": BGM,
                "backends": {
                    "map": "deterministic_layers",
                    "S12": "双半幅纸雕(确定性)",
                    "hold": "题字定格",
                },
                "beats": edl,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n成片段 → {seg}  ({_probe(seg):.1f}s)\nEDL → {OUT / 'edl.json'}")


if __name__ == "__main__":
    main()

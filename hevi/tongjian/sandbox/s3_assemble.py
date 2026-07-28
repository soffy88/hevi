"""s3 晋作三军五军·六卿彊 · N9 段装配:N0 7/9 净稿 → 成片段 + EDL。

后端 deterministic_layers + S13 竹简(多 onscreen)+ S12 双半幅(上军主帅 cf),零 provider。
派发:onscreen→S13 竹简;dual_account→S12;establish→晋map(含河流/城邑增强)。地图镜成本≈0。
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
from s3_episode import build
from s3_mapstates import ms_jin_wengong

from hevi.tongjian.map_anim import animate_establish
from hevi.tongjian.quote_shots import render_dual_panel, render_quote_slip

OUT = Path("output/s3_liujing/assemble")
OUT.mkdir(parents=True, exist_ok=True)
FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
BGM = "assets/audio/bgm/epic/a_generated_pad.wav"
VOICE = "zh-CN-YunjianNeural"
W, H, FPS = 1168, 784, 24
JIN = ms_jin_wengong()
LOC = {
    "绛": (0.368, 0.554),
    "被庐": (0.337, 0.631),
    "清原": (0.316, 0.492),
    "曹": (0.758, 0.692),
    "卫": (0.674, 0.6),
    "宋": (0.737, 0.785),
}
_PLACES_OF = {"b0": ["绛"], "b1": ["被庐", "宋"], "b2": ["清原"], "b3": ["绛"]}
BEATS, FACTS, DUALS, ONSCREEN, _ = build()
DUAL_BY = {d.beat_id: d for d in DUALS}


def render_shot(beat, dur, d):
    b = beat.beat_id
    if b in DUAL_BY:  # S12(cf 上军主帅)优先
        return render_dual_panel(DUAL_BY[b], d, size=(W, H), fps=FPS, duration_s=dur)
    if b in ONSCREEN:  # S13 竹简(onscreen 文言)
        return render_quote_slip(ONSCREEN[b], d, form="竹简", size=(W, H), fps=FPS, duration_s=dur)
    return animate_establish(JIN, d, duration_s=dur, fps=FPS)  # b0 establish


def make_sub_png(vo_text, places, path):
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
    bh = 24 + len(lines) * 42
    d.rectangle([0, H - bh, W, H], fill=(20, 15, 8, 150))
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=f)
        x = (W - (bb[2] - bb[0])) // 2
        y = H - bh + 14 + i * 42
        d.text((x + 1, y + 1), ln, font=f, fill=(0, 0, 0, 220))
        d.text((x, y), ln, font=f, fill=(240, 232, 210, 255))
    fp = ImageFont.truetype(FONT, 25)
    for name in places:
        if name in LOC:
            px, py = int(LOC[name][0] * W), int(LOC[name][1] * H)
            d.text((px + 11, py - 35), name, font=fp, fill=(30, 20, 10, 255))
            d.text((px + 10, py - 36), name, font=fp, fill=(245, 235, 200, 255))
    img.save(path)


SFX = {
    "establish": (
        "sine=frequency=110:duration=1.4",
        "afade=t=in:d=0.5,afade=t=out:st=0.9:d=0.5,volume=0.5",
    ),
    "expand": (
        "anoisesrc=d=0.5:c=brown",
        "bandpass=f=900:w=600,afade=t=out:st=0.1:d=0.4,volume=0.7",
    ),
    "highlight": ("sine=frequency=880:duration=0.5", "afade=t=out:st=0.05:d=0.45,volume=0.45"),
}


def synth_sfx(cue, sd):
    sd.mkdir(parents=True, exist_ok=True)
    wav = sd / f"{cue}.wav"
    if not wav.exists():
        src, af = SFX[cue]
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-af", af, str(wav)],
            check=True,
        )
    return wav


def build_sfx(edl, sd, out):
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for e in edl:
        cmd += ["-i", str(synth_sfx(e["sfx_cue"], sd))]
    n = len(edl)
    g = "".join(f"[{i}:a]adelay={int(e['start_s'] * 1000)}:all=1[s{i}];" for i, e in enumerate(edl))
    g += "".join(f"[s{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0[a]"
    subprocess.run([*cmd, "-filter_complex", g, "-map", "[a]", str(out)], check=True)
    return out


def _probe(p):
    return float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(p),
            ],
            capture_output=True,
            text=True,
        ).stdout
    )


async def _tts(text, path):
    clean = (
        text.replace("——", ",")
        .replace("—", ",")
        .replace("……", ",")
        .replace("…", ",")
        .replace("『", "")
        .replace("』", "")
    )
    await edge_tts.Communicate(clean, VOICE, rate="-8%", pitch="-2Hz").save(str(path))


async def tts_beat(text, path):
    for a in range(4):
        try:
            await _tts(text, path)
            if path.exists() and path.stat().st_size > 500:
                break
        except Exception:
            pass
        await asyncio.sleep(1.5 * (a + 1))
    return _probe(path)


def _sfx_cue(beat):
    return (
        "expand"
        if beat.beat_id in DUAL_BY
        else ("highlight" if beat.beat_id in ONSCREEN else "establish")
    )


def main():
    edl, clips, vos, t = [], [], [], 0.0
    for beat in BEATS:
        d = OUT / beat.beat_id
        d.mkdir(parents=True, exist_ok=True)
        vo, clip = d / "vo.mp3", d / "clip.mp4"
        dur = max(
            _probe(vo)
            if vo.exists() and vo.stat().st_size > 500
            else asyncio.run(tts_beat(beat.vo_text, vo)),
            2.5,
        )
        vos.append(vo)
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
                "shot": "S12双半幅"
                if beat.beat_id in DUAL_BY
                else ("S13竹简" if beat.beat_id in ONSCREEN else "establish"),
                "start_s": round(t, 2),
                "dur_s": round(dur, 2),
                "clip": str(clip),
                "sfx_cue": _sfx_cue(beat),
            }
        )
        t += dur
    (OUT / "clips.txt").write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
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
            str(OUT / "video.mp4"),
        ],
        check=True,
    )
    (OUT / "vo.txt").write_text("".join(f"file '{c.resolve()}'\n" for c in vos))
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
            str(OUT / "vo_all.m4a"),
        ],
        check=True,
    )
    sfx = build_sfx(edl, OUT / "sfx", OUT / "sfx_track.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(OUT / "vo_all.m4a"),
            "-stream_loop",
            "-1",
            "-i",
            BGM,
            "-i",
            str(sfx),
            "-filter_complex",
            "[1:a]volume=0.10[bg];[2:a]volume=0.85[sf];[0:a][bg][sf]amix=inputs=3:duration=first:normalize=0[a]",
            "-map",
            "[a]",
            "-c:a",
            "aac",
            str(OUT / "audio.m4a"),
        ],
        check=True,
    )
    seg = OUT / "s3_liujing_segment.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(OUT / "video.mp4"),
            "-i",
            str(OUT / "audio.m4a"),
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
                "episode": "ep_jin_decline_s3",
                "version": "s3-N9-v1",
                "total_s": round(t, 2),
                "fps": FPS,
                "vo_voice": VOICE,
                "bgm": BGM,
                "backends": {"map": "deterministic_layers", "S13": "竹简纸雕", "S12": "双半幅纸雕"},
                "beats": edl,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n成片段 → {seg} ({_probe(seg):.1f}s)")


if __name__ == "__main__":
    main()

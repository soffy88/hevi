"""s1 曲沃代翼 · N9 段装配:N0 9/9 净稿 → 成片段 + EDL。

后端全 deterministic_layers(地图/图解)+ 程序化纸偶(立牌)+ S13 竹简 + S12 双半幅,零 provider。
VO 按拍定时(edge_tts,onscreen 引文不口播由 vo 转述驱动时轴)→ 每拍渲染确定性镜头填 VO 时长 →
字幕/地名 R7 合成 → 拼接 → VO+BGM+SFX 混音 → 成片段。地图镜成本≈0。

镜头派发(N0-D-010/§5):onscreen→S13 竹简;dual_account→S12 双半幅(清 G1a 数据有画面无欠账);
establish/character(立牌)/route/battle(落点)/split_merge(撕裂)/hold(题字)→ map_anim。
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
from s1_episode import build
from s1_mapstates import ms_quwo_absorbed, ms_yi_independent

from hevi.tongjian.force_colors import get_force_color
from hevi.tongjian.map_anim import (
    _static_map,
    animate_establish,
    animate_landing,
    animate_route,
    animate_standee,
    animate_tear,
)
from hevi.tongjian.quote_shots import render_dual_panel, render_quote_slip

OUT = Path("output/s1_quwo_daiyi/assemble")
OUT.mkdir(parents=True, exist_ok=True)
FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
BGM = "assets/audio/bgm/epic/a_generated_pad.wav"
VOICE = "zh-CN-YunjianNeural"
W, H, FPS = 1168, 784, 24

YI = ms_yi_independent()
ABSORBED = ms_quwo_absorbed()
BASE = _static_map(YI, W, H)

# 焦点投影下地点分数坐标(lon 109-114.5, lat 33-37.5)
LOC = {
    "翼": (0.491, 0.40),
    "曲沃": (0.44, 0.444),
    "汾隰": (0.318, 0.522),
    "陘庭": (0.513, 0.344),
    "随": (0.24, 0.40),
}
# 立牌:桓叔(封于曲沃,袍色读曲沃注册色;trim/冠=身份)
STANDEE = {"huanshu": {"force": "quwo", "trim": (150, 120, 40), "crown": True, "seed": 33}}
SFX_OF = {"dual_account": "expand", "quote_slip": "highlight", "hold": "hold"}

BEATS, FACTS, DUALS, ONSCREEN, CF_OF = build()
DUAL_BY = {d.beat_id: d for d in DUALS}


def _sfx_cue(beat) -> str:
    if beat.beat_id in ONSCREEN:
        return "highlight"
    if beat.beat_id in DUAL_BY:
        return "expand"
    return beat.visual_intent if beat.visual_intent in _SFX_KEYS else "hold"


_SFX_KEYS = {
    "establish",
    "character",
    "route",
    "battle",
    "split_merge",
    "hold",
    "highlight",
    "expand",
    "timeline",
}


def render_shot(beat, dur: float, d: Path) -> Path:
    """按 beat 派发确定性镜头,时长=dur。onscreen→S13;dual_account→S12;否则按 intent。"""
    b = beat.beat_id
    # S13 竹简(onscreen 引文本体上屏,vo 转述驱动时轴)
    if b in ONSCREEN:
        return render_quote_slip(ONSCREEN[b], d, form="竹简", size=(W, H), fps=FPS, duration_s=dur)
    # S12 双半幅对勘(两 cf,清 G1a 欠账)
    if b in DUAL_BY:
        return render_dual_panel(DUAL_BY[b], d, size=(W, H), fps=FPS, duration_s=dur)
    vi = beat.visual_intent
    if vi == "establish":
        return animate_establish(YI, d, duration_s=dur, fps=FPS)
    if vi == "character":
        who = FACTS[beat.order].persons[0]
        kw = dict(STANDEE[who])
        kw["accent"] = get_force_color(kw.pop("force")).rgb
        return animate_standee(out_dir=d, tag=who, duration_s=dur, fps=FPS, **kw)
    if vi == "route":  # 曲沃屡伐翼
        return animate_route(
            [LOC["曲沃"], (0.47, 0.42), LOC["翼"]],
            d,
            base=BASE.copy(),
            color=get_force_color("quwo").rgb,
            width=16,
            duration_s=dur,
            fps=FPS,
            tag="fa_yi",
        )
    if vi == "battle":  # 诱杀/落点 @曲沃
        tx, ty = LOC["曲沃"]
        return animate_landing(
            tx, ty, d, base=BASE.copy(), accent=get_force_color("quwo").rgb, duration_s=dur, fps=FPS
        )
    if vi == "split_merge":  # 曲沃吞并翼(撕裂/合并)
        return animate_tear(YI, ABSORBED, d, duration_s=dur, fps=FPS)
    # hold:题字定格(应验/counterpoint)走吞并态底图
    still = d / "hold.png"
    d.mkdir(parents=True, exist_ok=True)
    _static_map(ABSORBED, W, H).convert("RGB").save(still)
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
    """字幕底带 + 地名 R7 合成层(透明 PNG)。"""
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
    "character": (
        "anoisesrc=d=0.14:c=pink",
        "highpass=f=1200,afade=t=out:st=0.04:d=0.1,volume=0.8",
    ),
    "route": (
        "anoisesrc=d=1.2:c=pink",
        "bandpass=f=3000:w=1500,tremolo=f=9:d=0.7,afade=t=out:st=0.7:d=0.5,volume=0.5",
    ),
    "battle": (
        "anoisesrc=d=1.6:c=brown",
        "lowpass=f=900,afade=t=in:d=0.3,afade=t=out:st=1.0:d=0.6,volume=0.7",
    ),
    "highlight": ("sine=frequency=880:duration=0.5", "afade=t=out:st=0.05:d=0.45,volume=0.45"),
    "split_merge": (
        "anoisesrc=d=0.8:c=pink",
        "highpass=f=1500,afade=t=out:st=0.15:d=0.6,volume=0.75",
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


def _probe(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
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


_PLACES_OF = {"b3": ["翼", "随"], "b5": ["曲沃"], "b6": ["翼"]}


def main():
    edl, clips, vo_mp3s, t_cursor = [], [], [], 0.0
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
        else:
            print(f"{beat.beat_id} 复用 clip (VO {dur:.1f}s)", flush=True)
        clips.append(clip)
        edl.append(
            {
                "beat": beat.beat_id,
                "intent": beat.visual_intent,
                "shot": "S13竹简"
                if beat.beat_id in ONSCREEN
                else "S12双半幅"
                if beat.beat_id in DUAL_BY
                else beat.visual_intent,
                "start_s": round(t_cursor, 2),
                "dur_s": round(dur, 2),
                "clip": str(clip),
                "sfx_cue": _sfx_cue(beat),
            }
        )
        t_cursor += dur

    # 拼接视频 + VO
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
    segment = OUT / "s1_quwo_daiyi_segment.mp4"
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
            str(segment),
        ],
        check=True,
    )
    edl_doc = {
        "episode": "ep_jin_decline_s1",
        "version": "s1-N9-v1",
        "total_s": round(t_cursor, 2),
        "fps": FPS,
        "vo_voice": VOICE,
        "bgm": BGM,
        "backends": {
            "map": "deterministic_layers",
            "standee": "程序化纸偶",
            "S13": "竹简纸雕(确定性)",
            "S12": "双半幅纸雕(确定性)",
        },
        "beats": edl,
    }
    (OUT / "edl.json").write_text(json.dumps(edl_doc, ensure_ascii=False, indent=2))
    print(f"\n成片段 → {segment}  ({_probe(segment):.1f}s)")
    print(f"EDL → {OUT / 'edl.json'}")


if __name__ == "__main__":
    main()

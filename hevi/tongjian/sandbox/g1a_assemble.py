"""G1a · N9 段装配:facts+模板+VO → 成片段 + EDL。

云健 VO 按拍定时序 → 每拍渲染确定性镜头(填该拍 VO 时长)→ 字幕/地名后期合成(R7)→
拼接 → VO+BGM+SFX 混音 → 成片段。地图/图解镜零 provider。

v3(閘④ 裁决 2026-07-22):①S10 年份文字 R7 上屏(随游标到位分时显现)
②B06 对勘角标合成(文本取自 DualAccountFact,不硬编码)③SFX v0 粗混入轨
(音源=ffmpeg lavfi 合成占位,審链路完整不審终版音效设计)④立牌袍色一律读勢力色注册表。
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
from g0d_453_mapstates import ms_453_split, ms_453_unified
from g1a_episode import BEATS, DUAL_ACCOUNTS

from hevi.tongjian.force_colors import get_force_color
from hevi.tongjian.map_anim import (
    _static_map,
    animate_establish,
    animate_fissure_reveal,
    animate_landing,
    animate_route,
    animate_standee,
    animate_tear,
    animate_timeline,
)

OUT = Path("output/g1a_sanjia_fenjin/assemble")
OUT.mkdir(parents=True, exist_ok=True)
FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
BGM = "assets/audio/bgm/epic/a_generated_pad.wav"
VOICE = "zh-CN-YunjianNeural"
W, H, FPS = 1168, 784, 24

UNI = ms_453_unified()
SPLIT = ms_453_split()
BASE = _static_map(UNI, W, H)
JINYANG = (0.5, 0.418)  # 晋阳 lon112.5 lat37.9

# 立牌角色(T1,具名且露脸) — 袍色一律读勢力色注册表(裁决 2026-07-22);trim/冠/须=身份细节
STANDEE = {
    "zhibo": {"force": "zhi", "trim": (150, 30, 20), "crown": True, "seed": 11},
    "zhaoxiangzi": {"force": "zhao", "trim": (30, 50, 110), "elder": True, "seed": 22},
    # 张孟谈:赵家臣补 T1(裁决"具名且露脸=T1")。袍随赵色,浅米领异饰与赵襄子区分
    "zhangmengtan": {"force": "zhao", "trim": (232, 224, 202), "seed": 55},
}


def standee_kwargs(who: str) -> dict:
    kw = dict(STANDEE[who])
    kw["accent"] = get_force_color(kw.pop("force")).rgb
    return kw


def render_shot(beat, dur, d: Path) -> Path:
    """按 beat 渲染其确定性镜头,时长=dur。"""
    b = beat.beat_id
    if b == "B01":
        return animate_establish(UNI, d, duration_s=dur, fps=FPS)
    if b == "B02":
        return animate_standee(
            out_dir=d, tag="zhibo", duration_s=dur, fps=FPS, **standee_kwargs("zhibo")
        )
    if b == "B03":
        return animate_fissure_reveal(UNI, SPLIT.fissures, d, duration_s=dur, fps=FPS)
    if b == "B04":
        return animate_standee(
            out_dir=d, tag="zhao", duration_s=dur, fps=FPS, **standee_kwargs("zhaoxiangzi")
        )
    if b == "B05":
        return animate_route(
            [(0.44, 0.62), (0.47, 0.52), *[JINYANG]],
            d,
            base=BASE.copy(),
            color=(140, 40, 30),
            width=17,
            duration_s=dur,
            fps=FPS,
            tag="siege",
        )
    if b == "B06":
        return animate_route(
            [(0.40, 0.30), (0.44, 0.36), (0.47, 0.40), JINYANG],
            d,
            base=BASE.copy(),
            color=(70, 120, 200),
            width=18,
            duration_s=dur,
            fps=FPS,
            tag="water",
        )
    if b == "B07":
        return animate_standee(
            out_dir=d, tag="zhang", duration_s=dur, fps=FPS, **standee_kwargs("zhangmengtan")
        )
    if b == "B08":
        return animate_landing(
            *JINYANG, d, base=BASE.copy(), accent=(70, 120, 200), duration_s=dur, fps=FPS
        )
    if b == "B09":
        return animate_tear(UNI, SPLIT, d, duration_s=dur, fps=FPS)
    if b == "B10":
        return animate_timeline(
            [(456 - y) / 53 for y in (456, 455, 453, 403)], d, duration_s=dur, fps=FPS
        )
    # B11 hold:分晋定格 + 臣光曰(字幕层)。走 _static_map(与全段同款水墨渲染)
    still = d / "hold.png"
    d.mkdir(parents=True, exist_ok=True)
    _static_map(SPLIT, W, H).convert("RGB").save(still)
    mp4 = d / "b11_hold.mp4"
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


def make_sub_png(vo_text: str, place: str | None, path: Path):
    """字幕(底带) + 地名(晋阳)后期合成层(R7)。透明 PNG。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 34)
    # 折行 ~20 字
    lines, cur = [], ""
    for ch in vo_text:
        cur += ch
        if len(cur) >= 20:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    lines = lines[:3]
    band_h = 24 + len(lines) * 44
    d.rectangle([0, H - band_h, W, H], fill=(20, 15, 8, 150))
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=f)
        x = (W - (bb[2] - bb[0])) // 2
        y = H - band_h + 14 + i * 44
        d.text((x + 1, y + 1), ln, font=f, fill=(0, 0, 0, 220))
        d.text((x, y), ln, font=f, fill=(240, 232, 210, 255))
    if place:
        fp = ImageFont.truetype(FONT, 26)
        px, py = int(JINYANG[0] * W), int(JINYANG[1] * H)
        d.text((px + 12, py - 34), place, font=fp, fill=(30, 20, 10, 255))
        d.text((px + 11, py - 35), place, font=fp, fill=(245, 235, 200, 255))
    img.save(path)


def make_year_overlays(d: Path) -> tuple[Path, Path]:
    """S10 年份文字 R7 上屏(v3 ①)。坐标同 animate_timeline 轴几何;456/455/453 挤左错行防叠。
    返回(左组,右组)两层,右组随游标到位分时 enable。"""
    x0, x1, ax_y = int(W * 0.12), int(W * 0.88), int(H * 0.52)
    f = ImageFont.truetype(FONT, 22)

    def px(year: int) -> int:
        return int(x0 + ((456 - year) / 53) * (x1 - x0))

    def draw(labels: list[tuple[str, int, int]], path: Path) -> Path:
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        for text, x, y in labels:
            bb = dr.textbbox((0, 0), text, font=f)
            xx = min(max(x - (bb[2] - bb[0]) // 2, 6), W - (bb[2] - bb[0]) - 6)
            dr.text((xx + 1, y + 1), text, font=f, fill=(248, 240, 218, 200))
            dr.text((xx, y), text, font=f, fill=(62, 44, 26, 255))
        img.save(path)
        return path

    left = draw(
        [
            ("前453", px(453), ax_y - 149),
            ("前456", px(456), ax_y - 121),
            ("前455", px(455), ax_y - 93),
        ],
        d / "years_left.png",
    )
    right = draw([("前403", px(403), ax_y - 121)], d / "years_right.png")
    return left, right


def make_collation_note(path: Path) -> Path:
    """B06 对勘角标(v3 ②):文本取自 DualAccountFact(数据已在,装配只呈现),右上纸卡。"""
    dual = DUAL_ACCOUNTS[0]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    ft = ImageFont.truetype(FONT, 22)
    fs = ImageFont.truetype(FONT, 20)
    lines = [(f"史载互异 · {dual.dimension}", ft)] + [
        (f"{a.source_display}:{a.summary}", fs) for a in dual.accounts
    ]
    pad, lh = 14, 30
    wpx = max(dr.textbbox((0, 0), t, font=fo)[2] for t, fo in lines) + pad * 2
    hpx = pad * 2 + lh * len(lines)
    x0, y0 = W - wpx - 22, 22
    dr.rectangle([x0, y0, x0 + wpx, y0 + hpx], fill=(244, 236, 216, 208), outline=(90, 66, 40, 230))
    for i, (t, fo) in enumerate(lines):
        dr.text((x0 + pad, y0 + pad + i * lh), t, font=fo, fill=(62, 44, 26, 255))
    img.save(path)
    return path


# SFX v0 占位音源(v3 ③):ffmpeg lavfi 合成,按 intent 贴点。審链路完整,不審终版音效设计。
SFX_SPECS: dict[str, tuple[str, str]] = {
    "establish": (
        "sine=frequency=110:duration=1.4",
        "afade=t=in:d=0.5,afade=t=out:st=0.9:d=0.5,volume=0.5",
    ),
    "character": (
        "anoisesrc=d=0.14:c=pink",
        "highpass=f=1200,afade=t=out:st=0.04:d=0.1,volume=0.8",
    ),
    "expand": (
        "anoisesrc=d=0.5:c=brown",
        "bandpass=f=900:w=600,afade=t=out:st=0.1:d=0.4,volume=0.7",
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
    "timeline": ("sine=frequency=1500:duration=0.09", "afade=t=out:st=0.02:d=0.07,volume=0.7"),
    "hold": (
        "sine=frequency=98:duration=2.4",
        "afade=t=in:d=0.05,afade=t=out:st=0.5:d=1.9,volume=0.55",
    ),
}


def synth_sfx(intent: str, sfx_dir: Path) -> Path:
    sfx_dir.mkdir(parents=True, exist_ok=True)
    wav = sfx_dir / f"{intent}.wav"
    if not wav.exists():
        src, af = SFX_SPECS[intent]
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-af", af, str(wav)],
            check=True,
        )
    return wav


def build_sfx_track(edl: list[dict], sfx_dir: Path, out_wav: Path) -> Path:
    """按 EDL 贴点把各拍占位 SFX adelay 到位后粗混成整轨。"""
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


def _probe_dur(path: Path) -> float:
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
    # 消毒:破折号/省略号会让 edge_tts 偶发空音频
    clean = text.replace("——", ",").replace("—", ",").replace("……", ",").replace("…", ",")
    await edge_tts.Communicate(clean, VOICE, rate="-8%", pitch="-2Hz").save(str(path))


async def tts_beat(text: str, path: Path) -> float:
    last = None
    for attempt in range(4):  # edge_tts 间歇 NoAudioReceived → 重试
        try:
            await _tts_once(text, path)
            if path.exists() and path.stat().st_size > 500:
                break
        except Exception as e:
            last = e
        await asyncio.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"TTS 4 次仍失败: {last}")
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


def main():
    edl = []
    clips = []
    vo_mp3s = []
    place_beats = {"B05": "晋阳", "B06": "晋阳", "B08": "晋阳"}
    t_cursor = 0.0
    for beat in BEATS:
        d = OUT / beat.beat_id
        d.mkdir(parents=True, exist_ok=True)
        vo = d / "vo.mp3"
        clip = d / "clip.mp4"
        # VO 幂等复用(免重打 edge_tts,避开其间歇失败);clip 缺失则重渲(地图升级后强制)
        if vo.exists() and vo.stat().st_size > 500:
            dur = max(_probe_dur(vo), 2.2)
        else:
            dur = max(asyncio.run(tts_beat(beat.vo_text, vo)), 2.2)
        vo_mp3s.append(vo)
        if clip.exists():
            print(f"{beat.beat_id} 复用 clip (VO {dur:.1f}s)", flush=True)
        else:
            print(f"{beat.beat_id} [{beat.visual_intent}] VO {dur:.1f}s → 渲染…", flush=True)
            raw = render_shot(beat, dur, d)
            sub = d / "sub.png"
            make_sub_png(beat.vo_text, place_beats.get(beat.beat_id), sub)
            # v3:附加 R7 图层 —— (png, enable表达式|None)
            extra: list[tuple[Path, str | None]] = []
            if beat.beat_id == "B06":
                extra.append((make_collation_note(d / "collation_note.png"), None))
            if beat.beat_id == "B10":
                yl, yr = make_year_overlays(d)
                # 左组随游标扫过挤左三桩后显现;右组等游标近终位(同 animate_timeline 推进曲线)
                extra.append((yl, f"gte(t,{dur * 0.24:.2f})"))
                extra.append((yr, f"gte(t,{dur * 0.86:.2f})"))
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-i", str(sub)]
            for p, _ in extra:
                cmd += ["-i", str(p)]
            graph = "[0][1]overlay=0:0[v1]"
            for i, (_, enable) in enumerate(extra):
                en = f"=enable='{enable}'" if enable else "=0:0"
                graph += f";[v{i + 1}][{i + 2}]overlay{en}[v{i + 2}]"
            last_lbl = f"[v{len(extra) + 1}]"
            cmd += [
                "-filter_complex",
                graph,
                "-map",
                last_lbl,
                "-r",
                str(FPS),
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                str(clip),
            ]
            subprocess.run(cmd, check=True)
        clips.append(clip)
        edl.append(
            {
                "beat": beat.beat_id,
                "intent": beat.visual_intent,
                "start_s": round(t_cursor, 2),
                "dur_s": round(dur, 2),
                "clip": str(clip),
                "sfx_cue": beat.visual_intent,
            }
        )
        t_cursor += dur

    # 拼接视频
    lst = OUT / "clips.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
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
            str(lst),
            "-c",
            "copy",
            str(video),
        ],
        check=True,
    )
    # 拼接 VO
    volst = OUT / "vo.txt"
    volst.write_text("".join(f"file '{c.resolve()}'\n" for c in vo_mp3s))
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
            str(volst),
            "-c:a",
            "aac",
            str(vo_all),
        ],
        check=True,
    )
    # SFX 整轨(v3 ③:占位音源按 EDL 贴点粗混)
    sfx_track = build_sfx_track(edl, OUT / "sfx", OUT / "sfx_track.wav")
    # VO + BGM(epic,低音量循环) + SFX 混音
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
            "[1:a]volume=0.10[bg];[2:a]volume=0.85[sx];"
            "[0:a][bg][sx]amix=inputs=3:duration=first:normalize=0[a]",
            "-map",
            "[a]",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    # 合成成片段
    final = OUT / "sanjia_fenjin_segment.mp4"
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
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(final),
        ],
        check=True,
    )
    (OUT / "edl.json").write_text(
        json.dumps(
            {
                "episode": "ep_sanjia_fenjin",
                "version": "v3",
                "total_s": round(t_cursor, 2),
                "fps": FPS,
                "vo_voice": VOICE,
                "bgm": BGM,
                "sfx": {
                    "mixed": True,
                    "placeholder": True,
                    "note": "v0 占位音源(lavfi 合成),閘④ 審链路不審终版音效设计",
                    "track": str(OUT / "sfx_track.wav"),
                },
                "beats": edl,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n✅ 成片段: {final}  总时长 {t_cursor:.1f}s")
    print(f"   EDL: {OUT / 'edl.json'}")


if __name__ == "__main__":
    main()

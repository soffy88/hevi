#!/usr/bin/env python3
"""「智伯索地」完整版 —— 纯云水墨戏剧短片,happyhorse 数字人配音+口型(无本地 GPU)。

对应资治通鉴·周纪一:智伯索地于魏宣子→魏弗予→任章进言→予万户之邑→智伯大悦→复索地
于赵弗与→围晋阳→韩魏反外赵应内→智氏自亡。

核心(v5,复刻 scene_v2 的做法):**happyhorse-1.1-r2v 是"会说话的数字人"**——喂一张水墨
参考图 + 台词,它一步生成带**配音 + 口型同步 + 动作**的视频(用 ALIBABA_MAAS key)。所以:
- **对白镜头**:happyhorse(角色水墨像 + 该角色台词)→ 直接用它自带的配音和口型。
- **旁白镜头**:happyhorse(史官像 + 旁白文本)→ 只取音轨作旁白;画面用 wan2.2-i2v 让人物
  闭嘴做神态动作(或战争空镜),把旁白音轨铺上去(人物不 lip-sync 旁白)。
关键帧仍用 qwen-image(角色 canonical)+ qwen-image-edit(按镜改表情,云端锁脸)。
转场用 xfade 溶解,镜头叠 zoompan 缓推。全云端、零 GPU、按 shot 缓存不重复扣费。

用法: .venv/bin/python scripts/build_scene_zhibo_full.py
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from hevi.image.qwen_image_service import qwen_image_edit, qwen_image_generate
from hevi.video.dashscope_i2v_service import happyhorse_animate, i2v_animate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_scene_zhibo_full")

_OUT_DIR = Path("output/tongjian/zhibo_suodi")
_WORK = _OUT_DIR / "full_work_cloud"
_OUTPUT = _OUT_DIR / "scene_v5_full.mp4"  # v4 保留(scene_v4_full_KEEP.mp4)

_CHAR_DESC = {
    "zhibo": (
        "国画水墨写意人物画,战国时代权臣智伯,壮年男子,黑发黑色短须,浓眉深目,神情倨傲威严,"
        "身着黑色云纹深衣,头戴玄色高冠,近景半身像,身后是朝堂木柱与淡淡薄雾,单色水墨,"
        "写意笔触,宣纸质感,右侧竖排题字与朱红印章"
    ),
    "weihuanzi": (
        "国画水墨写意人物画,战国魏氏宗主魏桓子,四十岁男子,黑发黑须,面容方正沉稳,神情持重多虑,"
        "身着深褐色深衣,头戴玄色高冠,近景半身像,身后是朝堂木柱与淡淡薄雾,单色水墨,"
        "写意笔触,宣纸质感,右侧竖排题字与朱红印章"
    ),
    "renzhang": (
        "国画水墨写意人物画,战国谋士任章,四十岁男子,黑发黑色短须,目光睿智从容,神情沉着,"
        "身着素色深衣,头戴幅巾,近景半身像,身后是朝堂木柱与淡淡薄雾,单色水墨,"
        "写意笔触,宣纸质感,右侧竖排题字与朱红印章"
    ),
}
_EDIT_PREFIX = "严格保持画中人物的相貌、胡须、服饰、头冠和水墨画风完全不变,只改变神态动作:"

# 分镜:sp(NARRATOR=旁白/否则该角色说自己台词)/text(说的内容)/lead(角色,None=战争空镜)/
# edit(角色关键帧 qwen-image-edit 的神态指令)/scene(战争 qwen-image 文生图)/say(对白镜头
# happyhorse 的动作神态描述,台词会拼在后面)/motion(旁白镜头 i2v 的闭嘴动作)。
_SHOTS: list[dict] = [
    {
        "id": "S01",
        "sp": "NARRATOR",
        "lead": "zhibo",
        "text": "战国初年,晋国最有权势的智伯,野心越来越大。他仗着兵强马壮,张口就向魏桓子要一块地。",
        "edit": "昂首挺立,神情倨傲逼人",
        "motion": "人物昂首挺立,神情倨傲,须髯与衣袖轻动,闭着嘴",
    },
    {
        "id": "S02",
        "sp": "NARRATOR",
        "lead": "weihuanzi",
        "text": "魏桓子心里很不痛快,压根不想给。",
        "edit": "眉头微皱,面露不悦,轻轻摇头",
        "motion": "人物微皱眉,轻轻摇头,神色不豫,闭着嘴",
    },
    {
        "id": "S03",
        "sp": "renzhang",
        "lead": "renzhang",
        "text": "主公,您为什么不给他呢?",
        "edit": "拱手向前,神情从容",
        "say": "谋士拱手向前,从容发问",
    },
    {
        "id": "S04",
        "sp": "weihuanzi",
        "lead": "weihuanzi",
        "text": "他无缘无故就来要地,所以我不给。",
        "edit": "神色持重",
        "say": "宗主神色持重地作答",
    },
    {
        "id": "S05",
        "sp": "renzhang",
        "lead": "renzhang",
        "text": "他无缘无故索取土地,邻国都会心生恐惧;他这样贪得无厌,天下都会忌惮他。",
        "edit": "一手微抬示意,从容进言",
        "say": "谋士从容进言,一手微抬示意",
    },
    {
        "id": "S06",
        "sp": "renzhang",
        "lead": "renzhang",
        "text": "您把地给了他,他必定越发骄狂、轻视对手;而邻国因为害怕,反倒会联合起来。",
        "edit": "侃侃而谈,神情笃定",
        "say": "谋士侃侃而谈,神情笃定",
    },
    {
        "id": "S07",
        "sp": "renzhang",
        "lead": "renzhang",
        "text": "用同仇敌忾的军队,去对付一个骄狂轻敌的智伯,他的死期也就不远了。",
        "edit": "身体微微前倾,神情锐利自信",
        "say": "谋士身体微微前倾,神情锐利自信",
    },
    {
        "id": "S08",
        "sp": "renzhang",
        "lead": "renzhang",
        "text": "《周书》上说:想要夺取它,必先给予它。",
        "edit": "一手抬起引经据典",
        "say": "谋士抬手引经据典",
    },
    {
        "id": "S09",
        "sp": "renzhang",
        "lead": "renzhang",
        "text": "您何必舍不得这一块地,偏偏让魏国单独去做智伯的靶子呢?",
        "edit": "拱手反问,神情恳切",
        "say": "谋士拱手恳切反问",
    },
    {
        "id": "S10",
        "sp": "weihuanzi",
        "lead": "weihuanzi",
        "text": "好!就依你。",
        "edit": "颔首,神色释然决断",
        "say": "宗主颔首,神色释然决断",
    },
    {
        "id": "S11",
        "sp": "NARRATOR",
        "lead": "zhibo",
        "text": "于是,魏桓子把一座上万户的大城,拱手送给了智伯。智伯果然大喜过望。",
        "edit": "仰头得意大笑,须髯上扬",
        "motion": "人物仰头得意大笑,须髯扬动",
    },
    {
        "id": "S12",
        "sp": "NARRATOR",
        "lead": "zhibo",
        "text": "尝到甜头的智伯越发骄横,又跑去向赵襄子要地。这一回,赵襄子一口回绝。",
        "edit": "挥手怒指,神情暴怒",
        "motion": "人物挥手怒指,神情暴怒,须髯衣袖抖动,闭着嘴",
    },
    {
        "id": "S13",
        "sp": "NARRATOR",
        "lead": None,
        "text": "恼羞成怒的智伯,胁迫韩、魏两家出兵,把赵襄子团团围困在晋阳城。",
        "scene": "国画水墨写意战争场面,战国时代千军万马围攻一座高大城池,城门匾额上清晰写着"
        "“晋阳”两个大字,军中大旗上写着“智”字,城墙下大水漫涌,烟尘弥漫,气势磅礴,"
        "单色水墨,写意笔触,宣纸质感",
        "neg": "秦字,秦国,旗帜上的秦字,现代文字,乱码",
        "motion": "旌旗招展,大军压城,烟尘与水势翻涌",
    },
    {
        "id": "S14",
        "sp": "NARRATOR",
        "lead": None,
        "text": "可就在城池即将攻破的时候,韩、魏两家临阵倒戈,和城里的赵氏里应外合。",
        "scene": "国画水墨写意战争场面,战国时代两军阵前倒戈相攻,混战一片,写着“韩”“魏”字样的"
        "军旗调转,一面写着“智”字的大旗轰然倾倒,烟尘弥漫,战马奔腾,单色水墨,写意笔触,宣纸质感",
        "neg": "秦字,秦国,旗帜上的秦字,现代文字,乱码",
        "motion": "战阵倒戈,大旗倾覆,烟尘弥漫",
    },
    {
        "id": "S15",
        "sp": "NARRATOR",
        "lead": "zhibo",
        "text": "不可一世的智伯,顷刻间土崩瓦解。贪婪和傲慢,终究把他自己,送上了绝路。",
        "edit": "神色黯然颓丧,笼罩在浓重的烟墨阴影里",
        "motion": "人物神色黯然,烟墨渐散,闭着嘴",
    },
]


def _ffprobe_dur(p: Path) -> float:
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
        check=True,
    ).stdout.strip()
    return float(out)


def _say_dur(text: str) -> int:
    """按中文字数估 happyhorse 时长(秒),clamp 到官方允许的 3~15s。"""
    return max(3, min(15, round(len(text) * 0.32) + 1))


async def _canonical(cid: str, desc: str, seed: int = 42) -> Path:
    out = _WORK / f"canon_{cid}.png"
    if not out.exists():
        logger.info("生成 canonical: %s", cid)
        await qwen_image_generate(prompt=desc, output_path=out, size="1280*720", seed=seed)
    return out


async def _keyframe(shot: dict) -> Path:
    frame = _WORK / f"{shot['id']}.png"
    if frame.exists():
        return frame
    if shot["lead"]:
        canon = await _canonical(shot["lead"], _CHAR_DESC[shot["lead"]])
        await qwen_image_edit(
            image_path=canon, instruction=_EDIT_PREFIX + shot["edit"], output_path=frame
        )
    else:
        await qwen_image_generate(
            prompt=shot["scene"],
            output_path=frame,
            size="1280*720",
            negative_prompt=shot.get("neg", ""),
        )
    return frame


def _fit_dialogue(clip: Path, out: Path) -> float:
    """对白镜头:happyhorse 片自带配音+口型,**保留其音轨**;只做尺寸规整 + zoompan 缓推。"""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(clip),
            "-filter_complex",
            "[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,"
            "zoompan=z='min(zoom+0.0004,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            "s=1280x720:fps=24[v]",
            "-map",
            "[v]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return _ffprobe_dur(out)


def _fit_narration(visual: Path, audio: Path, out: Path) -> float:
    """旁白镜头:画面(i2v 或战争空镜,无关音轨)循环填满旁白音轨时长 + zoompan;挂旁白音轨。"""
    hold = _ffprobe_dur(audio) + 0.4
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(visual),
            "-i",
            str(audio),
            "-filter_complex",
            f"[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
            f"trim=0:{hold:.3f},setpts=PTS-STARTPTS,fps=24,"
            f"zoompan=z='min(zoom+0.0004,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s=1280x720:fps=24[v]",
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            f"{hold:.3f}",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return hold


def _xfade_concat(clips: list[tuple[Path, float]], out: Path, crossfade: float = 0.5) -> None:
    inputs: list[str] = []
    for p, _ in clips:
        inputs += ["-i", str(p)]
    n = len(clips)
    if n == 1:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                *inputs,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        return
    vf, af = [], []
    prev_v, prev_a = "[0:v]", "[0:a]"
    cum = clips[0][1]
    for i in range(1, n):
        off = max(cum - crossfade, 0.0)
        vout = f"[v{i}]" if i < n - 1 else "[vout]"
        aout = f"[a{i}]" if i < n - 1 else "[aout]"
        vf.append(
            f"{prev_v}[{i}:v]xfade=transition=fade:duration={crossfade}:offset={off:.3f}{vout}"
        )
        af.append(f"{prev_a}[{i}:a]acrossfade=d={crossfade}{aout}")
        prev_v, prev_a = vout, aout
        cum = cum + clips[i][1] - crossfade
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(vf + af),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


async def main() -> None:
    _WORK.mkdir(parents=True, exist_ok=True)
    narrator_ref = await _canonical(
        "narrator",
        "国画水墨写意人物画,一位年长儒雅的说书人史官,须发斑白,身着素色长袍,面容睿智平和,"
        "正襟危坐,近景半身像,身后淡淡书卷与薄雾,单色水墨,写意笔触,宣纸质感",
        seed=7,
    )

    shot_clips: list[tuple[Path, float]] = []
    for shot in _SHOTS:
        sid = shot["id"]
        is_dialogue = shot["sp"] != "NARRATOR"
        logger.info("=== %s (%s) ===", sid, "对白" if is_dialogue else "旁白")
        frame = await _keyframe(shot)
        dur = _say_dur(shot["text"])

        fitted = _WORK / f"{sid}_fit.mp4"
        if is_dialogue:
            # 对白:happyhorse 让角色说自己的台词(自带配音+口型),直接用。
            talk = _WORK / f"{sid}_talk.mp4"
            if not talk.exists():
                logger.info("[%s] happyhorse 说台词...", sid)
                await happyhorse_animate(
                    image_path=frame,
                    prompt=f"国画水墨写意画风,单色水墨,保持画风不变,画中{shot['say']},"
                    f'郑重说道:"{shot["text"]}",嘴巴随说话自然清晰地张合',
                    output_path=talk,
                    duration=dur,
                )
            hold = _fit_dialogue(talk, fitted)
        else:
            # 旁白:happyhorse(史官)出音轨 + i2v/战争画面(人物闭嘴)。
            narr = _WORK / f"{sid}_narr.mp4"
            if not narr.exists():
                logger.info("[%s] happyhorse 史官旁白音轨...", sid)
                await happyhorse_animate(
                    image_path=narrator_ref,
                    prompt=f'国画水墨画风,一位史官说书人沉稳讲述:"{shot["text"]}"',
                    output_path=narr,
                    duration=dur,
                )
            narr_audio = _WORK / f"{sid}_narr.aac"
            if not narr_audio.exists():
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(narr), "-vn", "-acodec", "copy", str(narr_audio)],
                    check=True,
                    capture_output=True,
                )
            vis = _WORK / f"{sid}_vis.mp4"
            if not vis.exists():
                logger.info("[%s] i2v 画面(闭嘴/空镜)...", sid)
                await i2v_animate(
                    image_path=frame,
                    prompt=f"水墨画风保持不变,{shot['motion']}",
                    output_path=vis,
                )
            hold = _fit_narration(vis, narr_audio, fitted)

        shot_clips.append((fitted, hold))
        logger.info("[%s] 完成 hold=%.1fs", sid, hold)

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _xfade_concat(shot_clips, _OUTPUT, crossfade=0.5)
    total = _ffprobe_dur(_OUTPUT)
    logger.info("完成 → %s (%.1fs)", _OUTPUT, total)
    print(f"\n✓ 输出: {_OUTPUT}  时长 {total:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())

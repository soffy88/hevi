"""INC-003 生产验收:一个双人**对话**镜头,走真实生产管线(`build_frame_manifest_avatar`,
不是探路脚本手搭的调用序列)从④分镜→⑤生成出片。真花钱(happyhorse 1 次调用),只跑这一个
镜头,不跑一集。

复用 G-S1/INC-003 探路已建的真实资产(王生/老道 canon + Subject3D front 视图 + 客栈空景板),
不重新生成——省时省钱,且前三条断言本来就是拿这批资产在静图上证过的,这次只买④⑤的信息。

五条断言(①②③静图已证,这次复核;④⑤是这次真正买的信息):
  ① 身份间距正:左半 vs 对应 canon 的分,减去左半 vs 交叉 canon 的分(看间距不看绝对值)
  ② 落位对:王生画左、老道画右(合成底图确定性保证,产出后肉眼复核)
  ③ 场景融合:肉眼看关键帧,两人是否像同处一室
  ④ 口型落在说话人(王生)脸上:抽帧肉眼看
  ⑤ 老道不动嘴:抽帧肉眼看

失败分类(供判读用,不在代码里编码):
  - 口型落错脸(动的是老道)→ happyhorse 不认多人图里谁是谁,需要换路(如单人参考图 + 事后合成)
  - 口型糊但位置大致对 → 参数问题(prompt/清晰度),不是路径问题
  - 两人都不怎么动嘴/都在动 → 模型不知道谁在说话,需要额外条件(如遮住另一人嘴部/更明确 prompt)

用法:python scripts/inc003_prod_accept_e2e.py   (需 GPU;happyhorse 走 ALIBABA_MAAS,真实计费)
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # 独立脚本(非 API 进程)不会自动加载 .env——qwen_image_service._creds 直读
# os.getenv,不经过 pydantic Settings,漏这一步云端凭证读不到(INC-003 探路脚本同款坑)。

import asyncio
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inc003_accept")

_GS1 = Path("output/gs1_scene_stage")
_WS_FRONT = Path("output/gs1_3dtest/front.png")
_LD_FRONT = Path("output/incr003_laodao_3d/front.png")
_BG = Path("output/incr003_scene_facing/inn_bg.png")
_OUT = Path("output/inc003_prod_accept_v2_style")  # 新目录:换 style 复测,别复用旧 run 缓存的
# kf.png/clip.mp4(build_frame_manifest_avatar 靠文件存在即跳过重生成,同目录会读到上一轮的图)。
_OUT.mkdir(parents=True, exist_ok=True)


def _score(a: Path, b: Path) -> float | None:
    from contextlib import suppress

    from hevi.subjects.subject_embed import cosine_similarity, subject_embed

    with suppress(Exception):
        return cosine_similarity(
            subject_embed(image_path=a, kind="style"), subject_embed(image_path=b, kind="style")
        )
    return None


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


def _extract_frame(clip: Path, t: float, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1", str(out)],
        check=True,
        capture_output=True,
    )


async def main() -> None:
    from hevi.providers.registry import register_all_providers

    register_all_providers()

    for p in (_GS1 / "canon_王生.png", _GS1 / "canon_老道.png", _WS_FRONT, _LD_FRONT, _BG):
        assert p.exists(), f"缺资产,先跑对应探路脚本产出:{p}"

    from hevi.tongjian.scene_render_avatar import build_frame_manifest_avatar
    from hevi.tongjian.schemas import (
        CharacterBible,
        CharacterBibleEntry,
        Constitution,
        LayerConfig,
        Script,
        ScriptLine,
        Shot,
        ShotList,
    )

    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="王生",
                text="道长,此地为何如此冷清?",
                emotion="疑惑",
                target="老道",
                visual_hint="拱手问询",
            )
        ]
    )
    shot = Shot(
        shot_id="SH001",
        line_ids=["LN001"],
        characters=["王生", "老道"],
        scene_id="客栈",
        blocking=["王生:左侧,面向老道", "老道:右侧,面向王生"],
    )
    shotlist = ShotList(shots=[shot])
    bible = CharacterBible(
        characters=[
            CharacterBibleEntry(
                character_id="王生",
                name="王生",
                appearance="年轻书生,面容清秀,无须,黑色发髻,蓝色书生袍",
                ref_image=str(_GS1 / "canon_王生.png"),
            ),
            CharacterBibleEntry(
                character_id="老道",
                name="老道",
                appearance="年迈道士,白须飘飘,白发发髻,灰色道袍",
                ref_image=str(_GS1 / "canon_老道.png"),
            ),
        ]
    )

    manifest = await build_frame_manifest_avatar(
        shotlist,
        script,
        bible,
        Constitution(),
        run_dir=_OUT,
        config=LayerConfig(
            model="cloud_avatar",
            params={
                # 复测:第一轮没传 style,落到 scene_render_avatar._DEFAULT_STYLE(卡通,通鉴
                # 纯讲解路的兜底),跟这场古装客栈戏的资产口径(_ART_DIRECTION/_SCENE_PLATE_
                # DIRECTION 的"写实历史正剧")不一致——③场景融合没复现探路效果的疑似根因。
                # 这里改传与③锁资产一致的写实历史正剧措辞,strength 仍是代码里定死的 0.55,
                # 不动,只变这一个变量。
                "style": "写实历史正剧质感,电影感摄影,自然光效,浅景深,写实质感",
                "keyframe_engine": "local",
                "subject3d_views_by_id": {
                    "王生": {"front": str(_WS_FRONT)},
                    "老道": {"front": str(_LD_FRONT)},
                },
                "scene_bg_by_id": {"客栈": str(_BG)},
            },
        ),
    )

    frame = manifest.frames[0]
    log.info("clip_path=%s debug_context=%s", frame.clip_path, frame.debug_context)
    assert frame.clip_path, "没产出 clip——生产管线在这一镜上失败了,先看日志"
    clip = Path(frame.clip_path)
    kf = _OUT / "SH001_kf.png"
    assert kf.exists() and clip.exists()

    # ── ① 身份间距 ──────────────────────────────────────────────────────────
    from PIL import Image

    img = Image.open(kf).convert("RGB")
    W, H = img.size
    left, right = _OUT / "kf_left.png", _OUT / "kf_right.png"
    img.crop((0, 0, W // 2, H)).save(left)
    img.crop((W // 2, 0, W, H)).save(right)
    id_ws = _score(left, _GS1 / "canon_王生.png")
    id_ld = _score(right, _GS1 / "canon_老道.png")
    cross_l = _score(left, _GS1 / "canon_老道.png")
    cross_r = _score(right, _GS1 / "canon_王生.png")
    gap_l = (id_ws - cross_l) if (id_ws is not None and cross_l is not None) else None
    gap_r = (id_ld - cross_r) if (id_ld is not None and cross_r is not None) else None

    # ── ④⑤ 抽帧(始/近1/3/近2/3/末)看口型 ───────────────────────────────────
    frames_dir = _OUT / "clip_frames"
    frames_dir.mkdir(exist_ok=True)
    dur = _ffprobe_dur(clip)
    frame_paths = []
    for i, t in enumerate([0.15, dur * 0.35, dur * 0.6, max(0.1, dur - 0.2)]):
        out = frames_dir / f"f{i}_{t:.2f}s.png"
        _extract_frame(clip, t, out)
        frame_paths.append(out)

    print("\n" + "=" * 68)
    print("INC-003 生产验收:双人对话镜头,真实生产管线出片")
    print("=" * 68)
    print(f"关键帧:{kf}")
    print(f"clip:  {clip}  (时长 {dur:.2f}s)")
    print(f"抽帧:  {', '.join(str(p) for p in frame_paths)}")
    print("-" * 68)
    print("【①身份间距(看间距不看绝对值)】")
    print(f"  左半(应像王生) id={id_ws} cross(老道)={cross_l} gap={gap_l}")
    print(f"  右半(应像老道) id={id_ld} cross(王生)={cross_r} gap={gap_r}")
    print(
        f"【②落位】王生应在左半、老道应在右半(合成底图确定性保证);"
        f"layout_base={frame.debug_context.get('layout_base')}"
    )
    print(f"【③场景融合】肉眼看 {kf}:两人是否像同处一室(暖光/地面/透视一致)")
    print(f"【④口型落在说话人(王生)脸上】肉眼看 {frames_dir}/*.png:左边(王生)嘴是否随时间张合")
    print(f"【⑤老道不动嘴】肉眼看同一批帧:右边(老道)嘴是否全程基本不动")
    print("=" * 68)


if __name__ == "__main__":
    asyncio.run(main())

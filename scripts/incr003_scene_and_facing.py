"""INC-003 两个单变量后续实验(都零训练、走现有 sdxl 路,从 run3 正面基线出发)。

run3 基线(scripts/incr003_multichar_composite_verify.py):正面视图 + 纯灰底 →
  王生 0.790 / 老道 0.850,无渗透,但"两人像贴上去的"(纯灰底 + 浮动半身像 + 中间留空)。

① 场景融合:只改底图构造 —— 真实客栈内景背景 + 两人靠近下移有地面重叠 + prompt 统一光照。
   变量=底图。问:能不能从"并排肖像"变成"同处一室"?身份掉多少?
② 对视:只把正面视图换成侧脸(王生 right.png 面朝右、老道 left.png 面朝左,互相看)。
   变量=朝向。问:一张脸变侧脸后身份分还剩多少?→ 决定 compose 路能不能做对话戏。

用法:python scripts/incr003_scene_and_facing.py   (需 GPU;老道/王生视图已建)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from PIL import Image

from hevi.image.sdxl_local_service import sdxl_local_generate
from hevi.tongjian.scene_render_avatar import _edit_keyframe, _knockout_near_white, _local_kf_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("incr003_2")

_GS1 = Path("output/gs1_scene_stage")
_WS_VIEWS = Path("output/gs1_3dtest")
_LD_VIEWS = Path("output/incr003_laodao_3d")
_OUT = Path("output/incr003_scene_facing")
_OUT.mkdir(parents=True, exist_ok=True)

_STYLE = (
    "cinematic photorealistic, ancient Chinese costume drama, natural light, shallow depth of field"
)
_WS_EN = (
    "a young Chinese male scholar in his early 20s, handsome clean face, no beard, "
    "black hair topknot, blue traditional scholar robe"
)
_LD_EN = (
    "an elderly Chinese Taoist priest, very long flowing white beard, white hair topknot, "
    "wrinkled wise face, gray traditional Taoist robe"
)


def _score(frame: Path, canon: Path) -> float | None:
    from hevi.subjects.subject_embed import cosine_similarity, subject_embed

    with suppress(Exception):
        return cosine_similarity(
            subject_embed(image_path=frame, kind="style"),
            subject_embed(image_path=canon, kind="style"),
        )
    return None


async def _ask_vlm(prompt: str, image: Path) -> str:
    from obase.provider_registry import ProviderRegistry

    try:
        vlm = ProviderRegistry.get().vlm("default")
        resp = await vlm(
            messages=[{"role": "user", "content": prompt}], image_paths=[str(image)], max_tokens=80
        )
        return str((resp.get("content") if hasattr(resp, "get") else resp) or "").strip()
    except Exception as e:
        log.warning("VLM 失败: %s", e)
        return ""


def _paste_figure(bg: Image.Image, view: Path, cx: float, h_frac: float) -> None:
    """把一张 Subject3D 视图(近白底)抠图后贴到 bg 上:水平中心 cx(0..1)、目标高 h_frac*画布高、
    脚底贴底(有地面重叠)。"""
    fig = _knockout_near_white(Image.open(view))
    W, H = bg.size
    scale = (H * h_frac) / fig.height
    fig = fig.resize((max(1, int(fig.width * scale)), int(H * h_frac)))
    x = int(cx * W - fig.width / 2)
    y = H - fig.height
    bg.paste(fig, (x, y), fig)


async def _twoshot(
    *,
    tag: str,
    view_ws: Path,
    view_ld: Path,
    bg_path: Path | None,
    strength: float,
    extra_prompt: str,
) -> tuple[float | None, float | None, float | None, float | None]:
    """建底图 → 贴两人 → img2img → 返回(左vs王生, 右vs老道, 交叉左vs老, 交叉右vs王)。"""
    w, h = 1280, 720
    base = (
        Image.open(bg_path).convert("RGB").resize((w, h))
        if bg_path
        else Image.new("RGB", (w, h), (128, 128, 128))
    )
    # 两人靠近(0.36/0.64 而非 run3 的 0.22/0.78)、下移有地面重叠(0.78 高的半身)
    _paste_figure(base, view_ws, 0.36, 0.78)
    _paste_figure(base, view_ld, 0.64, 0.78)
    layout = _OUT / f"{tag}_layout.png"
    base.save(layout)

    prompt = _local_kf_prompt(
        _STYLE,
        f"two people together in one frame, on the left {_WS_EN}, on the right {_LD_EN}. "
        + extra_prompt,
        "natural expression",
        "",
    )
    result = _OUT / f"{tag}_twoshot.png"
    src = await _edit_keyframe(
        image_path=_GS1 / "canon_王生.png",
        instruction="two people",
        output_path=result,
        fallback_from=_GS1 / "canon_王生.png",
        engine="local",
        local_prompt=prompt,
        init_image=layout,
        init_strength=strength,
        size=(w, h),
    )
    log.info("[%s] img2img %s → %s", tag, src, result)
    img = Image.open(result).convert("RGB")
    W, H = img.size
    lh, rh = _OUT / f"{tag}_left.png", _OUT / f"{tag}_right.png"
    img.crop((0, 0, W // 2, H)).save(lh)
    img.crop((W // 2, 0, W, H)).save(rh)
    return (
        _score(lh, _GS1 / "canon_王生.png"),
        _score(rh, _GS1 / "canon_老道.png"),
        _score(lh, _GS1 / "canon_老道.png"),
        _score(rh, _GS1 / "canon_王生.png"),
    )


async def main() -> None:
    from hevi.providers.registry import register_all_providers

    register_all_providers()

    # ── ① 场景融合:先 txt2img 生一张客栈内景当底图 ──────────────────────────────
    bg = _OUT / "inn_bg.png"
    if not bg.exists():
        log.info("生成客栈内景背景(txt2img)...")
        await sdxl_local_generate(
            prompt="interior of an ancient Chinese inn, wooden tables and benches, hanging "
            "lanterns, warm evening light from the left, empty room, wide establishing shot, "
            "photorealistic, cinematic",
            output_path=bg,
            width=1280,
            height=720,
            require_gpu=True,
        )

    log.info("=== ① 场景融合(真实背景 + 靠近下移 + 统一光照,正面视图)===")
    s1 = await _twoshot(
        tag="scene",
        view_ws=_WS_VIEWS / "front.png",
        view_ld=_LD_VIEWS / "front.png",
        bg_path=bg,
        strength=0.6,
        extra_prompt="both standing close together inside the same warm-lit inn, warm lantern "
        "light from the left casting consistent shadows, same floor, same perspective, "
        "cinematic two-shot",
    )
    v1_left_beard = await _ask_vlm(
        "只看画面左边的人,他有没有留长胡子?只答'有'或'无'加不超过8字。", _OUT / "scene_twoshot.png"
    )
    v1_same = await _ask_vlm(
        "这张图里的两个人,看起来像在同一个真实房间里(共享地面/光照/透视)吗?还是像两张照片拼贴?"
        "只答'同一空间'或'拼贴'加不超过15字。",
        _OUT / "scene_twoshot.png",
    )

    log.info("=== ② 对视(侧脸视图:王生 right 面朝右、老道 left 面朝左,纯灰底同 run3)===")
    s2 = await _twoshot(
        tag="facing",
        view_ws=_WS_VIEWS / "right.png",
        view_ld=_LD_VIEWS / "left.png",
        bg_path=None,
        strength=0.65,
        extra_prompt="the two face each other in profile, natural conversation",
    )
    v2_left_beard = await _ask_vlm(
        "只看画面左边的人,他有没有留长胡子?只答'有'或'无'加不超过8字。", _OUT / "facing_twoshot.png"
    )

    print("\n" + "=" * 68)
    print("INC-003 后续实验:① 场景融合  ② 对视")
    print("=" * 68)
    print("基线(run3 正面+纯灰底):王生 0.790 / 老道 0.850,无渗透,但贴上去感")
    print("-" * 68)
    print("① 场景融合(真实客栈底图 + 靠近下移 + 统一光照,正面):")
    print(f"   左半 vs 王生: {s1[0]}   (交叉 左vs老: {s1[2]})")
    print(f"   右半 vs 老道: {s1[1]}   (交叉 右vs王: {s1[3]})")
    print(f"   VLM 左边有胡子吗:{v1_left_beard!r}  (期望 无)")
    print(f"   VLM 像同一空间还是拼贴:{v1_same!r}")
    print(f"   → 看图 {_OUT}/scene_twoshot.png(拼接痕迹是否改善)")
    print("-" * 68)
    print("② 对视(侧脸:王生 right / 老道 left,互相看):")
    print(f"   左半 vs 王生: {s2[0]}   (交叉 左vs老: {s2[2]})   [正面基线 0.790]")
    print(f"   右半 vs 老道: {s2[1]}   (交叉 右vs王: {s2[3]})   [正面基线 0.850]")
    print(f"   VLM 左边有胡子吗:{v2_left_beard!r}  (期望 无)")
    print("   → 侧脸掉了多少身份分 = compose 路能否做对话戏的判据")
    print("=" * 68)


if __name__ == "__main__":
    asyncio.run(main())

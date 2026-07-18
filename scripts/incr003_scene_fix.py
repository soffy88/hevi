"""INC-003 (a):修①的姿势失控 —— 场景融合图里老道在 strength 0.6 下自己转了身,污染他那格
身份数。这里只降 strength(0.5/0.55 两档对比,其余全同),看老道能否保持正面、身份回升、场景
仍融合。复用已生成的客栈底图。

用法:python scripts/incr003_scene_fix.py   (需 GPU)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from PIL import Image

from hevi.tongjian.scene_render_avatar import _edit_keyframe, _knockout_near_white, _local_kf_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("incr003_fix")

_GS1 = Path("output/gs1_scene_stage")
_WS_VIEWS = Path("output/gs1_3dtest")
_LD_VIEWS = Path("output/incr003_laodao_3d")
_OUT = Path("output/incr003_scene_facing")
_BG = _OUT / "inn_bg.png"

_STYLE = (
    "cinematic photorealistic, ancient Chinese costume drama, natural light, shallow depth of field"
)
_WS_EN = (
    "a young Chinese male scholar in his early 20s, handsome clean face, no beard, "
    "black hair topknot, blue traditional scholar robe"
)
_LD_EN = (
    "an elderly Chinese Taoist priest, very long flowing white beard, white hair topknot, "
    "wrinkled wise face, gray traditional Taoist robe, facing forward toward the camera"
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
    except Exception as e:  # noqa: BLE001
        log.warning("VLM 失败: %s", e)
        return ""


def _paste(bg: Image.Image, view: Path, cx: float, h_frac: float) -> None:
    fig = _knockout_near_white(Image.open(view))
    W, H = bg.size
    scale = (H * h_frac) / fig.height
    fig = fig.resize((max(1, int(fig.width * scale)), int(H * h_frac)))
    bg.paste(fig, (int(cx * W - fig.width / 2), H - fig.height), fig)


async def _run(strength: float) -> None:
    w, h = 1280, 720
    base = Image.open(_BG).convert("RGB").resize((w, h))
    _paste(base, _WS_VIEWS / "front.png", 0.36, 0.78)
    _paste(base, _LD_VIEWS / "front.png", 0.64, 0.78)
    tag = f"scenefix_s{int(strength * 100)}"
    layout = _OUT / f"{tag}_layout.png"
    base.save(layout)

    prompt = _local_kf_prompt(
        _STYLE,
        f"two people together in one frame, on the left {_WS_EN}, on the right {_LD_EN}. "
        "both standing close together facing the camera inside the same warm-lit inn, "
        "warm lantern light from the left casting consistent shadows, same floor, same "
        "perspective, cinematic two-shot",
        "natural expression",
        "",
    )
    result = _OUT / f"{tag}_twoshot.png"
    await _edit_keyframe(
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
    img = Image.open(result).convert("RGB")
    W, H = img.size
    lh, rh = _OUT / f"{tag}_left.png", _OUT / f"{tag}_right.png"
    img.crop((0, 0, W // 2, H)).save(lh)
    img.crop((W // 2, 0, W, H)).save(rh)
    id_ws = _score(lh, _GS1 / "canon_王生.png")
    id_ld = _score(rh, _GS1 / "canon_老道.png")
    cross_ld = _score(lh, _GS1 / "canon_老道.png")
    cross_ws = _score(rh, _GS1 / "canon_王生.png")
    beard_r = await _ask_vlm(
        "只看画面右边的人,他有没有留长胡子?只答'有'或'无'加不超过8字。", result
    )
    facing_r = await _ask_vlm(
        "画面右边的人是面朝镜头(看得见脸)还是背对镜头(看不见脸)?只答'正面'或'背面'。", result
    )
    print(f"\n--- strength {strength} → {result.name} ---")
    print(f"  左半 vs 王生: {id_ws}   (交叉 左vs老 {cross_ld})")
    print(f"  右半 vs 老道: {id_ld}   (交叉 右vs王 {cross_ws})   [0.6 时 0.736]")
    print(f"  VLM 右边有胡子:{beard_r!r}   右边朝向:{facing_r!r}   (要 正面+有须 才算老道没转身)")


async def main() -> None:
    from hevi.providers.registry import register_all_providers

    register_all_providers()
    assert _BG.exists(), "缺客栈底图,先跑 incr003_scene_and_facing.py 生成 inn_bg.png"
    for s in (0.5, 0.55):
        await _run(s)
    print("\n看图对比:scenefix_s50_twoshot.png vs scenefix_s55_twoshot.png vs 原 scene_twoshot.png")


if __name__ == "__main__":
    asyncio.run(main())

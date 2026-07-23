"""INC-003 前置验证:多角色走位合成底图 → img2img → 双人同框(零训练、零 GPU 增量)。

走**现有生产函数**:_compose_layout_base(走位拼底图)+ _edit_keyframe(img2img 路)。
不碰 LoRA。用 G-S1 已建的王生/老道 canon(身份已正确)+ 一个 SceneStage(王生画左、
老道画右)。

四条断言(前两条程序化,后两条 VLM/肉眼):
  1. 身份分:结果左半 vs 王生 canon、右半 vs 老道 canon,各 >= 0.70
  2. 落位:王生在画左、老道在画右(靠合成底图确定性保证,VLM 复核)
  3. 渗透:VLM 极简问"画面左边的人有没有胡子"(王生青年无须;若有=老道渗透)
  4. 拼接痕迹:肉眼看两人是否像同一空间(输出图,人工判)

用法:python scripts/incr003_multichar_composite_verify.py   (需 GPU + TripoSR venv)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PIL import Image

from hevi.subjects.subject3d_local import generate_subject3d
from hevi.tongjian.scene_render_avatar import _compose_layout_base, _edit_keyframe, _local_kf_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("incr003")

_GS1 = Path("output/gs1_scene_stage")
_WS_VIEWS = Path("output/gs1_3dtest")  # 王生 4 视图(B4 已产)
_LD_VIEWS = Path("output/incr003_laodao_3d")  # 老道 4 视图(本脚本按需产)
_OUT = Path("output/incr003_multichar")
_OUT.mkdir(parents=True, exist_ok=True)

# 英文 prompt:base SDXL 对中文老者/道士渲成通用少女(gs1 首跑教训),英文对年龄/性别/胡须
# 控制好得多。**且绕开 qwen_cloud 翻译**——独立脚本没加载 .env,翻译漏斗失败会让中文原样进
# SDXL 渲染跑偏(production 里 .env 在、翻译正常,这是 harness artifact,不是方法问题)。
_STYLE = (
    "cinematic photorealistic, ancient Chinese costume drama, natural light, shallow depth of field"
)
_APPEAR = {
    "王生": "a young Chinese male scholar in his early 20s, handsome clean face, no beard, "
    "black hair topknot, blue traditional scholar robe",
    "老道": "an elderly Chinese Taoist priest, very long flowing white beard, white hair topknot, "
    "wrinkled wise face, gray traditional Taoist robe",
}


def _score(frame: Path, canon: Path) -> float | None:
    from contextlib import suppress

    from hevi.subjects.subject_embed import cosine_similarity, subject_embed

    with suppress(Exception):
        return cosine_similarity(
            subject_embed(image_path=frame, kind="style"),
            subject_embed(image_path=canon, kind="style"),
        )
    log.warning("打分失败 %s", frame.name)
    return None


async def _ask_vlm(prompt: str, image: Path) -> str:
    from obase.provider_registry import ProviderRegistry

    try:
        vlm = ProviderRegistry.get().vlm("default")
        resp = await vlm(
            messages=[{"role": "user", "content": prompt}],
            image_paths=[str(image)],
            max_tokens=80,
        )
        return str((resp.get("content") if hasattr(resp, "get") else resp) or "").strip()
    except Exception as e:
        log.warning("VLM 失败,跳过: %s", e)
        return ""


async def main() -> None:
    # 注册 provider(独立脚本不走 API 启动的 bootstrap):qwen_cloud 负责 sdxl prompt 中→英翻译
    # (缺它 base SDXL 拿中文渲染跑偏),vlm/default(本地 qwen2.5vl)负责渗透测。
    from hevi.providers.registry import register_all_providers

    register_all_providers()

    canon_ws = _GS1 / "canon_王生.png"
    canon_ld = _GS1 / "canon_老道.png"
    assert canon_ws.exists() and canon_ld.exists(), "缺 G-S1 canon,先跑 gs1_scene_stage_run.py"

    # 老道 Subject3D 视图:按需生成(CPU,零 GPU;王生视图 B4 已产)
    if not (_LD_VIEWS / "left.png").exists():
        log.info("老道 Subject3D 视图不存在,TripoSR 现生成(CPU,~3min)...")
        await generate_subject3d(canon_ld, output_dir=_LD_VIEWS)
    log.info("视图就绪:王生=%s 老道=%s", _WS_VIEWS, _LD_VIEWS)

    # 用 **front 视图**:侧/背视图会把脸藏了(首跑老道 left.png 是背身→身份/胡子根本没法测)。
    # 先用正面把"两个身份能否共存一帧"测清楚,朝向对视是后续细化。
    view_ws = _WS_VIEWS / "front.png"
    view_ld = _LD_VIEWS / "front.png"

    w, h = 1280, 720
    # 现有生产函数:走位拼底图(王生"左侧"、老道"右侧")
    layout = _compose_layout_base(
        present=["王生", "老道"],
        view_path_by_cid={"王生": view_ws, "老道": view_ld},
        pos_desc_by_cid={"王生": "左侧", "老道": "右侧"},
        size=(w, h),
        out_path=_OUT / "layout_base.png",
    )
    assert layout is not None, "合成底图失败(应 ≥2 视图)"
    log.info("走位底图:%s", layout)

    # 现有生产函数:img2img 从底图起(engine=local → sdxl img2img)。全英文 prompt,绕开翻译。
    local_prompt = _local_kf_prompt(
        _STYLE,
        f"two people in one frame: on the left, {_APPEAR['王生']}; "
        f"on the right, {_APPEAR['老道']}; both standing inside the same ancient inn, "
        "facing each other, natural conversation, same lighting and perspective",
        "natural expression",
        "",
        wide=True,
    )
    result = _OUT / "twoshot.png"
    src = await _edit_keyframe(
        image_path=canon_ws,  # 云端兜底才用;local 路走 init_image
        instruction="两人同框",
        output_path=result,
        fallback_from=canon_ws,
        engine="local",
        local_prompt=local_prompt,
        init_image=layout,
        # 0.65:底图是 TripoSR 卡通半身像,strength 太低跳不出卡通;够高才能重绘成写实,同时保留
        # 底图的走位锚(太高会连位置一起丢)。
        init_strength=0.65,
        size=(w, h),
    )
    log.info("img2img 引擎路:%s → %s", src, result)
    assert result.exists()

    # ── 断言 1:身份分(左半 vs 王生、右半 vs 老道)──────────────────────────────
    img = Image.open(result).convert("RGB")
    W, H = img.size
    left_half = _OUT / "twoshot_left.png"
    right_half = _OUT / "twoshot_right.png"
    img.crop((0, 0, W // 2, H)).save(left_half)
    img.crop((W // 2, 0, W, H)).save(right_half)
    id_ws = _score(left_half, canon_ws)  # 左半应像王生
    id_ld = _score(right_half, canon_ld)  # 右半应像老道
    # 交叉:左半 vs 老道(应更低),用来判渗透方向
    cross_ws_ld = _score(left_half, canon_ld)
    cross_ld_ws = _score(right_half, canon_ws)

    # ── 断言 3:渗透(VLM 极简问法)────────────────────────────────────────────
    q_left_beard = await _ask_vlm(
        "只看这张图**画面左边**的那个人。他有没有留长胡子?只回答'有'或'无',再加不超过10字说明。",
        result,
    )
    q_right_beard = await _ask_vlm(
        "只看这张图**画面右边**的那个人。他有没有留长胡子?只回答'有'或'无',再加不超过10字说明。",
        result,
    )
    q_left_hair = await _ask_vlm(
        "只看这张图**画面左边**那个人的头发颜色,一个词回答(黑/白/灰/其他)。", result
    )

    print("\n" + "=" * 64)
    print("INC-003 多角色走位合成底图 → img2img 验证结果")
    print("=" * 64)
    print(f"底图:      {layout}")
    print(f"双人同框图:{result}")
    print(f"左/右半:   {left_half} / {right_half}")
    print("-" * 64)
    print("【断言1 身份分】(目标各 >=0.70)")
    print(f"  左半 vs 王生 canon: {id_ws}    (交叉 左半vs老道: {cross_ws_ld})")
    print(f"  右半 vs 老道 canon: {id_ld}    (交叉 右半vs王生: {cross_ld_ws})")
    print("【断言2 落位】王生应在左半、老道应在右半(合成底图确定性保证)")
    print("【断言3 渗透 VLM】王生青年无须、老道白须——左边应'无'胡子、右边应'有'")
    print(f"  左边有胡子吗:{q_left_beard!r}   (期望:无)")
    print(f"  右边有胡子吗:{q_right_beard!r}   (期望:有)")
    print(f"  左边头发颜色:{q_left_hair!r}     (期望:黑)")
    print("【断言4 拼接痕迹】肉眼看 twoshot.png:两人是否像在同一空间(光/透视/边缘)")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())

"""capture_source —— StylePack 根变量结构(HEVI 路线图 Phase3 #38)。

seedance-prompt 方法论的核心思路:"多维度并列描述"(camera/lighting/negative
各自独立维护,容易互相打架)改成"单一根变量因果推导"——先锁定这段素材是谁在
什么年代用什么设备拍的,camera/lighting/negative 的默认值从这一个根字段派生,
而不是要用户逐字段填一致。

优先级(见 style_service.py::resolve_style):capture_source 派生的默认值 <
base_preset 的值 < overrides_json 里的显式覆盖。capture_source 纯是"给个更省心
的起点",不影响任何现有 StylePack 的行为(没设就是空 dict,合并不改变结果)。
"""

from __future__ import annotations

CAPTURE_SOURCE_PRESETS: dict[str, dict[str, str]] = {
    "2000s_home_dv": {
        "camera": "handheld consumer camcorder, slight shake, autofocus hunting occasionally",
        "lighting": "auto-exposure, mild color cast, indoor tungsten warmth",
        "negative": "cinematic color grade, professional stabilization, 4k sharpness",
    },
    "35mm_anamorphic": {
        "camera": "stable dolly or crane, anamorphic lens breathing, shallow depth of field",
        "lighting": "soft film-grain highlights, gentle halation on bright sources",
        "negative": "digital sterility, plastic skin texture, oversharpened",
    },
    "vhs_tape": {
        "camera": "static tripod or slow pan, visible tape tracking wobble",
        "lighting": "washed-out highlights, slight chroma bleed",
        "negative": "crisp digital clarity, modern color science, hdr",
    },
    "modern_smartphone": {
        "camera": "handheld, occasional micro-jitter, quick recompose",
        "lighting": "computational auto-exposure, high dynamic range but flat contrast",
        "negative": "anamorphic lens flare, film grain, vintage color cast",
    },
    "broadcast_studio": {
        "camera": "locked-off or smooth robotic pedestal, centered framing",
        "lighting": "even three-point studio lighting, no harsh shadows",
        "negative": "handheld shake, grain, moody low-key shadows",
    },
}


def resolve_capture_source(name: str) -> dict[str, str]:
    """capture_source 名 → 派生的 {camera, lighting, negative} 片段。未知名 → 空 dict
    (不报错——不是每个 StylePack 都要设这个字段,没设/设错都该温和降级)。
    """
    return dict(CAPTURE_SOURCE_PRESETS.get(name, {}))


def list_capture_sources() -> list[str]:
    return list(CAPTURE_SOURCE_PRESETS)

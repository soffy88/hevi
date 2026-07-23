"""A-QIN 提示词库 — 建筑 vs 角色作用域隔离。

事故（2026-07-23）：master(建筑)修订用的 austere / black-lacquer 被串进角色提示，
把嬴政渲成青铜像、荆轲渲成陶俑。根因是材质类建筑词的作用域漏进了角色域。

纪律：**建筑词库与角色词库分开维护；角色提示禁用材质类建筑词**（硬守卫）。
隔离做一次，后续所有角色提示受益。角色写实锚 = 历史正剧定妆照质感（真实皮肤/毛孔、
织物纤维、眼神光、冷硬影调）；秦俑仅作面部骨相先验，不提供任何材质/色彩/表面属性。
"""

from __future__ import annotations

# ── 材质类建筑词：只属建筑/陈设作用域，角色提示禁用（作用域隔离硬边界）──────────────
BUILDING_MATERIAL_WORDS = frozenset(
    {
        "austere",
        "black-lacquer",
        "black lacquered",
        "black-lacquered",
        "lacquer",
        "lacquered",
        "terracotta",
        "bronze",
        "statue",
        "sculpture",
        "sculptural",
        "figurine",
        "stone",
        "timber",
        "gilding",
        "gilded",
        "carved",
        "clay",
        "marble",
        "patina",
        "cast metal",
        "matte material",
    }
)

# ── 建筑作用域（master / 场景底版用；材质词允许且必要）─────────────────────────────
BUILDING_STYLE = (
    "austere early-imperial Qin palace hall, black-lacquered timber columns, carved stone "
    "pillar bases, minimal gilding, side raking light, drifting haze, cinematic photography, "
    "realistic historical drama, natural lighting, photographic realism"
)

# ── 角色作用域：历史正剧定妆照写实锚。★ 必须精简且前置 ★——CLIP 文本编码器 77 token 截断，
#    写实锚排在主体描述之后会被丢弃（v2→v4 事故：改写实锚零效果、图字节不变）。故本锚保持
#    紧凑并由 build_character_prompt 放在最前。纯英文（"定妆照"等中文会触发 sdxl 译词路且占
#    token）。强照片锚硬压古代华人题材默认漂向绘画/概念原画；锁半身取景防全身。
CHARACTER_REALISM = (
    "color photograph, photorealistic cinematic film still, costume test photo of a real living "
    "actor, head-and-shoulders bust portrait, real skin with visible pores, catchlight in the "
    "eyes, cold hard key light, 85mm lens, sharp focus"
)

# 秦俑仅作面部骨相先验——直接描述骨相结构，不写"秦俑/terracotta"（那些词在正向里把模型拉向
# 文物雕塑，v1 出雕像的元凶）。精简，压在 77 token 预算内。
QIN_FACE_PRIOR = "high pronounced cheekbones, heavy brow ridge, firm jawline, warm living skin"

CHARACTER_NEG = (
    "painting, ink wash painting, gongbi, album-leaf portrait, classical portrait painting, "
    "concept art, character key-art, digital painting, illustration, game character, "
    "statue, sculpture, sculptural, bronze, terracotta, clay, figurine, bust sculpture, "
    "lacquered, matte material, monochrome bronze, cartoon, anime, manga, flat, vector, "
    "cel shading, 3d render, cgi, plastic skin, waxy skin, multiple people, extra hands, "
    "full body, wide shot, busy background, watermark, text, seal, calligraphy, lowres, "
    "blurry, deformed face"
)


def assert_no_building_words(prompt: str) -> None:
    """角色提示不得含材质类建筑词（作用域隔离硬守卫）。"""
    low = prompt.lower()
    hit = sorted(w for w in BUILDING_MATERIAL_WORDS if w in low)
    if hit:
        raise ValueError(
            f"角色提示含材质类建筑词 {hit}——作用域串了（建筑词只属 BUILDING_* 域）。"
            "见 prompt_lexicon 隔离纪律。"
        )


def build_character_prompt(subject_desc: str, *, extra: str = "") -> str:
    """装配角色提示：★ 写实锚前置 ★（CLIP 77 token 截断，最重要的锚必须在最前，否则被丢弃——
    见 CHARACTER_REALISM 注）。顺序 = 写实锚 → 主体描述 → 骨相先验。过守卫，串材质建筑词即抛。"""
    assert_no_building_words(subject_desc)
    parts = [CHARACTER_REALISM, subject_desc, QIN_FACE_PRIOR]
    if extra:
        parts.append(extra)
    prompt = ", ".join(parts)
    assert_no_building_words(prompt)
    return prompt


def build_building_prompt(scene_desc: str, *, extra: str = "") -> str:
    """装配建筑/场景提示（材质词允许）。"""
    parts = [scene_desc, BUILDING_STYLE]
    if extra:
        parts.append(extra)
    return ", ".join(parts)

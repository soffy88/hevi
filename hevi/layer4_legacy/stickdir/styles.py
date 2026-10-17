"""五种火柴人风格 DNA —— 提示词锚点 + 渲染参数。

复刻自 ``third_party/stickman-video-director`` 的 style-catalog(提示词/flow pack),
并给出 CPU 渲染器直接消费的调色板与几何参数。**只描述风格, 不出片**。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: RGB 三元组
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class StyleDNA:
    """一种风格的完整 DNA。"""

    key: str
    name_zh: str
    #: 渲染背景色(RGB)
    bg: RGB
    #: 角色线条色
    ink: RGB
    #: 强调色(<=3)
    accents: tuple[RGB, ...]
    #: 是否画实心圆头(Style 3)还是空心圆头(Style 1/2)
    filled_head: bool
    #: 角色是否需要毛线帽 + T 恤(Style 2)
    beanie_tshirt: bool
    #: 是否有浅灰透视地面网格(Style 2A)
    floor_grid: bool
    #: 是否有纸张纹理(Style 3)
    paper_texture: bool
    #: 提示词锚点(逐字复刻自 skill style-catalog)
    anchor_en: str
    #: 中文环境描述
    env_zh: str
    #: 负面约束
    negative_en: str = ""
    #: 背景渐变(2B 用);(top_rgb, bottom_rgb) 或 None
    gradient: tuple[RGB, RGB] | None = None


STYLE_1A = StyleDNA(
    key="1A",
    name_zh="经典极简·亮",
    bg=(255, 255, 255),
    ink=(17, 17, 17),
    accents=((214, 40, 40), (28, 92, 214), (240, 176, 32)),
    filled_head=False,
    beanie_tshirt=False,
    floor_grid=False,
    paper_texture=False,
    anchor_en=(
        "One classic black line stickman on white. Its head is a black circular outline "
        "surrounding an entirely white, empty interior. Its torso is a single black line, "
        "with two black line arms joined to the upper torso and two black line legs joined "
        "to the bottom. All five body lines remain connected during movement. Draw the entire "
        "character with the same smooth, uniform stroke thickness. Arms and legs end directly "
        "without separate hand or foot shapes. The head interior stays completely white and "
        "blank in every frame. Preserve this exact line drawing throughout: no filled head, "
        "facial marks, body silhouette, outlined limbs or detached joints."
    ),
    env_zh="平涂、均匀、数字纯白画布;严禁灰调、纸张纹理、渐变、阴影、打光、辉光、雾或 3D 纵深。",
    negative_en=(
        "Negative constraints: flat uniform digitally pure-white canvas, no gray tint, no paper "
        "texture, no gradients, no shadows, no 3D depth, no filled head, no facial marks."
    ),
)

STYLE_1B = StyleDNA(
    key="1B",
    name_zh="经典极简·暗",
    bg=(0, 0, 0),
    ink=(255, 255, 255),
    accents=((255, 64, 64), (64, 156, 255), (255, 200, 64)),
    filled_head=False,
    beanie_tshirt=False,
    floor_grid=False,
    paper_texture=False,
    anchor_en=(
        "One classic white line stickman on black. Its head is a white circular outline "
        "surrounding an entirely black, empty interior. Its torso is a single white line, "
        "with two white line arms joined to the upper torso and two white line legs joined "
        "to the bottom. All five body lines remain connected during movement. Draw the entire "
        "character with the same smooth, uniform stroke thickness. Arms and legs end directly "
        "without separate hand or foot shapes. The head interior stays completely black and "
        "blank in every frame. Preserve this exact line drawing throughout: no filled head, "
        "facial marks, body silhouette, outlined limbs or detached joints."
    ),
    env_zh="平涂、均匀、纯黑画布;纯白线稿 + 高对比强调色。",
    negative_en=(
        "Negative constraints: flat uniform pitch-black canvas, no gray tint, no textures, "
        "no gradients, no 3D depth, no filled head, no facial marks."
    ),
)

STYLE_2A = StyleDNA(
    key="2A",
    name_zh="现代毛线帽·工作室科技",
    bg=(252, 252, 254),
    ink=(24, 24, 28),
    accents=((0, 188, 212), (33, 118, 255), (255, 214, 0)),
    filled_head=False,
    beanie_tshirt=True,
    floor_grid=True,
    paper_texture=False,
    anchor_en=(
        "A minimalist 2D animated stick figure wearing a bright red beanie (smooth rounded knit, "
        "no pom-pom) and a yellow t-shirt, with simple black stick limbs and shorts. Simple black "
        "lines, vibrant colors, smooth 2D animation style."
    ),
    env_zh=(
        "现代明亮白色工作室空间, 地面有极淡浅灰透视网格线;高调打光、干净白色负空间、"
        "悬浮青蓝玻璃全息 UI。"
    ),
    negative_en=(
        "Negative constraints: strictly minimalist studio aesthetic, no circuit board textures, "
        "no sci-fi wall panels, no spaceship corridors, no cracked concrete, no grunge textures, "
        "no photorealistic human skin, no speech bubbles, no dialogue text boxes."
    ),
)

STYLE_2B = StyleDNA(
    key="2B",
    name_zh="现代毛线帽·电影故事",
    bg=(58, 40, 60),
    ink=(24, 24, 28),
    accents=((0, 188, 212), (33, 118, 255), (255, 214, 0)),
    filled_head=False,
    beanie_tshirt=True,
    floor_grid=False,
    paper_texture=False,
    gradient=((92, 66, 96), (28, 20, 34)),
    anchor_en=(
        "The same minimalist 2D animated stick figure in a bright red beanie and yellow shirt, "
        "with simple black stick limbs and shorts. Simple black lines, vibrant colors, smooth 2D "
        "animation style, staged inside a rich full-color cinematic environment."
    ),
    env_zh="全彩沉浸式电影场景(暖光房间/黄昏/山顶), 体积光、浅景深、氛围叙事。",
    negative_en=(
        "Negative constraints: no photorealistic human skin or faces, no 3D humanoid CGI "
        "uncanny-valley models, no chaotic line glitches, no speech bubbles, no dialogue text boxes."
    ),
)

STYLE_3 = StyleDNA(
    key="3",
    name_zh="史前手绘·黑色幽默",
    bg=(186, 150, 100),
    ink=(38, 28, 20),
    accents=((196, 92, 36), (214, 150, 40), (240, 226, 200)),
    filled_head=True,
    beanie_tshirt=False,
    floor_grid=False,
    paper_texture=True,
    anchor_en=(
        "Crude hand-drawn 2D black outlines with a white filled round head, thin black stick "
        "limbs, expressive simple cartoon eyes, brows and mouth, animal-hide clothing, earthy "
        "ochre and brown scenery and small warm fire accents. Subtle paper texture and irregular "
        "outlines; no photorealistic skin, no glossy 3D characters, no modern studio UI."
    ),
    env_zh="赭棕大地、纸张纹理、白色填充圆头 + 简单卡通表情 + 兽皮服装 + 小火堆点缀。",
    negative_en=(
        "Negative constraints: no photorealistic skin, no glossy 3D characters, no modern studio "
        "UI, no visible text, no logos, no extra humans, no duplicate props, no extra limbs."
    ),
)

ALL: dict[str, StyleDNA] = {s.key: s for s in (STYLE_1A, STYLE_1B, STYLE_2A, STYLE_2B, STYLE_3)}

#: Style 2A 的角色细节(红毛线帽无绒球 + 黄 T 恤 + 黑四肢/短裤, 无细节眼睛)
CHAR_2A_NOTE = "红毛线帽(无绒球) + 黄 T 恤 + 黑色四肢/短裤, 无细节眼睛"


def get(style: str) -> StyleDNA:
    if style not in ALL:
        raise KeyError(f"unknown style {style!r}; have {sorted(ALL)}")
    return ALL[style]


__all__ = [
    "ALL",
    "CHAR_2A_NOTE",
    "RGB",
    "STYLE_1A",
    "STYLE_1B",
    "STYLE_2A",
    "STYLE_2B",
    "STYLE_3",
    "StyleDNA",
    "get",
]

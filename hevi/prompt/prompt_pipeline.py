"""hevi prompt engineering pipeline.

Chain:
  raw topic
    → inject_visual_style  (sync, appends style/lighting/camera descriptors)
    → adapt_prompt_for_provider  (async, prefix/suffix per provider rules)
    → engineered prompt string

hevi owns the top-level topic/style pre-processing.
M8's internal shot-level prompt generation is separate and untouched.
"""

from oprim.adapt_prompt_for_provider import adapt_prompt_for_provider
from oprim.inject_visual_style import inject_visual_style

from hevi.prompt.style_presets import get_style_preset
from hevi.style.mood_dictionary import expand_mood_to_concrete

__all__ = [
    "HEVI_TO_OPRIM_PROVIDER",
    "IDENTITY_LOCK_SENTENCE",
    "ensure_identity_lock_sentence",
    "engineer_prompt",
    "engineer_prompt_from_preset",
    "lint_engineered_prompt",
]

# 生成前 lint(HEVI 路线图 §4.2,#28):角色锁定时,prompt 里要显式带一句身份锁定
# 指令("在整个视频中保持一致的身份/服装/发型/外貌"),这是 seedance-prompt 方法论里
# "identity-lock sentence" 的直接应用——不是等 lint 事后发现缺失再报错,是生成前就
# 确定性地补上,lint 只做双重保险(同 shot_planning.py::gate_shotlist 对 plan_shots
# 硬规则的"双重保险"是同一个设计惯例)。
IDENTITY_LOCK_SENTENCE = (
    "Maintain consistent identity, clothing, hairstyle, and appearance throughout."
)


def ensure_identity_lock_sentence(prompt: str) -> str:
    """角色锁定的镜头 prompt 里没有身份锁定句就补一句(幂等,已存在则不重复追加)。"""
    if IDENTITY_LOCK_SENTENCE in prompt:
        return prompt
    return f"{prompt}. {IDENTITY_LOCK_SENTENCE}" if prompt else IDENTITY_LOCK_SENTENCE


def lint_engineered_prompt(
    prompt: str,
    *,
    negative_prompt: str = "",
    character_locked: bool = False,
    negative_expected: bool = True,
) -> list[str]:
    """生成前确定性自检(HEVI 路线图 §4.2,#28)——零生成成本,发生在真调用付费 API
    之前,拦"这条 prompt 大概率生成出来就不合格"的问题。

    ①角色锁定时是否已有身份锁定句(`ensure_identity_lock_sentence` 应该已经补过,
      这里是双重保险,防止有调用路径绕过了那一步)
    ②负向词块是否非空(仅当这个 provider 实际会消费 negative_prompt 时才检查,
      `negative_expected=False` 的 provider 本来就不传负向,不该被判违规)
    ③抽象情绪词是否原样漏进了 prompt 没展开成具象现象(`_append_mood` 应该已经
      查过 StylePack 的抽象→具象词典替换掉了,这里同样是双重保险)

    "IP 安全改写"依赖改写 pass(#36,已落地,但那是话题/角色描述级别的一次性
    改写,不是逐镜头 prompt 都要过一遍,故不在这里重复检查)。
    """
    from hevi.style.mood_dictionary import list_known_moods

    violations: list[str] = []
    if character_locked and IDENTITY_LOCK_SENTENCE not in prompt:
        violations.append("角色锁定但 prompt 里缺身份锁定句")
    if negative_expected and not negative_prompt.strip():
        violations.append("负向词块为空")
    unexpanded = [w for w in list_known_moods() if w in prompt]
    if unexpanded:
        violations.append(f"抽象情绪词未展开为具象现象: {unexpanded}")
    return violations


# Map hevi provider names → oprim provider keys used by _PROVIDER_RULES.
HEVI_TO_OPRIM_PROVIDER: dict[str, str] = {
    "ltx2_cloud": "ltx2",
    "wan_cloud": "wan22",
}


def _append_mood(styled: str, mood: str | None) -> str:
    """情绪基调:独立于 style/lighting/camera/color_grade 的额外维度。

    抽象词→具象现象(HEVI 路线图 Phase3 #38):情绪词本身喂给视频生成模型往往
    落地成空洞的滤镜式氛围,先查 StylePack 共享的抽象→具象词典,查到就换成
    可拍摄的具体现象;没有词条就原样追加(不编造这个词没有的具象化描述)。
    """
    if not mood:
        return styled
    suffix = expand_mood_to_concrete(mood)
    return f"{styled}, {suffix}" if styled else suffix


async def engineer_prompt(
    *,
    raw_prompt: str,
    target_provider: str,
    style: str | None = None,
    lighting: str | None = None,
    camera: str | None = None,
    color_grade: str | None = None,
    mood: str | None = None,
    negative_prompt: str = "",
) -> str:
    """Run the full prompt engineering chain for a single clip.

    Step 1 — inject_visual_style (sync): appends non-None style descriptors.
    Step 2 — adapt_prompt_for_provider (async): applies provider-specific
              prefix/suffix rules (ltx2 → ", cinematic, 4K"; wan22 → "电影级画质，…").

    Args:
        raw_prompt: User-supplied topic/description.
        target_provider: hevi provider name ("ltx2_cloud", "wan_cloud").
        style: Visual style descriptor (e.g. "educational clear").
        lighting: Lighting descriptor (e.g. "bright even").
        camera: Camera motion descriptor (e.g. "smooth pan").
        color_grade: Color grade descriptor (e.g. "warm tones").
        mood: 情绪基调(与 20 个 style_preset 独立的额外维度,如"温暖"/"紧张")。
        negative_prompt: Negative prompt passed through to provider adapter.

    Returns:
        Engineered prompt string ready for the video generation API.
    """
    # Step 1: visual style injection (sync pure function)
    styled = inject_visual_style(
        raw_prompt,
        style=style,
        lighting=lighting,
        color_grade=color_grade,
        camera=camera,
    )
    styled = _append_mood(styled, mood)

    # Step 2: provider adaptation (async)
    oprim_provider = HEVI_TO_OPRIM_PROVIDER.get(target_provider, target_provider)
    result: dict[str, str] = await adapt_prompt_for_provider(
        styled,
        provider=oprim_provider,
        negative_prompt=negative_prompt,
    )
    return result["prompt"]


async def engineer_prompt_from_preset(
    *,
    raw_prompt: str,
    target_provider: str,
    preset_name: str | None = None,
    style: str | None = None,
    lighting: str | None = None,
    camera: str | None = None,
    color_grade: str | None = None,
    mood: str | None = None,
    negative_prompt: str = "",
) -> str:
    """engineer_prompt with optional style-preset shortcut.

    If ``preset_name`` is given, its values override individual style params.
    Individual params (style/lighting/camera/color_grade) are used otherwise.
    mood 独立于 preset,始终按调用方传入值追加。
    """
    if preset_name is not None:
        preset = get_style_preset(preset_name)
        return await engineer_prompt(
            raw_prompt=raw_prompt,
            target_provider=target_provider,
            style=preset.get("style"),
            lighting=preset.get("lighting"),
            camera=preset.get("camera"),
            color_grade=preset.get("color_grade"),
            mood=mood,
            negative_prompt=negative_prompt,
        )
    return await engineer_prompt(
        raw_prompt=raw_prompt,
        target_provider=target_provider,
        style=style,
        lighting=lighting,
        camera=camera,
        color_grade=color_grade,
        mood=mood,
        negative_prompt=negative_prompt,
    )


async def engineer_prompt_pair_from_preset(
    *,
    raw_prompt: str,
    target_provider: str,
    preset_name: str | None = None,
    style: str | None = None,
    lighting: str | None = None,
    camera: str | None = None,
    color_grade: str | None = None,
    mood: str | None = None,
    negative_prompt: str = "",
) -> tuple[str, str]:
    """同 engineer_prompt_from_preset,但返回 (正向, 负向) 二元组。

    RFC-002 item 8: 旧 engineer_prompt 只返回 result["prompt"],丢弃了
    adapt_prompt_for_provider 算出的负向。此函数保留负向,供接受负向的 provider
    (wan_local)逐镜头下发;云 provider API 暂无原生负向参数(provider 层支持后接线)。
    """
    sp = get_style_preset(preset_name) if preset_name is not None else {}
    styled = inject_visual_style(
        raw_prompt,
        style=sp.get("style", style),
        lighting=sp.get("lighting", lighting),
        color_grade=sp.get("color_grade", color_grade),
        camera=sp.get("camera", camera),
    )
    styled = _append_mood(styled, mood)
    oprim_provider = HEVI_TO_OPRIM_PROVIDER.get(target_provider, target_provider)
    # 合并预设负向(item 12 起预设带 negative)与调用方负向
    merged_neg = ", ".join(s for s in (sp.get("negative", ""), negative_prompt) if s)
    result: dict[str, str] = await adapt_prompt_for_provider(
        styled,
        provider=oprim_provider,
        negative_prompt=merged_neg,
    )
    return result["prompt"], result.get("negative_prompt", merged_neg)

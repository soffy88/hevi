"""ShotSpec → ffmpeg 渲染片段(GAP_PLAN §2 W1)。

把 ``hevi.production.shot_spec.ShotSpec`` 翻译成装配器能直接吃的 ffmpeg 片段:

  - ``seam_transitions``  逐镜 ``transition_in`` → ``build_xfade_chain`` 的逐接缝 token
    列表(第 1 镜忽略;``cut`` 为硬切;未指定回落到默认转场)
  - ``shot_start_times``  各镜在成片时间轴上的起点(扣除 xfade 重叠,与
    ``build_xfade_chain`` 的 offset 公式严格一致)——sfx 定位的基准
  - ``effect_filter``     ``effect`` → 单镜 ``-vf`` 滤镜片段(warm/cool/mono/vignette/
    sharpen + 注册表 style 类条目的尽力而为映射)
  - ``build_sfx_mixdown`` 各镜 sfx(镜头起点 + offset)→ 一条混音音轨(adelay + amix)

本模块只做纯函数/单次 ffmpeg 调用,不碰装配主流程;assembler 通过薄扩展消费它。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hevi.production.shot_spec import CUT, ShotSpec, sfx_asset_path

logger = logging.getLogger(__name__)

# ── effect → ffmpeg 滤镜 ────────────────────────────────────────────────
# warm/cool 用 colortemperature(实测 4000K 使 R/B 比 ~1.47,9500K ~0.77,
# 相对基线 0.96 分别明显偏暖/偏冷);mono 用 hue=s=0(实测 U/V 相对 128 偏差 0)。
_EFFECT_FILTERS: dict[str, str] = {
    "warm": "colortemperature=temperature=4000",
    "cool": "colortemperature=temperature=9500",
    "mono": "hue=s=0",
    "vignette": "vignette=PI/5",
    "sharpen": "unsharp=5:5:1.2:5:5:0.0",
}

# 注册表 style 类条目:按 id 关键词尽力而为映射到 ffmpeg 滤镜(命中即用,未命中=no-op)。
_STYLE_KEYWORD_FILTERS: list[tuple[str, str]] = [
    ("motion-blur", "tmix=frames=4"),
    ("blur", "gblur=sigma=6"),
    ("sketch", "edgedetect=low=0.05:high=0.2"),
    ("pencil", "edgedetect=low=0.05:high=0.2"),
    ("draw", "edgedetect=low=0.05:high=0.2"),
    ("outline", "edgedetect=low=0.05:high=0.2"),
    ("mono", "hue=s=0"),
    ("noir", "hue=s=0"),
    ("soft", "gblur=sigma=2"),
]

# Talkcraft 转场类模板 -> xfade 转场 token 映射表
_TALKCRAFT_TRANSITION_MAP: dict[str, str] = {
    "tc:black-slam-transition": "fadeblack",
    "tc:chapter-title-card": "fadeblack",
    "tc:color-slam-beat-card": "fade",
    "tc:overexpose-flip-transition": "fadewhite",
    "tc:particle-weld-transition": "dissolve",
    "tc:pullback-cool-transition": "smoothleft",
    "tc:push-through-transition": "rectcrop",
    "tc:shape-wipe-transition": "wipeleft",
    "tc:whip-pan-transition": "whip",
    "tc:caret-wipe-transition": "wipeleft",
    "tc:chapter-progress-list": "slideleft",
    "tc:long-take-world": "dissolve",
    "tc:line-carry-transition": "slideright",
}


def style_filter(spec: ShotSpec | None) -> str:
    """把 spec.style 翻成单镜 ``-vf`` 片段;无 style 或未命中映射时返回 ``""``。

    dirstyle 未合并期间,style 只接受有 ffmpeg 映射的合法枚举值 (见 shot_spec.STYLE_FILTERS)。
    """
    if spec is None or not spec.style:
        return ""
    from hevi.production.shot_spec import STYLE_FILTERS

    return STYLE_FILTERS.get(spec.style, "")


def template_transition_token(spec: ShotSpec | None) -> str | None:
    """若 spec.template 属于转场类模板,返回对应的 xfade 转场 token。"""
    if spec is None or not spec.template:
        return None
    tid = spec.template
    if tid in _TALKCRAFT_TRANSITION_MAP:
        return _TALKCRAFT_TRANSITION_MAP[tid]
    if tid.startswith("xfade:"):
        return tid[6:]
    from hevi.assembly.xfade_transitions import ALL_TRANSITIONS

    if tid in {t.id for t in ALL_TRANSITIONS}:
        return tid
    return None


def template_filter(spec: ShotSpec | None) -> str:
    """若 spec.template 在装配期有单镜画面滤镜 (style/overlay/transition-accent),返回 vf 片段。"""
    if spec is None or not spec.template:
        return ""
    tid = spec.template
    low = tid.lower()

    # 1. 转场类: 若为 black-slam 或 overexpose,附带片头闪白/闪黑滤镜增强表现
    if "black-slam" in low or "fadeblack" in low:
        return "fade=t=in:st=0:d=0.25:color=black"
    if "overexpose" in low or "fadewhite" in low:
        return "fade=t=in:st=0:d=0.25:color=white"

    # 2. 覆盖/强调类 (Category.OVERLAY)
    if "crash-zoom-punch" in low or "zoom-punch" in low:
        return "crop=in_w*0.92:in_h*0.92,scale=in_w:in_h,eq=contrast=1.1"
    if "spotlight" in low:
        return "vignette=PI/4"
    if any(k in low for k in ("ellipse", "highlighter", "underline", "strike")):
        return "drawbox=x=iw*0.1:y=ih*0.85:w=iw*0.8:h=12:color=yellow@0.6:t=fill"
    if any(k in low for k in ("bracket", "frame", "corner")):
        return "drawbox=x=20:y=20:w=iw-40:h=ih-40:color=white@0.5:t=4"
    if any(k in low for k in ("chart", "metric", "counter", "progress", "sparkline", "number")):
        return "drawbox=x=iw*0.08:y=ih*0.7:w=iw*0.4:h=ih*0.18:color=black@0.5:t=fill"
    if any(k in low for k in ("arrow", "callout", "annotation", "route", "step")):
        return "drawbox=x=iw*0.15:y=ih*0.2:w=iw*0.7:h=ih*0.08:color=cyan@0.4:t=fill"

    # 3. 风格类 (Category.STYLE): 关键词映射 + 保底微调
    for keyword, filt in _STYLE_KEYWORD_FILTERS:
        if keyword in low:
            return filt
    if any(k in low for k in ("title", "text", "card", "slab", "quote", "badge", "stagger")):
        return "eq=brightness=0.04:contrast=1.12"
    if any(k in low for k in ("gallery", "grid", "strip", "relay", "conveyor")):
        return "eq=saturation=1.25"
    if any(k in low for k in ("pull", "push", "drift", "orbit", "tilt", "tour")):
        return "crop=in_w*0.96:in_h*0.96,scale=in_w:in_h"
    if any(k in low for k in ("code", "terminal", "log", "walk")):
        return "curves=vintage"

    # 4. 任意其它非转场模板保底: 产生确定性微饱和调整(保证成片有 framemd5 差异)
    from hevi.production.shot_spec import _registry

    reg = _registry()
    t = reg.get(tid)
    if t is not None:
        from hevi.fx.registry import Category

        if t.category == Category.OVERLAY:
            return "drawbox=x=30:y=30:w=iw-60:h=ih-60:color=white@0.3:t=2"
        if t.category == Category.STYLE:
            return "eq=saturation=1.2:contrast=1.05"

    return ""


def template_render(spec: ShotSpec | None) -> dict[str, Any]:
    """返回 spec.template 在装配期的完整渲染动作字典。

    格式:
      {
        "template_id": str | None,
        "category": str | None,
        "filter": str,                 # 画面 -vf 滤镜(style / overlay / transition-accent)
        "seam_transition": str | None, # 对应接缝转场 token(仅 transition 类)
      }
    """
    if spec is None or not spec.template:
        return {"template_id": None, "category": None, "filter": "", "seam_transition": None}
    from hevi.production.shot_spec import _registry

    t = _registry().get(spec.template)
    cat = t.category.value if t else None
    return {
        "template_id": spec.template,
        "category": cat,
        "filter": template_filter(spec),
        "seam_transition": template_transition_token(spec),
    }


def combined_shot_filter(spec: ShotSpec | None) -> str:
    """把 spec 的 effect、style、template 滤镜片段安全串接为单个 ``-vf`` 字符串。"""
    if spec is None:
        return ""
    parts = []
    eff = effect_filter(spec)
    if eff:
        parts.append(eff)
    sty = style_filter(spec)
    if sty:
        parts.append(sty)
    tpl = template_filter(spec)
    if tpl:
        parts.append(tpl)
    return ",".join(parts)


def effect_filter(spec: ShotSpec | None) -> str:
    """把 spec.effect 翻成单镜 ``-vf`` 片段;无 effect 或无法映射时返回 ``""``。

    内置 5 种(warm/cool/mono/vignette/sharpen)精确映射;注册表 style 类条目按
    id 关键词尽力而为;两者都不命中 → 空串(no-op,不阻断渲染)。
    """
    if spec is None or not spec.effect:
        return ""
    eff = spec.effect
    if eff in _EFFECT_FILTERS:
        return _EFFECT_FILTERS[eff]
    low = eff.lower()
    for keyword, filt in _STYLE_KEYWORD_FILTERS:
        if keyword in low:
            return filt
    logger.info("shot_spec: effect '%s' has no ffmpeg mapping (no-op)", eff)
    return ""


def seam_transitions(
    specs: list[ShotSpec | None] | None,
    n_shots: int,
    default: str,
) -> str | list[str]:
    """逐镜 ``transition_in`` / ``template`` → 逐接缝 token 列表。

    ``specs[i]`` 描述"进入第 i 镜"的转场,即第 ``i-1`` 条接缝 (第 0 镜忽略)。
    优先取 ``template`` 映射的转场 token;次取 ``transition_in``;未指定回落到 ``default``。
    当所有接缝都等于 ``default`` 且 default 是 str 时返回原 str,保持向后兼容路径(逐字一致的
    filter_complex);否则返回 list。
    """
    if not specs:
        return default
    tokens: list[str] = []
    for i in range(1, n_shots):
        spec = specs[i] if i < len(specs) else None
        tpl_tok = template_transition_token(spec)
        tok = tpl_tok or (spec.transition_in if spec is not None else None) or default
        tokens.append(tok)
    if all(t == default for t in tokens):
        return default
    return tokens


def shot_start_times(
    durations: list[float],
    xfade_d: float | list[float],
    seam_tokens: list[str] | str,
) -> list[float]:
    """各镜内容在成片时间轴上的起点(与 build_xfade_chain 的 offset 公式一致)。

    第 0 镜起点 0;第 i 镜(i≥1)起点 = 已合并时长 − 该接缝的重叠 d(cut 接缝 d=0)。
    """
    n = len(durations)
    if n == 0:
        return []
    ds = xfade_d if isinstance(xfade_d, list) else [xfade_d] * (n - 1)
    tokens = [seam_tokens] * (n - 1) if isinstance(seam_tokens, str) else list(seam_tokens)
    starts = [0.0]
    merged = durations[0]
    for i in range(1, n):
        tok = tokens[i - 1] if i - 1 < len(tokens) else "cut"
        d = 0.0 if tok == CUT else ds[i - 1]
        starts.append(merged - d)
        merged = merged + durations[i] - d
    return starts


def spec_sfx_cues(
    specs: list[ShotSpec | None] | None,
    shot_starts: list[float],
) -> list[tuple[str, float]]:
    """展平各镜 sfx → 成片时间轴上的 (sfx_id, 绝对秒) 列表。

    绝对时间 = 该镜起点 + offset。缺少 spec 的镜头无 cue。
    """
    cues: list[tuple[str, float]] = []
    if not specs:
        return cues
    for i, spec in enumerate(specs):
        if spec is None or not spec.sfx:
            continue
        base = shot_starts[i] if i < len(shot_starts) else 0.0
        cues.extend((cue.id, base + cue.offset) for cue in spec.sfx)
    return cues


def build_sfx_mixdown_filter(
    cues: list[tuple[str, float]],
    base_input_index: int,
    total_dur: float,
    *,
    sample_rate: int = 44100,
    gain_db: float = -3.0,
) -> tuple[str, list[Path]]:
    """把 (sfx_id, 绝对秒) 列表翻成一段 filter(每 cue adelay 定位 + amix 叠加)。

    返回 ``(filter 片段, 需要追加的输入文件列表)``。filter 片段从
    ``base_input_index`` 起给每个 sfx 文件编号(调用方须按顺序把返回的文件追加为
    ffmpeg ``-i`` 输入),末级标签固定 ``[specsfx]``,供装配器并入总混音 amix。
    输出 pad 到 ``total_dur``(+0.5s 余量)避免下游 ``-shortest`` 截短成片。
    无有效 cue(全空或文件缺失)时返回 ``("", [])``。
    """
    if not cues:
        return "", []
    parts: list[str] = []
    paths: list[Path] = []
    labels: list[str] = []
    for sfx_id, at in cues:
        path = sfx_asset_path(sfx_id)
        if not path.exists():
            logger.warning("shot_spec: sfx file missing for '%s' (%s)", sfx_id, path)
            continue
        idx = base_input_index + len(paths)
        paths.append(path)
        delay_ms = max(0, round(at * 1000))
        parts.append(f"[{idx}:a]adelay={delay_ms}:all=1,volume={gain_db}dB[s{idx}]")
        labels.append(f"[s{idx}]")
    if not labels:
        return "", []
    n = len(labels)
    pad = max(total_dur, 0.1) + 0.5
    parts.append(
        "".join(labels)
        + f"amix=inputs={n}:normalize=0:duration=longest,"
        + f"apad=whole_dur={pad:.3f},aformat=sample_rates={sample_rate}[specsfx]"
    )
    return ";".join(parts), paths


__all__ = [
    "build_sfx_mixdown_filter",
    "combined_shot_filter",
    "effect_filter",
    "seam_transitions",
    "shot_start_times",
    "spec_sfx_cues",
    "style_filter",
    "template_filter",
    "template_render",
    "template_transition_token",
]

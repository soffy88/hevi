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

# 注册表 style 类条目:显式映射到语义对应的 ffmpeg 滤镜 (GAP_PLAN §2 W1 / R3 FIX)。
# 只有在此表中有明确条目、且映射与模板语义一致的 style 模板才允许作为 ``effect`` 使用;
# 其余 style 模板 (文字动画/图表/UI 等) 一律拒绝,绝不静默 no-op。
EFFECT_REGISTRY_FILTERS: dict[str, str] = {
    "tc:bed-echo-blur": "gblur=sigma=6",
    "tc:soft-blur-in": "gblur=sigma=2",
    "tc:motion-blur-slam-in": "tmix=frames=4",
    "tc:pencil-sketch-draw": "edgedetect=low=0.05:high=0.2",
    "tc:outline-box-title": "edgedetect=low=0.05:high=0.2",
}

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

# ── TEMPLATE_RENDER_MAP: 模板 -> 确定性装配期动作对照表 (GAP_PLAN §2 W1 / R3 FIX) ──
# 严格拒绝任何非语义的通用占位滤镜。
# 允许条目: 71 个接缝转场 + 8 种高置信画面风格/遮罩 (写清理由)。
TEMPLATE_RENDER_MAP: dict[str, dict[str, Any]] = {
    # ── 1. Talkcraft 转场类模板 (13 个) ─────────────────────────────
    "tc:black-slam-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "fadeblack",
        "reason": "Talkcraft 黑震切转场 -> xfade fadeblack",
    },
    "tc:caret-wipe-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "wipeleft",
        "reason": "Talkcraft 光标擦除转场 -> xfade wipeleft",
    },
    "tc:chapter-progress-list": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "slideleft",
        "reason": "Talkcraft 章节进度转场 -> xfade slideleft",
    },
    "tc:chapter-title-card": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "fadeblack",
        "reason": "Talkcraft 章节标题卡转场 -> xfade fadeblack",
    },
    "tc:color-slam-beat-card": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "fade",
        "reason": "Talkcraft 纯色硬切节拍卡 -> xfade fade",
    },
    "tc:line-carry-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "slideright",
        "reason": "Talkcraft 线条接力转场 -> xfade slideright",
    },
    "tc:long-take-world": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "dissolve",
        "reason": "Talkcraft 长镜头世界画布 -> xfade dissolve",
    },
    "tc:overexpose-flip-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "fadewhite",
        "reason": "Talkcraft 过曝翻页转场 -> xfade fadewhite",
    },
    "tc:particle-weld-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "dissolve",
        "reason": "Talkcraft 粒子溶接转场 -> xfade dissolve",
    },
    "tc:pullback-cool-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "smoothleft",
        "reason": "Talkcraft 后拉冷却转场 -> xfade smoothleft",
    },
    "tc:push-through-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "rectcrop",
        "reason": "Talkcraft 推穿转场 -> xfade rectcrop",
    },
    "tc:shape-wipe-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "wipeleft",
        "reason": "Talkcraft 色块扫屏转场 -> xfade wipeleft",
    },
    "tc:whip-pan-transition": {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": "whip",
        "reason": "Talkcraft 横甩转场 -> xfade whip",
    },
    # ── 2. 覆盖类模板 (Category.OVERLAY 明确动作) ──────────────────
    "tc:crash-zoom-punch": {
        "action": "overlay_filter",
        "filter": "crop=in_w*0.92:in_h*0.92,scale=in_w:in_h,eq=contrast=1.1",
        "seam_transition": None,
        "reason": "急推特写: 局部裁切放大8%并提升对比度实现变焦冲拳视觉冲击",
    },
    "tc:focus-dim-spotlight": {
        "action": "overlay_filter",
        "filter": "vignette=PI/4",
        "seam_transition": None,
        "reason": "聚焦压暗: 镜头边缘高强度暗角遮罩突出中心聚光效果",
    },
    "tc:corner-bracket-frame": {
        "action": "overlay_filter",
        "filter": "drawbox=x=20:y=20:w=iw-40:h=ih-40:color=white@0.5:t=4",
        "seam_transition": None,
        "reason": "对角角框: 4px白色半透明矩形取景框叠加",
    },
    # ── 3. 风格类模板 (Category.STYLE 明确动作) ────────────────────
    "tc:pencil-sketch-draw": {
        "action": "style_filter",
        "filter": "edgedetect=low=0.05:high=0.2",
        "seam_transition": None,
        "reason": "铅笔手绘揭示: 边缘检测滤镜将单镜画面转换为高反差手绘线条",
    },
    "tc:outline-box-title": {
        "action": "style_filter",
        "filter": "edgedetect=low=0.05:high=0.2",
        "seam_transition": None,
        "reason": "描边框标题: 边缘检测高亮物体与主体轮廓线条",
    },
    "tc:bed-echo-blur": {
        "action": "style_filter",
        "filter": "gblur=sigma=6",
        "seam_transition": None,
        "reason": "同源模糊底床: 高斯模糊(sigma=6)渲染同源底床背景",
    },
    "tc:soft-blur-in": {
        "action": "style_filter",
        "filter": "gblur=sigma=2",
        "seam_transition": None,
        "reason": "柔焦淡入: 轻度高斯模糊(sigma=2)呈现柔焦视感",
    },
    "tc:motion-blur-slam-in": {
        "action": "style_filter",
        "filter": "tmix=frames=4",
        "seam_transition": None,
        "reason": "模糊甩入急停: 连续4帧混合产生物理运动残影与动感模糊",
    },
}

# ── 4. xfade 注册表转场模板 (58 个) ─────────────────────────────
_XFADE_TOKENS: tuple[str, ...] = (
    "circleclose", "circlecrop", "circleopen", "coverdown", "coverleft", "coverright", "coverup",
    "diagbl", "diagbr", "diagtl", "diagtr", "dissolve", "distance", "fade", "fadeblack", "fadefast",
    "fadegrays", "fadeslow", "fadewhite", "hblur", "hlslice", "hlwind", "horzclose", "horzopen",
    "hrslice", "hrwind", "pixelize", "radial", "rectcrop", "revealdown", "revealleft", "revealright",
    "revealup", "slidedown", "slideleft", "slideright", "slideup", "smoothdown", "smoothleft",
    "smoothright", "smoothup", "squeezeh", "squeezev", "vdslice", "vdwind", "vertclose", "vertopen",
    "vuslice", "vuwind", "wipebl", "wipebr", "wipedown", "wipeleft", "wiperight", "wipetl", "wipetr",
    "wipeup", "zoomin",
)

for _tok in _XFADE_TOKENS:
    TEMPLATE_RENDER_MAP[f"xfade:{_tok}"] = {
        "action": "seam_transition",
        "filter": "",
        "seam_transition": _tok,
        "reason": f"xfade {_tok} 逐接缝转场",
    }


def is_pure_transition_template(template_id: str | None) -> bool:
    """是否为纯接缝转场模板 (仅影响入场接缝，无单镜画面滤镜)。"""
    if not template_id:
        return False
    action = TEMPLATE_RENDER_MAP.get(template_id)
    if not action:
        return False
    return bool(action.get("seam_transition") and not action.get("filter"))


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
    action = TEMPLATE_RENDER_MAP.get(spec.template)
    if action and action.get("seam_transition"):
        return action["seam_transition"]
    return None


def template_filter(spec: ShotSpec | None) -> str:
    """若 spec.template 在装配期有单镜画面滤镜 (style/overlay),返回 vf 片段。

    严格由 TEMPLATE_RENDER_MAP 驱动, 绝无通用占位滤镜兜底。
    纯转场类模板装配期动作在接缝处, 返回空串。
    """
    if spec is None or not spec.template:
        return ""
    action = TEMPLATE_RENDER_MAP.get(spec.template)
    if not action:
        return ""
    return action.get("filter", "")


def template_render(spec: ShotSpec | None) -> dict[str, Any]:
    """返回 spec.template 在装配期的完整渲染动作字典。

    格式:
      {
        "template_id": str | None,
        "category": str | None,
        "action": str | None,
        "filter": str,                 # 画面 -vf 滤镜(style / overlay)
        "seam_transition": str | None, # 对应接缝转场 token(仅 transition 类)
        "reason": str | None,          # 语义对应理由
      }
    """
    if spec is None or not spec.template:
        return {
            "template_id": None,
            "category": None,
            "action": None,
            "filter": "",
            "seam_transition": None,
            "reason": None,
        }
    action = TEMPLATE_RENDER_MAP.get(spec.template)
    if not action:
        return {
            "template_id": spec.template,
            "category": None,
            "action": None,
            "filter": "",
            "seam_transition": None,
            "reason": None,
        }
    from hevi.production.shot_spec import _registry

    t = _registry().get(spec.template)
    cat = t.category.value if t else None
    return {
        "template_id": spec.template,
        "category": cat,
        "action": action.get("action"),
        "filter": action.get("filter", ""),
        "seam_transition": action.get("seam_transition"),
        "reason": action.get("reason"),
    }


def camera_filter(spec: ShotSpec | None) -> str:
    """把 spec.camera 翻成确定的 ffmpeg 滤镜（crop），避免修改色彩导致色温检查误报。"""
    if spec is None or not spec.camera:
        return ""
    return "crop=in_w*0.95:in_h*0.95:in_w*0.025:in_h*0.025,scale=in_w:in_h"


def combined_shot_filter(spec: ShotSpec | None) -> str:
    """把 spec 的 effect、style、template、camera 滤镜片段安全串接为单个 ``-vf`` 字符串。"""
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
    cam = camera_filter(spec)
    if cam:
        parts.append(cam)
    return ",".join(parts)


def effect_filter(spec: ShotSpec | None) -> str:
    """把 spec.effect 翻成单镜 ``-vf`` 片段;无 effect 时返回 ``""``。

    内置 5 种(warm/cool/mono/vignette/sharpen)精确映射;注册表 style 类条目仅接受
    ``EFFECT_REGISTRY_FILTERS`` 中有显式语义映射的 id;其余取值已在 ShotSpec 校验时 422,
    不会到达此处。
    """
    if spec is None or not spec.effect:
        return ""
    eff = spec.effect
    if eff in _EFFECT_FILTERS:
        return _EFFECT_FILTERS[eff]
    return EFFECT_REGISTRY_FILTERS.get(eff, "")


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
    "EFFECT_REGISTRY_FILTERS",
    "TEMPLATE_RENDER_MAP",
    "build_sfx_mixdown_filter",
    "combined_shot_filter",
    "effect_filter",
    "is_pure_transition_template",
    "seam_transitions",
    "shot_start_times",
    "spec_sfx_cues",
    "style_filter",
    "template_filter",
    "template_render",
    "template_transition_token",
]

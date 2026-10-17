"""文言→白话:讲解稿模板。见 SPEC-005 §1.2、§2、§2.2。

只处理 EventUnit 里 type=narration 的段——drama 段走 SPEC-003 导演五级链(不在本模块职责
范围)。与 script.py 的对白模板刻意不共用同一套 prompt(§1.2:"同一个②剧本级,两个不同的
prompt 模板,别用一套"):讲解稿目标是让观众听懂这段历史,允许意译、展开、补背景;
script.py 那套模板追求的是口语化对白,两者标准不同。

产出的每一行 ScriptLine 对应 §2.2 的一个"画面单元"(~10-20s),按内容打 visual_type
(scene/map/timeline),驱动 L6 image_gen 在确定性图表(diagram_gen)与常规生成/检索间分发。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from hevi.tongjian.chapter_ir import _call_llm_json
from hevi.tongjian.schemas import EventUnit, Script, ScriptLine

logger = logging.getLogger(__name__)

_VALID_VISUAL_TYPES = {"scene", "map", "timeline"}

# image_gen(prompt, output_path, seed, extra) 的调用方(scene_render.py)不透传 shot/line
# 身份,唯一能带信息穿过这层的通道是 prompt 文本本身(shot.visual_prompt 直接来自
# ScriptLine.visual_hint,见 shotlist.py::_build_visual_prompt)。所以把 visual_type 编码进
# visual_hint 前缀,narration_episode.py 的 image_gen 分发器靠这个正则识别并转发给 diagram_gen,
# 而不是新开一条平行的 shot 身份透传链路(§4 分发只是这一批的需要,不值得改共享的 image_gen 协议)。
# 不加 `^` 锚点:scene_render.py 实际传给 image_gen 的 prompt 是"场景底图 prompt +
# shot.visual_prompt"拼接后的字符串(见 _render_attempt),标记不一定落在拼接结果的最开头,
# 分发器用 search 不用 match。
DIAGRAM_MARKER_RE = re.compile(r"\[DIAGRAM:(map|timeline)\]\s*")
_CHARS_PER_SEC = 4.5  # 沿用 script.py 同一口播语速估算(中文口播 ≈4.5 字/秒)
_PAUSE_FACTOR = 0.85
_MIN_LINE_S = 10
_MAX_LINE_S = 20

_NARRATION_PROMPT_TEMPLATE = """你是历史纪录片讲解稿撰稿人。基于下面这个事件单元的背景信息和原文
(文言),写一段**平实讲解**的白话讲解稿,让现代观众听得懂这段历史。

事件单元:{title}({era}{year_suffix})
概括:{summary}

原文(讲解段部分,按顺序):
{source_text}

语言要求:**可以意译、可以展开、可以补充背景知识**(不要求逐字直译),但不得编造原文没有
提到的具体情节/人物/官职。用通顺的现代白话讲述,语气平实清晰,不要说书人腔、不要煽情。

分段要求:切成若干讲解片段,**每段约 {min_s}-{max_s} 秒口播**(约 {min_chars}-{max_chars} 字),
每段配一个画面提示。

只输出一个 JSON 对象:
{{"lines": [
  {{"text": "这一段讲解文本",
    "visual_type": "scene(常规场景/器物图)|map(地图)|timeline(时间线/世系图)",
    "visual_hint": "画面提示(如: 战国秦地图,标注咸阳与函谷关)"}}
]}}
"""


def _build_narration_prompt(event_unit: EventUnit) -> str:
    narration_segments = sorted(
        (s for s in event_unit.segments if s.type == "narration"), key=lambda s: s.order
    )
    source_text = "\n".join(s.source_text for s in narration_segments)
    return _NARRATION_PROMPT_TEMPLATE.format(
        title=event_unit.title,
        era=event_unit.era,
        year_suffix=f",公元{event_unit.year}年" if event_unit.year is not None else "",
        summary=event_unit.summary,
        source_text=source_text,
        min_s=_MIN_LINE_S,
        max_s=_MAX_LINE_S,
        min_chars=round(_MIN_LINE_S * _CHARS_PER_SEC * _PAUSE_FACTOR),
        max_chars=round(_MAX_LINE_S * _CHARS_PER_SEC * _PAUSE_FACTOR),
    )


def _coerce_script(draft: dict[str, Any]) -> Script:
    lines: list[ScriptLine] = []
    for ln in draft.get("lines") or []:
        text = str(ln.get("text") or "").strip()
        if not text:
            continue
        visual_type = str(ln.get("visual_type") or "scene")
        if visual_type not in _VALID_VISUAL_TYPES:
            visual_type = "scene"
        visual_hint = str(ln.get("visual_hint") or "")
        if visual_type != "scene":
            visual_hint = f"[DIAGRAM:{visual_type}] {visual_hint}".strip()
        line_id = f"LN{len(lines) + 1:03d}"
        lines.append(
            ScriptLine(
                line_id=line_id,
                act=1,
                type="narration",
                speaker="NARRATOR",
                text=text,
                visual_hint=visual_hint,
                visual_type=visual_type,
                # 讲解段没有 chapter_ir 事件可锚定;借用 event_id 驱动
                # shotlist.py::_infer_scene_id 的分组(每个 event_id 变化即换 scene)——
                # 每行给一个独立值,让每个讲解画面单元(§2.2)天然落到自己的 scene_id,
                # 不与其它讲解段共享同一张场景底图。
                event_id=line_id,
            )
        )
    return Script(lines=lines)


async def generate_narration_script(event_unit: EventUnit, *, llm: Any = None) -> Script:
    """EventUnit(narration 段)→ 讲解稿 Script。LLM 调用失败 → 返回空壳(降级,不阻塞)。"""
    narration_segments = [s for s in event_unit.segments if s.type == "narration"]
    if not narration_segments:
        return Script(lines=[])

    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = _build_narration_prompt(event_unit)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("narration_script 生成 LLM 调用失败,返回空壳: %s", e)
        draft = {}
    return _coerce_script(draft)

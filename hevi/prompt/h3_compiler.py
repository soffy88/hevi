"""H3 prompt 编译器 —— 镜头契约 → H3 三段式 render(L1/L4 边界,hevi 纪律)。

MiniMax H3 的提示词是**三段式**(ComfyUI `MiniMaxH3ReferenceToVideo` 单 prompt 字段
内联分段,官方 r2v 模板即如此):

    integrated_multimodal_description
        【场景】… 【人物】… 【动作】… 【对白】… (画面 + 动作 + 对白)
    overall_soundscape
        环境音(无音乐)
    non_diegetic_music
        情绪配乐(压人声)

hevi 纪律:
  - 只消费 Director 已锁定的镜头契约(`ShotListItem` 同构对象),不再写第二套分镜引擎。
  - `prompt_language=zh` → 中文直出,**禁止**再走 SDXL 那套英译漏斗——本模块不做任何
    翻译调用,输出即 render 三字段,可直接喂 H3。
  - 一镜一句对白;多句应在分镜阶段拆开(这里只告警不静默截断)。
  - 对白带 quote_id 溯源标记(`[q:…]`),守 hevi 史实/溯源红线。
  - S 编号由调用方传入的 cast(S 号 → 角色名,全片稳定),编译器不自行分配。

纯逻辑、无 IO、无网络 —— 可无 DB 单测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: H3 对白段起始标记(照官方示例写法)。
_DIALOGUE_PREFIX = "<d>[Chinese] "
_DIALOGUE_SUFFIX = "</d>"
#: 一镜一句;超出的对白行不进 render(告警,由分镜阶段拆开)。
_MAX_DIALOGUE_LINES = 1

#: 环境音缺省文案(空镜也可用;无音乐)。
_DEFAULT_SOUNDSCAPE = "环境声:自然的环境氛围音,无对白,无音乐"
#: 配乐缺省文案(压人声)。
_DEFAULT_MUSIC = "情绪配乐:轻柔的氛围音乐,音量压低,不盖过对白"


@dataclass
class H3Render:
    """H3 三段式 render。to_dict() 直出 provider 消费的字段。"""

    integrated_multimodal_description: str
    overall_soundscape: str = _DEFAULT_SOUNDSCAPE
    non_diegetic_music: str = _DEFAULT_MUSIC

    def to_dict(self) -> dict[str, str]:
        return {
            "integrated_multimodal_description": self.integrated_multimodal_description,
            "overall_soundscape": self.overall_soundscape,
            "non_diegetic_music": self.non_diegetic_music,
        }

    @staticmethod
    def from_dict(data: Any) -> H3Render:
        """从 dict(LLM 或 JSON)还原;缺字段回落默认。非 dict 输入 → 整段当 integrated。"""
        if isinstance(data, dict):
            return H3Render(
                integrated_multimodal_description=str(
                    data.get("integrated_multimodal_description")
                    or data.get("prompt")
                    or data.get("integrated", "")
                ),
                overall_soundscape=str(
                    data.get("overall_soundscape") or data.get("soundscape") or _DEFAULT_SOUNDSCAPE
                ),
                non_diegetic_music=str(
                    data.get("non_diegetic_music") or data.get("music") or _DEFAULT_MUSIC
                ),
            )
        return H3Render(integrated_multimodal_description=str(data or ""))


# ── 段构造(纯字符串,便于单测逐段断言)─────────────────────────────────────


def scene_block(*, scene_name: str, scene_description: str = "") -> str:
    desc = f": {scene_description}" if scene_description else ""
    return f"【场景】{scene_name or '未命名场景'}{desc}。"


def character_block(*, name: str, s_no: int, anchor: str = "", shot_size: str = "") -> str:
    """【人物】名(S{n},锚点)+ 景别。anchor 只放短锚点,不重复整段母卡描述。"""
    s = f"（S{s_no}"
    if anchor:
        s += f"，{anchor}"
    s += "）"
    if shot_size:
        s += f"，{shot_size}"
    return f"【人物】{name}{s}"


def action_block(*, action_beats: list[str] | None = None, visual_prompt: str = "") -> str:
    """【动作】优先动作弧(action_beats);为空回落 visual_prompt。"""
    if action_beats:
        return "【动作】" + "；".join(b for b in action_beats if b) + "。"
    return f"【动作】{visual_prompt or '自然动态' }。"


def dialogue_block(*, name: str, s_no: int, text: str, quote_id: str = "") -> str:
    """【对白】一行:
        (S1) 名说道:
        <d>[Chinese] 短对白。</d>
    quote_id 给定时追加 [q:{quote_id}] 溯源标记(守史实/溯源红线)。
    """
    line = f"（S{s_no}）{name}说道：\n{_DIALOGUE_PREFIX}{text}{_DIALOGUE_SUFFIX}"
    if quote_id:
        line += f"[q:{quote_id}]"
    return line


# ── 主编译器 ────────────────────────────────────────────────────────────────


def compile_h3_prompt(
    *,
    shot: Any,
    cast: dict[str, int],
    scene_block_text: str = "",
    quote_id: str = "",
    soundscape: str = "",
    music: str = "",
) -> H3Render:
    """Director 镜头契约(ShotListItem 同构对象)→ H3 三段式 render。

    Args:
        shot: 镜头契约。读取字段(缺省安全,鸭子类型):
            - scene_name / scene_description(场景名与描述,来自锁定 DesignScene)
            - shot_size / camera(景别/机位,拼进【场景】或【人物】)
            - character_names(本镜出场角色名,顺序即 S 号来源的键)
            - visual_prompt(画面描述,动作弧缺省时兜底)
            - action_beats(动作弧)
            - dialogue_lines(ShotListDialogueLine 同构:[{character_name, text, target_name}])
        cast: 角色名 → S 号(1 基,全片稳定;由 cast_map/Subject 适配层给出)。
            镜头里只出现 cast 里的角色;找不到的角色按 0 处理并在日志告警。
        scene_block_text: 外部给出的【场景】段(通常来自场景 Subject 的描述),
            为空则用 shot 字段现场拼。
        quote_id: 对白溯源标记(史实/引用红线),追加到对白行。
        soundscape / music: 覆盖缺省环境音/配乐文案。

    Returns:
        H3Render: 三段式,to_dict() 可直喂 h3_local provider。
    """
    scene_name = getattr(shot, "scene_name", "") or ""
    scene_desc = getattr(shot, "scene_description", "") or getattr(shot, "scene_mood", "") or ""
    shot_size = getattr(shot, "shot_size", "") or ""
    camera = getattr(shot, "camera", "") or ""

    # 场景段:外部锁定文案优先(Subject 母卡),否则按 shot 字段拼。
    if not scene_block_text:
        scene_block_text = scene_block(scene_name=scene_name, scene_description=scene_desc)
    if camera:
        scene_block_text += f" 机位:{camera}。"

    # 人物段:本镜出场角色,按 cast 给 S 号。
    names = getattr(shot, "character_names", None) or []
    char_blocks: list[str] = []
    for n in names:
        s_no = cast.get(n, 0)
        if s_no <= 0:
            logger.warning("h3_compiler: 角色 %r 不在 cast 里(缺 S 号),按 S0 处理", n)
        anchor = getattr(shot, "character_anchor", "") or ""
        char_blocks.append(
            character_block(name=n, s_no=s_no, anchor=anchor, shot_size=shot_size)
        )
    if not char_blocks:
        char_blocks.append(character_block(name="人物", s_no=1, shot_size=shot_size))

    # 动作段。
    action = action_block(
        action_beats=getattr(shot, "action_beats", None) or None,
        visual_prompt=getattr(shot, "visual_prompt", "") or "",
    )

    # 对白段:一镜一句(超出告警,不静默拼接)。
    lines = getattr(shot, "dialogue_lines", None) or []
    dialogue = ""
    if lines:
        first = lines[0]
        if len(lines) > _MAX_DIALOGUE_LINES:
            logger.warning(
                "h3_compiler: 镜头 %r 有 %d 句对白,H3 一镜一句,只取第一句;"
                "多句应在分镜阶段拆开",
                getattr(shot, "shot_id", getattr(shot, "index", "?")),
                len(lines),
            )
        d_name = getattr(first, "character_name", "") or ""
        d_text = getattr(first, "text", "") or ""
        d_s = cast.get(d_name, 0)
        dialogue = "\n【对白】\n" + dialogue_block(
            name=d_name or "角色", s_no=d_s, text=d_text, quote_id=quote_id
        )

    integrated = "".join([scene_block_text, *char_blocks, action, dialogue])
    return H3Render(
        integrated_multimodal_description=integrated,
        overall_soundscape=soundscape or _DEFAULT_SOUNDSCAPE,
        non_diegetic_music=music or _DEFAULT_MUSIC,
    )

"""SPEC-003 分镜锁定覆盖 — 纯算法、stateless。

实现 SPEC §2 Task 2.1 要求的 ``apply_locked_storyboard_override``:

    组合原始 Script 与 SPEC-003 导演锁定的分镜数据, 输出确定性分镜列表

本模块为 **纯算法层**(无 LLM 调用、无 IO、无运行期钩子替换),输入锁定分镜
数据,输出 oskill 原生 schema 兼容的确定性规划结果。此前该逻辑以运行期
``_providers_script_fn`` / ``_providers_storyboard_fn`` 替换的形式内嵌在
``hevi/pipeline/longvideo_orchestrator.py`` 中 —— 3O 迁移将其抽离为标准函数。

.. note::
   3O 迁移意图:该函数应最终上游至 ``oskill`` 主库(``oskill.storyboard_locked_override``),
   此处为 Hevi 项目侧的暂驻实现,函数签名与 SPEC §2 完全一致,便于平移到 oskill
   源码仓库时零改动。当前 oskill 主库版本 (4.5.0) 未包含该函数。
"""

from __future__ import annotations

import re
from typing import Any

from oskill.schemas import Chapter, ChapterScript, SpeakerLine, Storyboard

# 舞台提示/动作说明括号(中英文),如"（一把拽过胳膊）"——是给分镜看的动作描述,
# 不是要念出来或打进字幕的台词,配音/字幕两处都剥掉。
_STAGE_DIR_RE = re.compile(r"[（(][^）)]*[）)]")


def strip_stage_directions(text: str) -> str:
    """剥掉台词中的舞台提示括号(中英文)。"""
    return _STAGE_DIR_RE.sub("", text or "").strip()


def _speaker_lines(locked_shots: list[dict[str, Any]]) -> list[SpeakerLine]:
    """从锁定分镜提取有说话人的对白行。

    2026-07-14 用户要求:彻底不要旁白。只保留有说话人的对白行
    (character_name 非空);旁白行(character_name 为空)完全丢弃,不进配音轨。
    台词里的舞台提示括号也剥掉(不是要念的话)。speaker_id 用角色名,命中
    produce 传入的 character_voices 就换成该角色专属音色。
    """
    dialogues: list[SpeakerLine] = []
    for shot in locked_shots:
        for line in shot.get("dialogue_lines", []):
            speaker = (line.get("character_name") or "").strip()
            if not speaker:
                continue
            text = strip_stage_directions(line.get("text", ""))
            if text:
                dialogues.append(SpeakerLine(speaker_id=speaker, text=text))
    return dialogues


def _shot_plan_namespaces(locked_shots: list[dict[str, Any]]) -> list[Any]:
    """每一镜转成 ShotPlan 兼容对象(鸭子类型)。

    下游只按属性访问(shot_id/image_prompt/tts_text/duration_s),不需要真的是
    oskill.ShotPlan 实例。字幕同样只收有说话人的对白,且不带"角色名:" 前缀
    (像正片字幕那样只显示台词本身)。
    """
    from types import SimpleNamespace

    out: list[Any] = []
    for shot in locked_shots:
        dialogue_bits = [
            strip_stage_directions(ln.get("text", ""))
            for ln in shot.get("dialogue_lines", [])
            if (ln.get("character_name") or "").strip()
        ]
        dialogue_bits = [t for t in dialogue_bits if t]
        out.append(
            SimpleNamespace(
                shot_id=shot.get("shot_id", ""),
                image_prompt=shot.get("visual_prompt", ""),
                tts_text="。".join(dialogue_bits),
                duration_s=float(shot.get("duration_s") or 5.0),
            )
        )
    return out


def apply_locked_storyboard_override(
    script_data: dict[str, Any],
    locked_shots: list[dict[str, Any]],
) -> dict[str, Any]:
    """组合原始 Script 与 SPEC-003 导演锁定的分镜数据, 输出确定性分镜列表。

    Args:
        script_data: 原始 Script 数据(当前实现仅作兼容占位,不做 LLM 消费;
            锁定分镜已是唯一真相源)。
        locked_shots: SPEC-003 ④级人工审核锁定后的分镜列表,每项含
            shot_id / visual_prompt / dialogue_lines / duration_s 等字段。

    Returns:
        确定性规划结果字典:
        - ``chapter_script``: ``oskill.schemas.ChapterScript``(仅含对白行,
          供全片配音轨消费;character_voices 可据此按角色分配音色)。
        - ``storyboard``: 占位 ``oskill.schemas.Storyboard``(shots=[])——
          shot_gen_fn 分支直接消费 shot_plans,不读 storyboard 内容。
        - ``shot_plans``: ShotPlan 兼容对象列表(鸭子类型)。
    """
    dialogues = _speaker_lines(locked_shots)
    chapter = Chapter(chapter_id="locked", title="", scenes=[], dialogues=dialogues)
    chapter_script = ChapterScript(
        chapters=[chapter],
        total_duration_s=sum(float(s.get("duration_s") or 0) for s in locked_shots),
        characters=[],
    )
    return {
        "chapter_script": chapter_script,
        "storyboard": Storyboard(shots=[]),
        "shot_plans": _shot_plan_namespaces(locked_shots),
    }

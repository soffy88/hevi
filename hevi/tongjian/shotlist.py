"""L4 分镜 —— timeline + script + character_bible → shotlist.json。见 HEVI-SPEC-01 §6。

切分规则(确定性代码 + LLM 补充):
- 基础切分:每个 audio_segment 默认 1 个 shot
- 时长 > 8s 的段落由 LLM 决定拆成 2-3 个 shot(同场景变机位)
- shot 时长 = 音频切分决定,不由画面反推
- 每个 shot 绑定:scene_id / characters / camera / visual_prompt

G4 校验门(纯代码,无 LLM):
- 时间轴无缝:shots 的 [t_start, t_end] 精确覆盖 total_duration,无重叠无空洞
- characters ⊆ character_bible
- 视觉节奏:连续 3+ shot 同 scene_id 同 shot_size → 强制变化(防画面呆板)
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.tongjian.chapter_ir import _call_llm_json, _extract_json_obj
from hevi.tongjian.schemas import (
    AudioSegment,
    CharacterBible,
    GateResult,
    Script,
    ScriptLine,
    Shot,
    ShotCamera,
    ShotList,
    Timeline,
)

logger = logging.getLogger(__name__)

_LONG_SHOT_THRESHOLD_MS = 8000  # > 8s 的段落可拆分
_VALID_SHOT_SIZES = {"wide", "medium", "medium_close", "close_up", "extreme_close"}
_VALID_MOVEMENTS = {
    "static",
    "slow_push_in",
    "slow_pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
}
_MONOTONY_WINDOW = 3  # 连续 N 个同 scene+景别 → 强制变化


# ── 景别/运镜推断(确定性规则)──────────────────────────────────────────────


def _infer_camera(line: ScriptLine) -> ShotCamera:
    """根据 line.type 和 visual_hint 用确定性规则推断景别。"""
    hint = (line.visual_hint or "").lower()

    # dialogue → 中近景
    if line.type == "dialogue":
        size = "medium_close"
        movement = "static"
    # commentary(臣光曰) → 远景,缓推
    elif line.type == "commentary":
        size = "wide"
        movement = "slow_push_in"
    else:
        size = "medium"
        movement = "static"

    # visual_hint 关键词覆盖
    if "远景" in hint or "全景" in hint:
        size = "wide"
    elif "近景" in hint or "特写" in hint:
        size = "close_up"
    elif "中景" in hint:
        size = "medium"

    if "推" in hint:
        movement = "slow_push_in"
    elif "拉" in hint:
        movement = "slow_pull_out"
    elif "摇" in hint or "横移" in hint:
        movement = "pan_left"

    return ShotCamera(shot_size=size, movement=movement)


def _infer_scene_id(line: ScriptLine, prev_scene: str) -> str:
    """根据 event_id + visual_hint 推断 scene_id。

    P0 简单策略:event_id 变 → 新 scene;否则沿用上一个 scene。
    """
    if line.event_id and line.event_id != prev_scene:
        return line.event_id
    return prev_scene or "S001"


def _extract_characters(line: ScriptLine, bible: CharacterBible) -> list[str]:
    """从 line 中提取在场角色 ID。"""
    chars: list[str] = []
    # dialogue 行:speaker 即角色
    if line.type == "dialogue" and line.speaker != "NARRATOR":
        chars.append(line.speaker)
    # visual_hint 中提及的角色
    for entry in bible.characters:
        if entry.name and line.visual_hint and entry.name in line.visual_hint:
            if entry.character_id not in chars:
                chars.append(entry.character_id)
    return chars


def _build_visual_prompt(line: ScriptLine) -> str:
    """组合 visual_hint + text 生成 visual_prompt。"""
    if line.visual_hint:
        return line.visual_hint
    # 回退:用 text 的前 50 字作为视觉描述
    return line.text[:50] if line.text else ""


# ── LLM 拆分长 shot ──────────────────────────────────────────────────────


_SPLIT_PROMPT_TEMPLATE = """你是短视频分镜师。下面这段音频对应一行旁白,时长 {duration_ms}ms(超过 8 秒)。
请将它拆成 2-3 个子镜头(shot),每个子镜头分配不同的景别和运镜,以避免画面呆板。

原文: {text}
画面提示: {visual_hint}

只输出 JSON:
{{"sub_shots": [
  {{"fraction": 0.5, "shot_size": "wide|medium|medium_close|close_up", "movement": "static|slow_push_in|slow_pull_out|pan_left", "visual_prompt": "这个子镜头的画面描述"}}
]}}

注意:fraction 是各子镜头占总时长的比例,所有 fraction 之和必须 = 1.0。"""


async def _split_long_shot(
    seg: AudioSegment,
    line: ScriptLine,
    base_shot: Shot,
    *,
    llm: Any,
) -> list[Shot]:
    """用 LLM 将长 shot 拆分为 2-3 个子 shot。失败 → 返回原单 shot(降级)。"""
    prompt = _SPLIT_PROMPT_TEMPLATE.format(
        duration_ms=seg.duration_ms,
        text=line.text,
        visual_hint=line.visual_hint or "(无)",
    )
    try:
        resp = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("L4: 长 shot %s LLM 拆分失败,保持单 shot: %s", base_shot.shot_id, e)
        return [base_shot]

    sub_shots_data = resp.get("sub_shots") or []
    if len(sub_shots_data) < 2:
        return [base_shot]

    # 归一化 fraction
    total_frac = sum(float(s.get("fraction", 0)) for s in sub_shots_data)
    if total_frac <= 0:
        return [base_shot]

    result: list[Shot] = []
    cursor_ms = base_shot.t_start_ms
    base_id = base_shot.shot_id

    for i, sub in enumerate(sub_shots_data):
        frac = float(sub.get("fraction", 0)) / total_frac
        duration = round(seg.duration_ms * frac)
        shot_size = str(sub.get("shot_size", "medium"))
        if shot_size not in _VALID_SHOT_SIZES:
            shot_size = "medium"
        movement = str(sub.get("movement", "static"))
        if movement not in _VALID_MOVEMENTS:
            movement = "static"

        result.append(
            Shot(
                shot_id=f"{base_id}_{i + 1:02d}",
                line_ids=base_shot.line_ids,
                t_start_ms=cursor_ms,
                t_end_ms=cursor_ms + duration,
                scene_id=base_shot.scene_id,
                characters=base_shot.characters,
                camera=ShotCamera(shot_size=shot_size, movement=movement),
                visual_prompt=str(sub.get("visual_prompt", base_shot.visual_prompt)),
                motion_mode=base_shot.motion_mode,
            )
        )
        cursor_ms += duration

    # 修正最后一个 shot 的 t_end 精确对齐
    if result:
        result[-1] = result[-1].model_copy(update={"t_end_ms": base_shot.t_end_ms})

    return result


# ── 主合成 ─────────────────────────────────────────────────────────────────


async def generate_shotlist(
    timeline: Timeline,
    script: Script,
    character_bible: CharacterBible,
    *,
    llm: Any = None,
    split_long_shots: bool = True,
) -> ShotList:
    """timeline + script + character_bible → ShotList。

    基础切分:每个 audio_segment 对应 1 个 shot;
    长 shot (>8s) 由 LLM 拆分为 2-3 个子 shot(仅换机位的静帧/i2v 管线受益)。

    split_long_shots=False:数字人(cloud_avatar)管线用——那里每镜按自己台词**重新生成音频**,
    拆分会让每个子镜头把整句各说一遍,同一句连播两三次 = 重复段落,故整体关闭拆分。
    """
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    lines_by_id = {ln.line_id: ln for ln in script.lines}
    gaps_by_after_line = {gap.after_line: gap for gap in timeline.gaps}
    shots: list[Shot] = []
    shot_idx = 0
    prev_scene = ""

    for seg in timeline.audio_segments:
        line = lines_by_id.get(seg.line_id)
        if line is None:
            continue

        shot_idx += 1
        scene_id = _infer_scene_id(line, prev_scene)
        camera = _infer_camera(line)
        characters = _extract_characters(line, character_bible)
        visual_prompt = _build_visual_prompt(line)

        base_shot = Shot(
            shot_id=f"SH{shot_idx:03d}",
            line_ids=[seg.line_id],
            t_start_ms=seg.t_start_ms,
            t_end_ms=seg.t_end_ms,
            scene_id=scene_id,
            characters=characters,
            camera=camera,
            visual_prompt=visual_prompt,
            motion_mode="ken_burns",
        )

        # 长 shot 拆分:只拆旁白/史论(风景空镜换机位防呆板)。对白行不拆——数字人已把整句演完,
        # 拆成子镜头会让每个子镜头都拿整句台词各渲一遍,同一角色同一句连播两三次 = 观感"重复段落"。
        # split_long_shots=False(数字人管线)则整体不拆(旁白同样会因重生成音频而重复)。
        if (
            split_long_shots
            and seg.duration_ms > _LONG_SHOT_THRESHOLD_MS
            and line.type != "dialogue"
        ):
            sub_shots = await _split_long_shot(seg, line, base_shot, llm=llm)
            shots.extend(sub_shots)
        else:
            shots.append(base_shot)

        prev_scene = scene_id

        # timeline.gaps(幕间空隙)也要有镜头覆盖,否则总时长留下无画面的空洞
        gap = gaps_by_after_line.get(seg.line_id)
        if gap is not None:
            shot_idx += 1
            shots.append(
                Shot(
                    shot_id=f"SH{shot_idx:03d}",
                    line_ids=[],
                    t_start_ms=seg.t_end_ms,
                    t_end_ms=seg.t_end_ms + gap.duration_ms,
                    scene_id=scene_id,
                    characters=[],
                    camera=ShotCamera(shot_size="wide", movement="static"),
                    visual_prompt=f"过场:{gap.purpose}",
                    motion_mode="static",
                    is_transition=True,
                )
            )

    return ShotList(shots=shots)


# ── G4 校验门 ─────────────────────────────────────────────────────────────


def gate_shotlist(
    shotlist: ShotList,
    timeline: Timeline,
    character_bible: CharacterBible,
) -> GateResult:
    """G4 门(纯代码,无 LLM)。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not shotlist.shots:
        errors.append("shotlist 为空,没有任何镜头")
        return GateResult(passed=False, errors=errors)

    # 1. 时间轴无缝校验
    _check_timeline_continuity(shotlist, timeline, errors)

    # 2. 角色引用闭环
    known_chars = {e.character_id for e in character_bible.characters}
    for shot in shotlist.shots:
        for cid in shot.characters:
            if cid not in known_chars:
                warnings.append(f"镜头 {shot.shot_id} 引用了 character_bible 中不存在的角色 {cid}")

    # 3. 视觉节奏:连续 N 个同 scene+景别 → 警告
    _check_visual_monotony(shotlist, warnings)

    coverage = 1.0  # 全部 shot 都校验了
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)


def _check_timeline_continuity(shotlist: ShotList, timeline: Timeline, errors: list[str]) -> None:
    """检查 shots 时间轴是否精确覆盖 total_duration(无重叠无空洞)。"""
    if not shotlist.shots:
        return

    sorted_shots = sorted(shotlist.shots, key=lambda s: s.t_start_ms)

    # 检查第一个 shot 是否从 0 开始(或从 timeline 的第一个 segment 开始)
    first_expected = timeline.audio_segments[0].t_start_ms if timeline.audio_segments else 0
    if sorted_shots[0].t_start_ms != first_expected:
        errors.append(
            f"第一个镜头 {sorted_shots[0].shot_id} 起始 {sorted_shots[0].t_start_ms}ms "
            f"!= 预期 {first_expected}ms"
        )

    # 检查相邻 shot 无缝衔接
    for i in range(1, len(sorted_shots)):
        prev_end = sorted_shots[i - 1].t_end_ms
        curr_start = sorted_shots[i].t_start_ms
        if curr_start != prev_end:
            gap = curr_start - prev_end
            if gap > 0:
                errors.append(
                    f"镜头 {sorted_shots[i - 1].shot_id} 和 {sorted_shots[i].shot_id} "
                    f"之间有 {gap}ms 空洞"
                )
            else:
                errors.append(
                    f"镜头 {sorted_shots[i - 1].shot_id} 和 {sorted_shots[i].shot_id} "
                    f"之间有 {-gap}ms 重叠"
                )


def _check_visual_monotony(shotlist: ShotList, warnings: list[str]) -> None:
    """连续 N 个 shot 同 scene_id + 同 shot_size → 警告。"""
    if len(shotlist.shots) < _MONOTONY_WINDOW:
        return

    for i in range(len(shotlist.shots) - _MONOTONY_WINDOW + 1):
        window = shotlist.shots[i : i + _MONOTONY_WINDOW]
        scenes = {s.scene_id for s in window}
        sizes = {s.camera.shot_size for s in window}
        if len(scenes) == 1 and len(sizes) == 1:
            warnings.append(
                f"镜头 {window[0].shot_id}-{window[-1].shot_id} "
                f"连续 {_MONOTONY_WINDOW} 个同场景({window[0].scene_id})"
                f"同景别({window[0].camera.shot_size}),建议变化"
            )


# ── 主入口 ─────────────────────────────────────────────────────────────────


async def build_shotlist(
    timeline: Timeline,
    script: Script,
    character_bible: CharacterBible,
    *,
    llm: Any = None,
    split_long_shots: bool = True,
) -> tuple[ShotList, GateResult]:
    """L4 主入口:生成 → G4 门。"""
    shotlist = await generate_shotlist(
        timeline,
        script,
        character_bible,
        llm=llm,
        split_long_shots=split_long_shots,
    )
    result = gate_shotlist(shotlist, timeline, character_bible)
    return shotlist, result

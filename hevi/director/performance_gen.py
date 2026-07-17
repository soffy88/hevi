"""INC-002 生成器 —— 把一个镜头(ShotListItem)拆成镜头内部的表演时间轴(performance_track)。

按密度档 tier 生成不同深度(L1 eyeline+emotional+body / L2 +facial+camera / L3 +muscle);
生成后**自动归一化时间窗**(用每段声明的相对时长无缝铺排到 [0, 时长],保证 P1 恒过),再跑 lint
把剩余问题(视线跳变/泪水倒流等)记进日志。tier=L0 → 不生成(返回 None,inert,走 action_beats 老路)。

与 performance_track.py 的分工:那边是纯编译/校验(无 LLM),这边是 LLM 生成(镜像 shot_list.py
的 _call_llm_json 约定)。生成的 track 存回 ShotListItem.performance_track,下游桥接自动编译成
时序提示词。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from hevi.director.performance_track import lint_performance_track
from hevi.director.pipeline_schemas import PerformancePhase, PerformanceTrack, ShotListItem

logger = logging.getLogger(__name__)

# 各密度档要 LLM 填哪些块(L0 不生成)。低档不问高档字段,省 token 也避免产出被降采样丢弃。
_TIER_BLOCKS = {
    "L1": ("eyeline", "emotional", "body"),
    "L2": ("eyeline", "emotional", "body", "facial", "camera"),
    "L3": ("eyeline", "emotional", "body", "facial", "camera", "muscle"),
}

_FACIAL_SPEC = (
    "- facial_performance:{{physiology:{{tear_state:none/welling/film/brimming/falling/dried"
    "(**必须逐级演化不可倒流/跳跃**),eye_vasculature:clear/faint/congested,"
    "pupil:{{dilation:0-1,movement}},blink:none/normal/rapid/forced_open/closing,swallow:bool,"
    "lip_state:pressed/parting/trembling/slack,skin_flush:none/cheeks/neck}},"
    "skin_texture:{{quality:natural_imperfect/clean/weathered,pores,sweat,preserve_base_tone}}}}"
)
_MUSCLE_SPEC = (
    "  facial_performance.muscle_actions:[{{muscle:corrugator/masseter/orbicularis_oculi/...,"
    "action:contract/relax/twitch/tremor,intensity:0-1,visible_result:'可观察结果如眉头痛苦紧皱'}}]"
)
_CAMERA_SPEC = (
    "- camera_curve:{{handheld:{{enabled,frequency_start,frequency_end(0-1,**跨段边界须连续**),"
    "amplitude_start,amplitude_end,easing:linear/ease_in/ease_out/accelerate}},"
    "focus:{{lock_target,lock_strictness:absolute/soft/rack,rack_to(absolute 时留空),"
    "depth_of_field}},"
    "movement:{{type:static/push_in/pull_out/pan/tilt/follow,speed_start,speed_end}},"
    "breathing:{{enabled,sync_to:none/character_breath/emotional_intensity}}}}"
)

_BASE_PROMPT = """你是电影表演设计师。把下面这**一个镜头**拆成"镜头内部的表演时间轴"——把 {duration}
秒切成若干段(通常 3-6 段),每段一个情绪/动作节拍,让镜头内部有连续演化而不是一个静态表情。

镜头:
- 时长:{duration}s
- 画面:{visual}
- 动作弧:{action_beats}
- 对白:{dialogue}
- 出场:{characters}

每段(phase)给:
- t_start_s/t_end_s:时间窗(秒)。尽量首段从 0、段段相接、末段到 {duration}(系统会再归一化)。
- label:这一段在演什么;trigger:由什么触发
- eyeline_track:{{state:locked/breaking/averted/returning/closed,direction:center/down/down_left/
  down_right/up/left/right,target_ref:看向谁,transition_speed:snap/quick/slow/trembling}}
  **视线状态相邻演化(locked→breaking→averted→returning),跳变必须 transition_speed=snap**
- emotional_state:{{primary:主情绪,intensity:0-1,conflict_with:内心对立面或空}}
- body:{{posture,tension:rigid/taut/trembling/slack/collapsing,
  breath:held/shallow_rapid/ragged/deep}}
{extra_specs}

只输出 JSON:{{"total_duration_s":{duration},"phases":[{{"phase_id":"ph1","order":1,"t_start_s":0,
"t_end_s":...,"label":"...","trigger":"...","eyeline_track":{{...}},"emotional_state":{{...}},
"body":{{...}}}}]}}"""


def _resolve_llm(llm: Any) -> Any:
    if llm is not None:
        return llm
    from obase.provider_registry import ProviderRegistry

    try:
        return ProviderRegistry.get().llm("qwen_cloud")
    except Exception:
        return ProviderRegistry.get().llm("default")


async def _call_llm_json(llm: Any, prompt: str) -> dict[str, Any]:
    # 见 shot_list.py 同名函数:qwen_cloud 适配器构造即同步发 HTTP,放线程池才真并发。
    def _invoke() -> Any:
        return llm(messages=[{"role": "user", "content": prompt}], max_tokens=6144)

    # L2/L3 每段要面部+运镜细节,输出长、qwen 实测常超 45s(空 TimeoutError 静默吃 None)。
    # perf-gen 跑在后台路径(_run_shot_list_*,非同步 HTTP,无 Cloudflare 100s 限),给足 120s。
    obj = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=120.0)
    resp = await obj if hasattr(obj, "__await__") else obj
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _normalize_time_windows(phases: list[PerformancePhase], total: float) -> None:
    """用每段声明的相对时长把时间窗无缝铺排到 [0, total],保证 P1 恒过(就地改)。LLM 的时间窗
    常有缝隙/重叠——与其拒绝,不如把它的相对节奏保住、时间轴钉直。"""
    if not phases or total <= 0:
        return
    durs = [max(0.01, p.t_end_s - p.t_start_s) for p in phases]
    span = sum(durs)
    t = 0.0
    for p, d in zip(phases, durs, strict=False):
        p.t_start_s = round(t, 3)
        t += d / span * total
        p.t_end_s = round(t, 3)
    phases[-1].t_end_s = total  # 消除浮点残差


def _build_prompt(shot: ShotListItem, tier: str) -> str:
    blocks = _TIER_BLOCKS.get(tier, ())
    extra = []
    if "facial" in blocks:
        extra.append(_FACIAL_SPEC)
    if "muscle" in blocks:
        extra.append(_MUSCLE_SPEC)
    if "camera" in blocks:
        extra.append(_CAMERA_SPEC)
    dialogue = " / ".join(
        f"{d.character_name or '旁白'}:{d.text}" for d in shot.dialogue_lines if d.text
    )
    return _BASE_PROMPT.format(
        duration=shot.duration_s or 5.0,
        visual=shot.visual_prompt or "(无)",
        action_beats=";".join(shot.action_beats) or "(无)",
        dialogue=dialogue or "(无对白)",
        characters="、".join(shot.character_names) or "(无)",
        extra_specs="\n".join(extra),
    )


async def generate_performance_track(
    *, shot: ShotListItem, tier: str = "L2", llm: Any = None
) -> PerformanceTrack | None:
    """一个镜头 → performance_track。tier=L0 或生成/解析失败 → None(inert,走 action_beats 老路)。"""
    if tier not in _TIER_BLOCKS:  # L0 或未知档
        return None
    resolved = _resolve_llm(llm)
    try:
        data = await _call_llm_json(resolved, _build_prompt(shot, tier))
    except Exception as e:
        logger.warning("performance_track 生成失败 shot=%s: %s", shot.shot_id, e)
        return None
    if not isinstance(data.get("phases"), list) or not data["phases"]:
        return None
    try:
        track = PerformanceTrack.model_validate(data)
    except Exception as e:
        logger.warning("performance_track 解析失败 shot=%s: %s", shot.shot_id, e)
        return None
    total = track.total_duration_s or shot.duration_s or 5.0
    track.total_duration_s = total
    for i, ph in enumerate(track.phases, 1):
        if not ph.phase_id:
            ph.phase_id = f"ph{i}"
        ph.order = ph.order or i
    _normalize_time_windows(track.phases, total)
    findings = lint_performance_track(track, shot_id=shot.shot_id)
    if findings:
        logger.info(
            "performance_track shot=%s 有 %d 条 lint 提示:%s",
            shot.shot_id,
            len(findings),
            "; ".join(f"{f.rule}:{f.message}" for f in findings[:3]),
        )
    return track


async def enrich_shot_list_with_performance(
    shots: list[ShotListItem], *, tier: str = "L2", llm: Any = None
) -> list[ShotListItem]:
    """给每个镜头并发生成 performance_track(就地写回 shot.performance_track)。tier=L0 → 原样返回
    (不生成,inert)。单镜失败只该镜为空,不拖累整体。"""
    if tier not in _TIER_BLOCKS or not shots:
        return shots
    resolved = _resolve_llm(llm)
    tracks = await asyncio.gather(
        *(generate_performance_track(shot=s, tier=tier, llm=resolved) for s in shots)
    )
    for shot, track in zip(shots, tracks, strict=False):
        shot.performance_track = track
    return shots

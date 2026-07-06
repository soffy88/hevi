"""L7 音乐与音效 —— constitution + timeline + shotlist → music_plan.json。
见 HEVI-SPEC-01 §8。纯确定性代码,无 LLM、无 GPU。

MVP 用预置曲库(hevi.audio.bgm_library.BGMLibrary,纯文件系统):按幕情绪
(Act.emotion_curve,辅以 Constitution.bgm_mood_arc 同位置条目)选 BGM;音效
按 shot.visual_prompt 关键词稀疏匹配(宁缺毋滥)。幕的时间范围从 timeline.gaps
反推(L3 synthesize_voiceover 在每次 act 切换处插入 gap,顺序即幕切换顺序),
供装配阶段(L8)定位交叉淡入淡出点。

G7 校验门(纯代码,无 LLM):每幕必须选到存在的 BGM 文件;响度检查(ffprobe)。

已知限制(P1,均在 scripts/gen_placeholder_*.py 里有说明——换真实素材零代码改动):
- BGM 情绪目录目前只有 5 个通用英文标签(warm/upbeat/tense/epic/mystery),中文
  情绪词(肃杀/攀升/余韵等)靠关键词映射表近似对应,不是真正的情绪向量匹配。
- SFX 资产目前只有 5 个通用占位音效(whoosh/ding/impact/pop/chime),不是 spec
  举例的历史音效(战鼓/钟声/竹简展开)。
"""

from __future__ import annotations

import logging
from pathlib import Path

from hevi.audio.bgm_library import BGMLibrary
from hevi.tongjian.schemas import (
    Constitution,
    GateResult,
    MusicCue,
    MusicPlan,
    SfxCue,
    ShotList,
    Timeline,
)

logger = logging.getLogger(__name__)

_MOOD_KEYWORD_MAP: dict[str, str] = {
    "肃杀": "tense",
    "压抑": "tense",
    "紧张": "tense",
    "悲壮": "tense",
    "沉重": "tense",
    "攀升": "epic",
    "激昂": "epic",
    "冲突": "epic",
    "高潮": "epic",
    "壮阔": "epic",
    "余韵": "warm",
    "感伤": "warm",
    "怀念": "warm",
    "平静": "warm",
    "收尾": "warm",
    "悬疑": "mystery",
    "诡谲": "mystery",
    "阴谋": "mystery",
    "轻快": "upbeat",
    "欢快": "upbeat",
}
_DEFAULT_MOOD_DIR = "warm"

_SFX_KEYWORD_MAP: dict[str, str] = {
    "鼓": "impact",
    "兵": "impact",
    "剑": "impact",
    "戈": "impact",
    "战": "impact",
    "钟": "ding",
    "铃": "ding",
    "竹简": "whoosh",
    "风": "whoosh",
    "展开": "whoosh",
}

_LOUDNESS_TARGET_LUFS = -18.0
_LOUDNESS_TOLERANCE = 6.0  # 曲库素材响度参差不齐,容忍范围比 L3 配音(±3dB)宽


def _map_mood_to_dir(mood_text: str) -> str:
    for cn, en in _MOOD_KEYWORD_MAP.items():
        if cn in mood_text:
            return en
    return _DEFAULT_MOOD_DIR


def _match_sfx_name(visual_prompt: str) -> str | None:
    for cn, name in _SFX_KEYWORD_MAP.items():
        if cn in visual_prompt:
            return name
    return None


def _act_time_ranges(timeline: Timeline, num_acts: int) -> list[tuple[int, int]]:
    """按 timeline.gaps 出现顺序切出每一幕的 [t_start, t_end)。

    L3 synthesize_voiceover 只在 act 变化处插入 gap,顺序天然对应幕切换顺序,
    不需要额外的 line→act 映射。gap 的静音段并入下一幕开头(由音乐覆盖过渡)。
    """
    if num_acts <= 0:
        return []
    if not timeline.audio_segments:
        return [(0, 0) for _ in range(num_acts)]

    gaps_after = {g.after_line for g in timeline.gaps}
    ranges: list[tuple[int, int]] = []
    act_start = 0
    for seg in timeline.audio_segments:
        if seg.line_id in gaps_after and len(ranges) < num_acts - 1:
            ranges.append((act_start, seg.t_end_ms))
            act_start = seg.t_end_ms

    ranges.append((act_start, timeline.total_duration_ms))
    while len(ranges) < num_acts:
        ranges.append((ranges[-1][1], ranges[-1][1]))
    return ranges[:num_acts]


def generate_music_plan(
    shotlist: ShotList,
    timeline: Timeline,
    constitution: Constitution,
    *,
    bgm_lib: BGMLibrary | None = None,
) -> MusicPlan:
    """幕情绪 → BGM;shot 视觉关键词 → 稀疏 SFX 点缀。"""
    bgm_lib = bgm_lib or BGMLibrary()

    acts = constitution.act_structure
    time_ranges = _act_time_ranges(timeline, len(acts))

    cues: list[MusicCue] = []
    for act, (t_start, t_end) in zip(acts, time_ranges, strict=True):
        mood_text = act.emotion_curve
        if 0 <= act.act - 1 < len(constitution.bgm_mood_arc):
            mood_text = f"{mood_text} {constitution.bgm_mood_arc[act.act - 1]}"
        mood_dir = _map_mood_to_dir(mood_text)
        bgm_path = bgm_lib.select_bgm(mood_dir)
        cues.append(
            MusicCue(
                act=act.act,
                mood=act.emotion_curve,
                bgm_path=str(bgm_path) if bgm_path else "",
                t_start_ms=t_start,
                t_end_ms=t_end,
            )
        )

    sfx: list[SfxCue] = []
    for shot in shotlist.shots:
        if not shot.visual_prompt:
            continue
        name = _match_sfx_name(shot.visual_prompt)
        if name is None:
            continue
        sfx_path = bgm_lib.get_sfx(name)
        if sfx_path is None:
            continue
        sfx.append(
            SfxCue(
                shot_id=shot.shot_id,
                sfx_name=name,
                sfx_path=str(sfx_path),
                t_start_ms=shot.t_start_ms,
            )
        )

    return MusicPlan(cues=cues, sfx=sfx)


async def _measure_lufs(path: Path) -> float | None:
    """ffmpeg loudnorm 探测整合响度(同 voiceover.py 的做法,独立实现:这里探测的是
    曲库素材文件而非合成音频,场景不同不复用私有函数)。
    """
    import asyncio
    import json as _json

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            "loudnorm=print_format=json",
            "-f",
            "null",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        text = stderr.decode(errors="replace")
        brace_start = text.rfind("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            data = _json.loads(text[brace_start:brace_end])
            return float(data.get("input_i", _LOUDNESS_TARGET_LUFS))
    except Exception as e:
        logger.warning("BGM 响度探测失败 (%s): %s", path, e)
    return None


async def gate_music_plan(plan: MusicPlan, constitution: Constitution) -> GateResult:
    """G7 门:每幕必须有存在的 BGM 文件(错误);响度/无音效只报 warning。"""
    errors: list[str] = []
    warnings: list[str] = []
    acts_covered = 0

    cues_by_act = {c.act: c for c in plan.cues}
    for act in constitution.act_structure:
        cue = cues_by_act.get(act.act)
        if cue is None or not cue.bgm_path:
            errors.append(f"第{act.act}幕未匹配到任何 BGM(情绪={act.emotion_curve!r})")
            continue
        if not Path(cue.bgm_path).exists():
            errors.append(f"第{act.act}幕 BGM 文件不存在: {cue.bgm_path}")
            continue
        acts_covered += 1
        lufs = await _measure_lufs(Path(cue.bgm_path))
        if lufs is not None and abs(lufs - _LOUDNESS_TARGET_LUFS) > _LOUDNESS_TOLERANCE:
            warnings.append(
                f"第{act.act}幕 BGM 响度 {lufs:.1f} LUFS 偏离目标 {_LOUDNESS_TARGET_LUFS} 较大"
            )

    if not plan.sfx:
        warnings.append("全片没有匹配到任何音效(可能是正常的『宁缺毋滥』,也可能是关键词库需要扩充)")

    total_acts = len(constitution.act_structure)
    coverage = (acts_covered / total_acts) if total_acts else 1.0
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)


async def build_music_plan(
    shotlist: ShotList,
    timeline: Timeline,
    constitution: Constitution,
    *,
    bgm_lib: BGMLibrary | None = None,
) -> tuple[MusicPlan, GateResult]:
    """L7 主入口:生成 → G7 门。"""
    plan = generate_music_plan(shotlist, timeline, constitution, bgm_lib=bgm_lib)
    result = await gate_music_plan(plan, constitution)
    return plan, result

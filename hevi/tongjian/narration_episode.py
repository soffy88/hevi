"""讲解段装配 —— SPEC-005 §2、§6 第一批。EventUnit(narration 段)→ 纯讲解版成片。

不需要角色 Subject / SceneStage / 分镜 / 多人同框 / i2v ——全部复用现有 L3/L4/L6/L8 执行层
(voiceover.py / shotlist.py / scene_render.py / assemble.py),只新增"从原文到讲解 Script"
这一段产出侧(narration_script.py)与 image_gen 的地图/时间线分发。不跑 L1 立意生成
(constitution.py)——讲解段不需要戏剧立意,直接给一个够用的 Constitution 壳。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.audio.edge_tts_custom import NARRATOR_VOICE
from hevi.tongjian.assemble import build_final_video
from hevi.tongjian.gates import lint_shot_pacing
from hevi.tongjian.narration_script import DIAGRAM_MARKER_RE, generate_narration_script
from hevi.tongjian.scene_render import build_frame_manifest
from hevi.tongjian.schemas import (
    CharacterBible,
    Constitution,
    EventUnit,
    FinalVideo,
    GateResult,
    MusicPlan,
    Script,
    VisualStyle,
)
from hevi.tongjian.shotlist import build_shotlist
from hevi.tongjian.voiceover import build_voiceover

_DIAGRAM_RENDERERS = {"map": "render_map_diagram", "timeline": "render_timeline_diagram"}


def _build_constitution(event_unit: EventUnit, script: Script) -> Constitution:
    """讲解段不跑 L1 立意生成——直接给一个够用的壳。target_duration 优先按**实际生成的**
    讲解稿字数估算——narration_script 允许意译/展开/补背景(§1.2),生成稿字数常显著多于
    原文 segments 估算(2026-07-18 真机验证实测:原文仅"卒下令"4字,LLM 展开成 6 段近
    300 字讲解稿,若以原文估算为准会把 target_duration 定成 1 秒,拿真实 47 秒配音去比,
    直接判超差 4599%)。script 为空(LLM 生成失败的降级场景)才退回原文 segments 估算。
    """
    est_from_script = round(sum(len(ln.text) for ln in script.lines) / 4.5 / 0.85)
    est_from_segments = sum(s.est_duration_s for s in event_unit.segments if s.type == "narration")
    return Constitution(
        thesis=event_unit.summary,
        visual_style=VisualStyle(art_direction="水墨写意"),
        target_duration_sec=est_from_script or est_from_segments or 60,
        bgm_mood_arc=[],
    )


def _make_image_gen_dispatcher(*, scene_image_gen: Any, event_unit: EventUnit) -> Any:
    """按 visual_hint 里的 [DIAGRAM:map|timeline] 标记(见 narration_script.py 顶部注释)
    在确定性图表生成(diagram_gen)与常规场景生成/检索(scene_image_gen)间分发。
    """
    from hevi.tongjian import diagram_gen

    diagram_extra = {
        "title": event_unit.title,
        "era": event_unit.era,
        "year": event_unit.year,
    }

    async def dispatcher(
        *, prompt: str, output_path: Any, seed: int | None = None, extra: Any = None, **kw: Any
    ):
        m = DIAGRAM_MARKER_RE.search(prompt or "")
        if m:
            renderer = getattr(diagram_gen, _DIAGRAM_RENDERERS[m.group(1)])
            stripped_prompt = DIAGRAM_MARKER_RE.sub("", prompt)
            return await renderer(
                prompt=stripped_prompt, output_path=output_path, seed=seed, extra=diagram_extra
            )
        return await scene_image_gen(
            prompt=prompt, output_path=output_path, seed=seed, extra=extra or {}
        )

    return dispatcher


async def build_narration_episode(
    event_unit: EventUnit,
    *,
    llm: Any = None,
    tts_fn: Any = None,
    image_gen: Any = None,
    vlm: Any = None,
    output_dir: Path,
) -> tuple[FinalVideo, GateResult]:
    """EventUnit(narration 段)→ 纯讲解版成片。§5.3 G-T1 里"纯讲解版 5 分钟能出"的主入口。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    script = await generate_narration_script(event_unit, llm=llm)
    constitution = _build_constitution(event_unit, script)

    timeline, voiceover_gate = await build_voiceover(
        script,
        constitution,
        output_dir=output_dir / "audio",
        tts_fn=tts_fn,
        voice_by_speaker={"NARRATOR": NARRATOR_VOICE},
    )

    shotlist, shotlist_gate = await build_shotlist(
        timeline,
        script,
        CharacterBible(characters=[]),
        llm=llm,
        split_long_shots=False,
    )
    pacing_lint = lint_shot_pacing(shotlist)

    if image_gen is None:
        from obase.provider_registry import ProviderRegistry

        image_gen = ProviderRegistry.get().image_gen("sdxl_local")
    dispatcher = _make_image_gen_dispatcher(scene_image_gen=image_gen, event_unit=event_unit)

    frame_manifest, frame_gate = await build_frame_manifest(
        shotlist,
        CharacterBible(characters=[]),
        constitution,
        output_dir=output_dir / "frames",
        image_gen=dispatcher,
        vlm=vlm,
    )

    music_plan = MusicPlan(cues=[], sfx=[])

    final_video, assemble_gate = await build_final_video(
        shotlist,
        frame_manifest,
        timeline,
        script,
        music_plan,
        constitution,
        audio_dir=output_dir / "audio",
        output_dir=output_dir,
        vlm=vlm,
    )

    warnings = [
        *voiceover_gate.warnings,
        *shotlist_gate.warnings,
        *pacing_lint.warnings,
        *frame_gate.warnings,
        *assemble_gate.warnings,
    ]
    errors = [
        *voiceover_gate.errors,
        *shotlist_gate.errors,
        *frame_gate.errors,
        *assemble_gate.errors,
    ]
    gate_result = GateResult(passed=not errors, errors=errors, warnings=warnings)
    return final_video, gate_result

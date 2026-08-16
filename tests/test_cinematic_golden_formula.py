"""黄金公式分镜拆解 + 动画演绎分支单测。

覆盖:
  - LLM 按 [景别/运镜]+[主体+动作+表情]+[氛围/光线] 切 3-5s 分镜矩阵
  - 情绪降维: 抽象情绪词 → 视觉动作 (parse 层面保证字段填充)
  - shot_prompt 黄金公式拼装
  - shot_planning 把 Beat 黄金公式变量带进 CineShot prompt
  - C6 动画分支: 无身份包/参考图, 纯文生视频, CG6 跳过身份距离
"""

from __future__ import annotations

import pytest

from hevi.cinematic.golden_formula import (
    GoldenBeat,
    decompose_story_to_golden_beats,
    golden_beats_to_shot_prompts,
    parse_golden_beats,
)
from hevi.cinematic.schemas import Beat, CineShot, Scene
from hevi.cinematic.shot_planning import plan_shots
from hevi.cinematic.video_gen import _generate_attempt, _run_cg6


class _FakeLLM:
    """返回固定 JSON 的 LLM 替身。"""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def __call__(self, messages, **kwargs) -> str:
        return self._raw

    def chat(self, messages) -> str:
        return self._raw


_SIMGUA_JSON = """[
  {"shot_size": "medium", "movement": "pan", "subject": "司马光",
   "action": "在庭院里跑跳追逐", "emotion_expression": "嘴角上扬欢笑",
   "atmosphere": "轻松嬉戏", "lighting": "明亮日光", "duration_s": 3.0,
   "narration": "古代小孩在庭院中嬉戏"},
  {"shot_size": "close", "movement": "push_in", "subject": "小孩",
   "action": "掉入巨型水缸", "emotion_expression": "双手乱抓、双眼张大极度恐慌",
   "atmosphere": "惊慌", "lighting": "水花溅起", "duration_s": 4.0,
   "narration": "小孩掉入水缸"}
]"""


@pytest.mark.asyncio
async def test_decompose_uses_golden_formula():
    """LLM 输出 → GoldenBeat 矩阵, 字段齐全, 时长 3-5s。"""
    beats = await decompose_story_to_golden_beats("司马光砸缸", _FakeLLM(_SIMGUA_JSON))
    assert len(beats) == 2
    b = beats[0]
    assert b.shot_size == "medium"
    assert b.emotion_expression == "嘴角上扬欢笑"      # 情绪已视觉动作化
    assert b.lighting == "明亮日光"
    assert 3.0 <= b.duration_s <= 5.0
    assert "轻" in b.atmosphere


def test_shot_prompt_golden_formula_assembly():
    """shot_prompt = [景别/运镜]+[主体+动作+表情]+[氛围/光线]。"""
    b = GoldenBeat(index=0, shot_size="close", movement="push_in",
                   subject="小孩", action="掉入巨型水缸",
                   emotion_expression="双手乱抓、双眼张大极度恐慌",
                   atmosphere="惊慌", lighting="水花溅起")
    p = b.shot_prompt
    assert p.startswith("close, push_in")
    assert "双手乱抓" in p and "水花溅起" in p
    prompts = golden_beats_to_shot_prompts([b])
    assert prompts == [p]


def test_parse_tolerates_markdown_fence():
    raw = '```json\n' + _SIMGUA_JSON + '\n```'
    beats = parse_golden_beats(raw)
    assert len(beats) == 2
    assert beats[1].movement == "push_in"


def test_parse_garbage_returns_empty():
    assert parse_golden_beats("抱歉, 我无法回答") == []


@pytest.mark.asyncio
async def test_plan_shots_carries_golden_variables():
    """Beat 的表情/氛围/光线 → CineShot + prompt (动画演绎变量落位)。"""
    scene = Scene(
        scene_id="s1",
        characters=["smg"],
        beats=[
            Beat(beat_id="b1", action="跑跳追逐",
                 emotion_expression="嘴角上扬欢笑",
                 atmosphere="轻松嬉戏", lighting="明亮日光"),
        ],
    )
    shots = await plan_shots(scene, art_direction="水墨动画风格")
    shot = shots.shots[0]
    assert shot.emotion_expression == "嘴角上扬欢笑"
    assert shot.lighting == "明亮日光"
    assert "嘴角上扬欢笑" in shot.prompt
    assert "轻松嬉戏" in shot.prompt
    assert shot.style == "live"                      # 默认 live, 向后兼容


def test_cineshot_animation_style():
    s = CineShot(shot_id="SH01", scene_id="s1", style="animation",
                 prompt="close, 司马光砸缸(水墨动画)")
    assert s.style == "animation"


@pytest.mark.asyncio
async def test_generate_attempt_animation_uses_text_to_video(tmp_path):
    """动画分支: 无参考图, 调纯文生视频 provider。"""
    shot = CineShot(shot_id="SH01", scene_id="s1", style="animation",
                    est_duration_s=4.0, prompt="close, 司马光砸缸(水墨动画)")
    calls = {}

    async def fake_t2v(**kw):
        calls.update(kw)
        kw["output_path"].write_bytes(b"fake-video")

    out = await _generate_attempt(
        shot, [], output_path=tmp_path / "a.mp4", seed=42,
        video_gen=fake_t2v, open_mouth=True,
    )
    assert out.name == "a.mp4"
    assert calls["prompt"].startswith("close")
    assert calls["duration"] == 4
    assert "reference_images" not in calls      # 不传参考图


@pytest.mark.asyncio
async def test_run_cg6_animation_skips_identity(tmp_path):
    """动画 CG6: identity 跳过 (置通过), 保留台词/VLM 检查。"""
    shot = CineShot(shot_id="SH01", scene_id="s1", style="animation",
                    est_duration_s=4.0)
    video = tmp_path / "a.mp4"
    video.write_bytes(b"fake")

    result = await _run_cg6(video, shot, pool=None, pack_id="",
                            version="", vlm=None, skip_identity=True)
    assert result.identity_passed is True
    assert result.identity_distance is None
    assert result.passed is True                    # 动画无身份约束 → 直接过

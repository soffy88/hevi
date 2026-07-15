"""L4 分镜 + G4 校验门测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.tongjian.schemas import (
    AudioSegment,
    CharacterBible,
    CharacterBibleEntry,
    GateResult,
    Script,
    ScriptLine,
    Shot,
    ShotCamera,
    ShotList,
    Timeline,
    TimelineGap,
)
from hevi.tongjian.shotlist import (
    _extract_characters,
    _infer_camera,
    _infer_scene_id,
    build_shotlist,
    gate_shotlist,
    generate_shotlist,
)


# ── fixtures ──────────────────────────────────────────────────────────────


def _make_script(lines: list[dict] | None = None) -> Script:
    if lines is None:
        lines = [
            {
                "line_id": "LN001",
                "act": 1,
                "type": "narration",
                "speaker": "NARRATOR",
                "text": "智伯设宴,韩魏赵三家大夫皆列席。",
                "event_id": "E001",
                "visual_hint": "远景,宫殿大堂",
            },
            {
                "line_id": "LN002",
                "act": 1,
                "type": "dialogue",
                "speaker": "C001",
                "text": "祸乱要来,也得我来挑起。",
                "event_id": "E001",
                "visual_hint": "近景,智伯冷笑",
            },
            {
                "line_id": "LN003",
                "act": 2,
                "type": "commentary",
                "speaker": "NARRATOR",
                "text": "臣光曰:礼崩乐坏,自此始也。",
                "event_id": "E002",
            },
        ]
    return Script(lines=[ScriptLine(**ln) for ln in lines])


def _make_bible() -> CharacterBible:
    return CharacterBible(
        characters=[
            CharacterBibleEntry(character_id="C001", name="智伯", appearance="高冠广袖"),
        ]
    )


def _make_timeline_no_gap() -> Timeline:
    return Timeline(
        audio_segments=[
            AudioSegment(
                line_id="LN001",
                file="audio/ln001.wav",
                duration_ms=3000,
                t_start_ms=0,
                t_end_ms=3000,
            ),
            AudioSegment(
                line_id="LN002",
                file="audio/ln002.wav",
                duration_ms=2000,
                t_start_ms=3000,
                t_end_ms=5000,
            ),
        ],
        total_duration_ms=5000,
    )


def _make_timeline_with_gap() -> Timeline:
    """LN002(act1)→LN003(act2)之间有 1.5s 幕间空隙,与真实 L3 输出一致。"""
    return Timeline(
        audio_segments=[
            AudioSegment(
                line_id="LN001",
                file="audio/ln001.wav",
                duration_ms=3000,
                t_start_ms=0,
                t_end_ms=3000,
            ),
            AudioSegment(
                line_id="LN002",
                file="audio/ln002.wav",
                duration_ms=2000,
                t_start_ms=3000,
                t_end_ms=5000,
            ),
            AudioSegment(
                line_id="LN003",
                file="audio/ln003.wav",
                duration_ms=2000,
                t_start_ms=6500,
                t_end_ms=8500,
            ),
        ],
        total_duration_ms=8500,
        gaps=[TimelineGap(after_line="LN002", duration_ms=1500, purpose="act_transition")],
    )


# ── 确定性规则测试 ────────────────────────────────────────────────────────


class TestInferCamera:
    def test_dialogue_defaults_medium_close(self):
        line = ScriptLine(line_id="LN001", type="dialogue", speaker="C001", text="x")
        cam = _infer_camera(line)
        assert cam.shot_size == "medium_close"
        assert cam.movement == "static"

    def test_commentary_wide_push_in(self):
        line = ScriptLine(line_id="LN001", type="commentary", speaker="NARRATOR", text="x")
        cam = _infer_camera(line)
        assert cam.shot_size == "wide"
        assert cam.movement == "slow_push_in"

    def test_visual_hint_overrides_size(self):
        line = ScriptLine(
            line_id="LN001", type="dialogue", speaker="C001", text="x", visual_hint="特写,面部"
        )
        cam = _infer_camera(line)
        assert cam.shot_size == "close_up"

    def test_visual_hint_movement_keyword(self):
        line = ScriptLine(
            line_id="LN001", type="narration", speaker="NARRATOR", text="x", visual_hint="镜头缓推"
        )
        cam = _infer_camera(line)
        assert cam.movement == "slow_push_in"


class TestInferSceneId:
    def test_new_event_new_scene(self):
        line = ScriptLine(line_id="LN001", speaker="NARRATOR", text="x", event_id="E002")
        assert _infer_scene_id(line, "E001") == "E002"

    def test_same_event_keeps_scene(self):
        line = ScriptLine(line_id="LN001", speaker="NARRATOR", text="x", event_id="E001")
        assert _infer_scene_id(line, "E001") == "E001"

    def test_no_prev_scene_falls_back_default(self):
        line = ScriptLine(line_id="LN001", speaker="NARRATOR", text="x", event_id=None)
        assert _infer_scene_id(line, "") == "S001"

    def test_location_used_as_scene_id(self):
        line = ScriptLine(line_id="LN001", speaker="NARRATOR", text="x", event_id="E001")
        assert _infer_scene_id(line, "", location="崂山绝顶道观") == "崂山绝顶道观"

    def test_same_location_keeps_scene_even_across_event_change(self):
        """2026-07-12 短剧真实反馈"场景乱切":P0 老策略(event_id 变就换 scene)没有
        场景连贯性概念。地点没变,即使事件变了也不该切场景。"""
        line = ScriptLine(line_id="LN001", speaker="NARRATOR", text="x", event_id="E002")
        assert _infer_scene_id(line, "崂山绝顶道观", location="崂山绝顶道观") == "崂山绝顶道观"

    def test_missing_location_falls_back_to_p0_strategy(self):
        """不传 location(通鉴自己的既有调用方)时行为不能变。"""
        line = ScriptLine(line_id="LN001", speaker="NARRATOR", text="x", event_id="E002")
        assert _infer_scene_id(line, "E001", location=None) == "E002"


class TestExtractCharacters:
    def test_dialogue_speaker_included(self):
        line = ScriptLine(line_id="LN001", type="dialogue", speaker="C001", text="x")
        assert _extract_characters(line, _make_bible()) == ["C001"]

    def test_narrator_not_a_character(self):
        line = ScriptLine(line_id="LN001", type="narration", speaker="NARRATOR", text="x")
        assert _extract_characters(line, _make_bible()) == []

    def test_visual_hint_mentions_character(self):
        line = ScriptLine(
            line_id="LN001",
            type="narration",
            speaker="NARRATOR",
            text="x",
            visual_hint="智伯立于殿前",
        )
        assert _extract_characters(line, _make_bible()) == ["C001"]


# ── generate_shotlist 测试 ────────────────────────────────────────────────


class TestGenerateShotlist:
    @pytest.mark.asyncio
    async def test_basic_one_shot_per_segment(self):
        shotlist = await generate_shotlist(
            _make_timeline_no_gap(),
            _make_script(),
            _make_bible(),
            llm=AsyncMock(),
        )
        assert len(shotlist.shots) == 2
        assert shotlist.shots[0].line_ids == ["LN001"]
        assert shotlist.shots[0].t_start_ms == 0
        assert shotlist.shots[0].t_end_ms == 3000
        assert shotlist.shots[1].t_start_ms == 3000
        assert shotlist.shots[1].t_end_ms == 5000

    @pytest.mark.asyncio
    async def test_event_locations_keep_same_scene_across_events(self):
        """2026-07-12 短剧真实反馈"场景乱切":同一地点连续发生的两个不同事件,
        传了 event_locations 后不该被切成两个场景。"""
        script = _make_script(
            lines=[
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "王生跪在观门前。",
                    "event_id": "E001",
                },
                {
                    "line_id": "LN002",
                    "act": 1,
                    "type": "dialogue",
                    "speaker": "C001",
                    "text": "弟子愿留观中修行。",
                    "event_id": "E002",
                },
            ]
        )
        shotlist = await generate_shotlist(
            _make_timeline_no_gap(),
            script,
            _make_bible(),
            llm=AsyncMock(),
            event_locations={"E001": "崂山绝顶道观", "E002": "崂山绝顶道观"},
        )
        assert shotlist.shots[0].scene_id == shotlist.shots[1].scene_id == "崂山绝顶道观"

    @pytest.mark.asyncio
    async def test_without_event_locations_keeps_old_per_event_scene_split(self):
        """不传 event_locations(通鉴自己的既有调用方)时行为不能变:换事件就换场景。"""
        script = _make_script(
            lines=[
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "王生跪在观门前。",
                    "event_id": "E001",
                },
                {
                    "line_id": "LN002",
                    "act": 1,
                    "type": "dialogue",
                    "speaker": "C001",
                    "text": "弟子愿留观中修行。",
                    "event_id": "E002",
                },
            ]
        )
        shotlist = await generate_shotlist(
            _make_timeline_no_gap(), script, _make_bible(), llm=AsyncMock()
        )
        assert shotlist.shots[0].scene_id != shotlist.shots[1].scene_id

    @pytest.mark.asyncio
    async def test_gap_gets_transition_shot(self):
        """真实 L3 timeline 的幕间空隙必须有镜头覆盖,不能留空洞。"""
        shotlist = await generate_shotlist(
            _make_timeline_with_gap(),
            _make_script(),
            _make_bible(),
            llm=AsyncMock(),
        )
        transition_shots = [s for s in shotlist.shots if s.is_transition]
        assert len(transition_shots) == 1
        gap_shot = transition_shots[0]
        assert gap_shot.t_start_ms == 5000
        assert gap_shot.t_end_ms == 6500
        assert gap_shot.characters == []

    @pytest.mark.asyncio
    async def test_long_shot_split_by_llm(self):
        timeline = Timeline(
            audio_segments=[
                AudioSegment(
                    line_id="LN001",
                    file="audio/ln001.wav",
                    duration_ms=9000,
                    t_start_ms=0,
                    t_end_ms=9000,
                ),
            ],
            total_duration_ms=9000,
        )
        script = _make_script(
            [
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "长旁白段落",
                    "event_id": "E001",
                },
            ]
        )
        llm = AsyncMock(
            return_value={
                "content": json.dumps(
                    {
                        "sub_shots": [
                            {
                                "fraction": 0.5,
                                "shot_size": "wide",
                                "movement": "static",
                                "visual_prompt": "远景",
                            },
                            {
                                "fraction": 0.5,
                                "shot_size": "close_up",
                                "movement": "static",
                                "visual_prompt": "特写",
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            }
        )

        shotlist = await generate_shotlist(timeline, script, _make_bible(), llm=llm)
        assert len(shotlist.shots) == 2
        assert shotlist.shots[0].t_start_ms == 0
        assert shotlist.shots[0].t_end_ms == 4500
        assert shotlist.shots[1].t_start_ms == 4500
        assert shotlist.shots[1].t_end_ms == 9000

    @pytest.mark.asyncio
    async def test_long_shot_llm_failure_falls_back_to_single_shot(self):
        timeline = Timeline(
            audio_segments=[
                AudioSegment(
                    line_id="LN001",
                    file="audio/ln001.wav",
                    duration_ms=9000,
                    t_start_ms=0,
                    t_end_ms=9000,
                ),
            ],
            total_duration_ms=9000,
        )
        script = _make_script(
            [
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "长旁白段落",
                    "event_id": "E001",
                },
            ]
        )
        llm = AsyncMock(side_effect=RuntimeError("network down"))
        shotlist = await generate_shotlist(timeline, script, _make_bible(), llm=llm)
        assert len(shotlist.shots) == 1
        assert shotlist.shots[0].t_end_ms == 9000

    @pytest.mark.asyncio
    async def test_missing_line_id_skipped(self):
        """timeline 引用了 script 里不存在的 line_id 时应跳过而非崩溃。"""
        timeline = Timeline(
            audio_segments=[
                AudioSegment(
                    line_id="LN999", file="x.wav", duration_ms=1000, t_start_ms=0, t_end_ms=1000
                ),
            ],
            total_duration_ms=1000,
        )
        shotlist = await generate_shotlist(timeline, _make_script(), _make_bible(), llm=AsyncMock())
        assert shotlist.shots == []


# ── gate_shotlist 测试 ────────────────────────────────────────────────────


class TestGateShotlist:
    @pytest.mark.asyncio
    async def test_empty_shotlist_fails(self):
        result = gate_shotlist(
            await generate_shotlist(
                Timeline(),
                Script(),
                _make_bible(),
                llm=AsyncMock(),
            ),
            Timeline(),
            _make_bible(),
        )
        assert not result.passed
        assert any("为空" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_gapless_timeline_passes(self):
        timeline = _make_timeline_no_gap()
        shotlist = await generate_shotlist(timeline, _make_script(), _make_bible(), llm=AsyncMock())
        result = gate_shotlist(shotlist, timeline, _make_bible())
        assert result.passed
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_real_timeline_gap_does_not_trigger_false_hole_error(self):
        """回归测试:真实 L3 输出含幕间空隙时,不应被 G4 误判为画面空洞。"""
        timeline = _make_timeline_with_gap()
        shotlist = await generate_shotlist(timeline, _make_script(), _make_bible(), llm=AsyncMock())
        result = gate_shotlist(shotlist, timeline, _make_bible())
        assert result.passed
        assert not any("空洞" in e for e in result.errors)

    def test_unknown_character_warns(self):
        timeline = _make_timeline_no_gap()
        shotlist = ShotList(
            shots=[
                Shot(
                    shot_id="SH001",
                    line_ids=["LN001"],
                    t_start_ms=0,
                    t_end_ms=3000,
                    scene_id="E001",
                    characters=["C999"],
                ),
                Shot(
                    shot_id="SH002",
                    line_ids=["LN002"],
                    t_start_ms=3000,
                    t_end_ms=5000,
                    scene_id="E001",
                    characters=["C001"],
                ),
            ]
        )
        result = gate_shotlist(shotlist, timeline, _make_bible())
        assert result.passed  # 未知角色只是 warning
        assert any("C999" in w for w in result.warnings)

    def test_overlap_detected_as_error(self):
        timeline = _make_timeline_no_gap()
        shotlist = ShotList(
            shots=[
                Shot(
                    shot_id="SH001",
                    line_ids=["LN001"],
                    t_start_ms=0,
                    t_end_ms=3000,
                    scene_id="E001",
                ),
                Shot(
                    shot_id="SH002",
                    line_ids=["LN002"],
                    t_start_ms=2500,
                    t_end_ms=5000,
                    scene_id="E001",
                ),
            ]
        )
        result = gate_shotlist(shotlist, timeline, _make_bible())
        assert not result.passed
        assert any("重叠" in e for e in result.errors)

    def test_monotony_warning_on_repeated_scene_and_size(self):
        timeline = Timeline(
            audio_segments=[],
            total_duration_ms=4000,
        )
        shots = [
            Shot(
                shot_id=f"SH{i:03d}",
                line_ids=[f"LN00{i}"],
                t_start_ms=i * 1000,
                t_end_ms=(i + 1) * 1000,
                scene_id="E001",
                camera=ShotCamera(shot_size="medium"),
            )
            for i in range(4)
        ]
        shotlist = ShotList(shots=shots)
        result = gate_shotlist(shotlist, timeline, _make_bible())
        assert any("建议变化" in w for w in result.warnings)


# ── build_shotlist 集成测试 ───────────────────────────────────────────────


class TestBuildShotlist:
    @pytest.mark.asyncio
    async def test_end_to_end_with_real_l3_shaped_timeline(self):
        shotlist, result = await build_shotlist(
            _make_timeline_with_gap(),
            _make_script(),
            _make_bible(),
            llm=AsyncMock(),
        )
        assert isinstance(result, GateResult)
        assert result.passed
        # 3 条台词 + 1 个过场镜头
        assert len(shotlist.shots) == 4

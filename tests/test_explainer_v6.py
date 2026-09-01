from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import hevi.explainer.assembly as explainer_assembly
from hevi.explainer.asr_verify import AsrVerificationError, character_error_rate, verify_audio
from hevi.explainer.assembly import cues_to_storyboard
from hevi.explainer.contracts import (
    ExplainerAssembleRequest,
    ExplainerCapabilityError,
    ExplainerCue,
    ExplainerResearchRequest,
    HookNode,
)
from hevi.explainer.research import research_and_generate
from hevi.explainer.service import ExplainerMasterService


def _payload() -> dict:
    cue = {"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "事实"}
    return {
        "facts": [{"claim": "事实", "source": "公开报告", "confidence": 0.9}],
        "hooks": [{"text": f"Hook {i}", "angle": "角度", "recommended": i == 0} for i in range(5)],
        "scripts": [
            {
                "id": letter,
                "title": f"版本 {letter}",
                "viewpoint": "数据",
                "hook": "Hook 0",
                "cues": [cue],
            }
            for letter in ("A", "B", "C")
        ],
    }


def _matrix_payload() -> dict:
    """v9 递进式 Hook 矩阵:动态数量 + 叙事功能档位,无推荐/不推荐标签。"""
    cue = {"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "事实"}
    return {
        "facts": [{"claim": "事实", "source": "公开报告", "confidence": 0.9}],
        "hooks": [
            {
                "hook_id": "H1",
                "title": "灾难的根源",
                "narrative_function": "opening_suspense",
                "suggested_placement_s": 0.0,
                "text": "为什么经典力学在 BBGKY 方程这里彻底失效？",
                "associated_concepts": ["BBGKY 方程"],
            },
            {
                "hook_id": "H2",
                "title": "拓扑树与重碰撞",
                "narrative_function": "mid_conflict",
                "suggested_placement_s": 90.0,
                "text": "这里的核心死结，就是这张拓扑树上的重碰撞",
                "associated_concepts": ["拓扑树", "重碰撞"],
            },
            {
                "hook_id": "H3",
                "title": "调和分析突破",
                "narrative_function": "climax_breakthrough",
                "suggested_placement_s": 180.0,
                "text": "而邓煜引入的调和分析，正是解开死结的钥匙",
                "associated_concepts": ["调和分析"],
            },
        ],
        "scripts": [
            {
                "id": "A",
                "title": "版本 A",
                "viewpoint": "数据",
                "hook": "H1",
                "cues": [cue],
            }
        ],
    }



class _Researcher:
    async def research(self, _topic: str) -> dict:
        return {"facts": _payload()["facts"]}


class _Generator:
    async def generate(self, _topic: str, _research: dict) -> dict:
        return _payload()


@pytest.mark.asyncio
async def test_v6_research_returns_five_hooks_and_three_scripts() -> None:
    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="测试主题"),
        researcher=_Researcher(),
        script_generator=_Generator(),
    )
    assert len(result.hooks) == 5
    assert len(result.scripts) == 3
    assert result.scripts[0].cues[0].visual_type == "voiceover"


@pytest.mark.asyncio
async def test_v6_research_accepts_three_hooks() -> None:
    payload = _payload()
    payload["hooks"] = payload["hooks"][:3]

    class ThreeHookGenerator:
        async def generate(self, _topic: str, _research: dict) -> dict:
            return payload

    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="测试主题"),
        researcher=_Researcher(),
        script_generator=ThreeHookGenerator(),
    )
    assert len(result.hooks) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("script_count", [1, 5])
async def test_v6_research_accepts_variable_script_counts(script_count: int) -> None:
    payload = _payload()
    template = payload["scripts"][0]
    payload["scripts"] = [
        {**template, "id": f"V{index + 1}", "title": f"版本 {index + 1}"}
        for index in range(script_count)
    ]

    class VariableScriptGenerator:
        async def generate(self, _topic: str, _research: dict) -> dict:
            return payload

    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="测试主题"),
        researcher=_Researcher(),
        script_generator=VariableScriptGenerator(),
    )
    assert len(result.scripts) == script_count
    assert result.decision_trail[-1]["script_count"] == script_count


@pytest.mark.asyncio
async def test_v6_research_extracts_hook_from_scripts_when_list_is_empty() -> None:
    payload = _payload()
    payload["hooks"] = []

    class ScriptHookGenerator:
        async def generate(self, _topic: str, _research: dict) -> dict:
            return payload

    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="测试主题"),
        researcher=_Researcher(),
        script_generator=ScriptHookGenerator(),
    )
    assert [hook.text for hook in result.hooks] == ["Hook 0"]


@pytest.mark.asyncio
async def test_v6_research_rejects_incomplete_model_output() -> None:
    class Incomplete:
        async def research(self, _topic: str) -> dict:
            return {"facts": [], "hooks": [], "scripts": []}

    with pytest.raises(ExplainerCapabilityError, match="没有可用 Hook"):
        await research_and_generate(
            ExplainerResearchRequest(topic_or_url="测试主题"), researcher=Incomplete()
        )


@pytest.mark.asyncio
async def test_v6_research_rejects_only_when_all_scripts_are_missing() -> None:
    class NoScripts:
        async def research(self, _topic: str) -> dict:
            return {"facts": [], "hooks": [{"text": "有效 Hook"}], "scripts": []}

    with pytest.raises(ExplainerCapabilityError, match="至少需要包含 1 个脚本版本"):
        await research_and_generate(
            ExplainerResearchRequest(topic_or_url="测试主题"), researcher=NoScripts()
        )


class _MatrixGenerator:
    async def generate(self, _topic: str, _research: dict) -> dict:
        return _matrix_payload()


@pytest.mark.asyncio
async def test_v9_research_returns_progressive_hook_matrix() -> None:
    """矩阵按知识节点动态产出,保留叙事功能档位与关联概念,不写死 5 个。"""
    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="邓煜突破 BBGKY 方程"),
        researcher=_Researcher(),
        script_generator=_MatrixGenerator(),
    )
    assert [hook.narrative_function for hook in result.hooks] == [
        "opening_suspense",
        "mid_conflict",
        "climax_breakthrough",
    ]
    assert [hook.suggested_placement_s for hook in result.hooks] == [0.0, 90.0, 180.0]
    assert result.hooks[0].associated_concepts == ["BBGKY 方程"]
    assert result.hooks[0].hook_id == "H1"
    # script.hook 引用的是 hook_id 时不重复入矩阵
    assert len(result.hooks) == 3


@pytest.mark.asyncio
async def test_v9_research_deduplicates_duplicate_hook_texts() -> None:
    payload = _matrix_payload()
    payload["hooks"].append(dict(payload["hooks"][0]))  # 重复文本的凑数 Hook

    class DupGenerator:
        async def generate(self, _topic: str, _research: dict) -> dict:
            return payload

    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="测试主题"),
        researcher=_Researcher(),
        script_generator=DupGenerator(),
    )
    assert len(result.hooks) == 3


@pytest.mark.asyncio
async def test_v9_research_accepts_dynamic_hook_counts() -> None:
    """6 个知识节点 → 6 个矩阵 Hook,不再被 5 个上限截断。"""
    payload = _matrix_payload()
    base = payload["hooks"][0]
    payload["hooks"] = [
        {
            **base,
            "hook_id": f"H{index + 1}",
            "title": f"节点 {index + 1}",
            "text": f"知识节点 {index + 1} 的递进 Hook",
            "suggested_placement_s": index * 30.0,
        }
        for index in range(6)
    ]

    class SixNodeGenerator:
        async def generate(self, _topic: str, _research: dict) -> dict:
            return payload

    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="测试主题"),
        researcher=_Researcher(),
        script_generator=SixNodeGenerator(),
    )
    assert len(result.hooks) == 6


def test_v9_assemble_request_accepts_hook_chain_selection() -> None:
    from hevi.explainer.contracts import ExplainerAssembleRequest

    request = ExplainerAssembleRequest(
        selected_hook="为什么经典力学在 BBGKY 方程这里彻底失效？",
        selected_hooks=[
            "为什么经典力学在 BBGKY 方程这里彻底失效？",
            "这里的核心死结，就是这张拓扑树上的重碰撞",
        ],
        hook_combination="chain",
        final_script_cues=[
            {"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "开场"}
        ],
    )
    assert request.hook_combination == "chain"
    assert len(request.selected_hooks) == 2
    assert request.selected_hook


def test_v9_assemble_request_supports_fusion_mode() -> None:
    from hevi.explainer.contracts import ExplainerAssembleRequest

    request = ExplainerAssembleRequest(
        selected_hooks=["悬念 A", "悬念 B"],
        hook_combination="fusion",
        final_script_cues=[
            {"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "开场"}
        ],
    )
    assert request.hook_combination == "fusion"
    assert request.selected_hook == ""  # 旧字段保持兼容,不强制


def test_v9_research_response_keeps_hook_matrix_structure() -> None:
    from hevi.explainer.contracts import ExplainerResearchResponse
    from hevi.explainer.research import response_payload

    result = asyncio.run(
        research_and_generate(
            ExplainerResearchRequest(topic_or_url="邓煜突破 BBGKY 方程"),
            researcher=_Researcher(),
            script_generator=_MatrixGenerator(),
        )
    )
    payload = response_payload(result, "邓煜突破 BBGKY 方程")
    response = ExplainerResearchResponse.model_validate(payload)
    assert isinstance(response.hooks[0], HookNode)
    assert response.hooks[0].narrative_function == "opening_suspense"
    assert response.hooks[0].associated_concepts == ["BBGKY 方程"]


def test_v6_cues_keep_visual_scaffold_metadata_for_remotion() -> None:
    storyboard = cues_to_storyboard(
        "测试主题",
        [ExplainerCue(time_range="00:00-00:05", visual_type="remotion_chart", text="数据")],
    )
    assert storyboard.segments[0].visual_type == "remotion_chart"
    assert storyboard.segments[0].visual_config["time_range"] == "00:00-00:05"


@pytest.mark.asyncio
async def test_stock_broll_is_fulfilled_when_service_injected(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    captured = {}

    async def fake_render(storyboard, _output_dir, **_kwargs):
        captured["storyboard"] = storyboard
        return "rendered"

    class FakeStock:
        async def search(self, *, user_id, query, media_type, count):
            assert user_id == "u1"
            assert query == "rain city"
            assert media_type == "video"
            return [{"preview_url": "https://cdn.example/rain.mp4"}]

    def fake_freeze(_url, *, output_dir, **_kwargs):
        frozen = output_dir / "frozen.mp4"
        frozen.write_bytes(b"frozen")
        return frozen

    monkeypatch.setattr(explainer_assembly, "_freeze_stock_url", fake_freeze)
    monkeypatch.setattr(explainer_assembly, "render_narrated_storyboard", fake_render)
    result = await explainer_assembly.assemble_explainer_cues(
        "测试主题",
        [
            ExplainerCue(
                visual_type="stock_broll",
                text="雨夜",
                visual_search_query="rain city",
            )
        ],
        tmp_path,
        voice="cosyvoice_default",
        stock_service=FakeStock(),
        stock_user_id="u1",
    )
    assert result == "rendered"
    frozen = Path(captured["storyboard"].segments[0].visual_config["assetUrl"])
    assert frozen.is_file()
    assert frozen.suffix == ".mp4"


@pytest.mark.asyncio
async def test_v8_local_presenter_is_renderable_without_heygen_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    captured = {}

    async def fake_render(storyboard, _output_dir, **_kwargs):
        captured["storyboard"] = storyboard
        return "rendered"

    async def forbidden_heygen(**_kwargs):
        raise AssertionError("local presenter must not call HeyGen")

    monkeypatch.setattr(explainer_assembly, "render_narrated_storyboard", fake_render)
    result = await explainer_assembly.assemble_explainer_cues(
        "测试主题",
        [ExplainerCue(visual_type="heygen_avatar", text="自动数字人开场")],
        tmp_path,
        voice="cosyvoice_default",
        presenter_provider="remotion",
        presenter_name="HEVI 默认解说数字人",
        heygen_provider=forbidden_heygen,
    )

    storyboard = captured["storyboard"]
    assert result == "rendered"
    assert storyboard.segments[0].visual_config["local_presenter"] is True
    assert storyboard.segments[0].visual_config["presenter_name"] == "HEVI 默认解说数字人"


def test_v6_cue_derives_time_range_when_model_omits_it() -> None:
    cue = ExplainerCue(visual_type="voiceover", text="模型生成的旁白", time_estimate_s=7.5)
    assert cue.time_range == "00:00-07.5s"
    assert cue.time_estimate_s == 7.5


def test_v6_cue_preserves_explicit_time_range() -> None:
    cue = ExplainerCue(
        time_range="00:05-00:12",
        visual_type="voiceover",
        text="人工编辑的旁白",
        time_estimate_s=7,
    )
    assert cue.time_range == "00:05-00:12"


def test_v6_cue_normalizes_legacy_null_estimate() -> None:
    cue = ExplainerCue(visual_type="voiceover", text="兼容旧客户端", time_estimate_s=None)
    assert cue.time_estimate_s == 5.0
    assert cue.time_range == "00:00-05.0s"


@pytest.mark.asyncio
async def test_v9_service_entry_deep_unpacks_double_escaped_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """服务入口(service.assemble)第一行递归解包:字符串化的 chart_data /
    visual_config 全部还原成 dict,绝不带着 str 进装配。"""
    captured = {}

    async def fake_render(storyboard, _output_dir, **_kwargs):
        captured["storyboard"] = storyboard
        return "rendered"

    monkeypatch.setattr(explainer_assembly, "render_narrated_storyboard", fake_render)
    # 构造一个藏了字符串化 chart_data 的 payload:visual_config 里嵌套对象被
    # 序列化成 JSON 字符串(服务入口 deep_unpack 必须逐层还原)。
    visual_config = {
        "chart_data": '{"type": "bar", "values": [1, 2, 3]}',
        "assetUrl": "/chart.png",
    }
    cue = ExplainerCue(
        time_range="00:00-00:06",
        visual_type="remotion_chart",
        text="数据图表",
        visual_config=visual_config,
    )
    request = ExplainerAssembleRequest(
        topic_or_url="邓煜突破 BBGKY 方程",
        final_script_cues=[cue],
        voice_profile="cosyvoice_default",
    )
    result = await ExplainerMasterService().assemble(request, tmp_path)
    assert result == "rendered"
    config = captured["storyboard"].segments[0].visual_config
    assert isinstance(config, dict)
    assert config["chart_data"] == {"type": "bar", "values": [1, 2, 3]}
    assert config["assetUrl"] == "/chart.png"


def test_v6_character_error_rate_is_deterministic() -> None:
    assert character_error_rate("你好世界", "你好世界") == 0
    assert character_error_rate("你好世界", "你好") == 0.5


@pytest.mark.asyncio
async def test_v6_asr_verification_retries_and_reports_failure(tmp_path) -> None:
    audio = tmp_path / "segment.wav"
    audio.write_bytes(b"audio")
    attempts = 0

    async def bad_asr(_path):
        nonlocal attempts
        attempts += 1
        return {"text": "完全不同"}

    with pytest.raises(AsrVerificationError, match="CER"):
        await verify_audio("目标旁白", audio, asr=bad_asr, retries=2)
    assert attempts == 3

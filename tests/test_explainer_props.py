"""Defensive Remotion props parsing at the explainer assembly boundary."""

from __future__ import annotations

from hevi.explainer.assembly import cues_to_storyboard
from hevi.explainer.contracts import ExplainerCue
from hevi.explainer.props import (
    normalise_visual_config,
    process_cues_for_remotion,
    safe_dict,
    safe_list,
    safe_str,
)

# ── safe_dict / safe_list / safe_str ─────────────────────────────────────


def test_safe_dict_passthrough_and_json_string() -> None:
    assert safe_dict({"a": 1}) == {"a": 1}
    assert safe_dict('{"chart_data": {"type": "bar"}}') == {
        "chart_data": {"type": "bar"}
    }


def test_safe_dict_tolerates_bad_input() -> None:
    assert safe_dict(None) == {}
    assert safe_dict("") == {}
    assert safe_dict("not json") == {}
    assert safe_dict('["list", 1]') == {}  # JSON 数组不是对象
    assert safe_dict(42) == {}
    assert safe_dict([1, 2]) == {}


def test_safe_dict_accepts_pydantic_model() -> None:
    cue = ExplainerCue(time_range="00:00-00:05", visual_type="voiceover", text="旁白")
    dumped = safe_dict(cue)
    assert dumped["text"] == "旁白"
    assert dumped["visual_type"] == "voiceover"


def test_safe_list_parses_json_array_string() -> None:
    assert safe_list(["a"]) == ["a"]
    assert safe_list('[{"title": "卡一"}]') == [{"title": "卡一"}]
    assert safe_list("not json") == []
    assert safe_list(None) == []


def test_safe_str_scalars_only() -> None:
    assert safe_str("ok") == "ok"
    assert safe_str(12) == "12"
    assert safe_str(None) == ""
    assert safe_str({"a": 1}) == ""
    assert safe_str(None, default="fallback") == "fallback"


# ── normalise_visual_config ──────────────────────────────────────────────


def test_normalise_visual_config_whole_string() -> None:
    assert normalise_visual_config('{"assetUrl": "/a.mp4"}') == {"assetUrl": "/a.mp4"}
    assert normalise_visual_config("not json") == {}
    assert normalise_visual_config(None) == {}


def test_normalise_visual_config_nested_strings() -> None:
    raw = {
        "chart_data": '{"type": "bar", "labels": ["一"], "values": [1]}',
        "cards": '[{"title": "卡"}]',
        "assetUrl": "/b.mp4",
    }
    out = normalise_visual_config(raw)
    assert out["chart_data"] == {"type": "bar", "labels": ["一"], "values": [1]}
    assert out["cards"] == [{"title": "卡"}]
    assert out["assetUrl"] == "/b.mp4"


def test_normalise_visual_config_bad_nested_value_falls_back() -> None:
    out = normalise_visual_config({"chart_data": "broken json", "ok": 1})
    assert out["chart_data"] == {}
    assert out["ok"] == 1


# ── process_cues_for_remotion ────────────────────────────────────────────


def test_process_cues_normalises_stringified_chart_data() -> None:
    cues = [
        {
            "time_range": "00:00-00:06",
            "visual_type": "remotion_chart",
            "text": "数据图表",
            "chart_data": '{"type": "bar", "values": [1, 2, 3]}',
        }
    ]
    processed = process_cues_for_remotion(cues)
    assert len(processed) == 1
    assert processed[0].chart_data == {"type": "bar", "values": [1, 2, 3]}


def test_process_cues_accepts_whole_cue_as_json_string() -> None:
    cue_json = '{"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "整条字符串化"}'
    processed = process_cues_for_remotion([cue_json])
    assert len(processed) == 1
    assert processed[0].text == "整条字符串化"


def test_process_cues_accepts_pydantic_models() -> None:
    cue = ExplainerCue(time_range="00:00-00:05", visual_type="voiceover", text="旁白")
    processed = process_cues_for_remotion([cue])
    assert len(processed) == 1
    assert processed[0].text == "旁白"


def test_process_cues_drops_dirty_entries() -> None:
    processed = process_cues_for_remotion(
        [
            "not json",
            42,
            {"visual_type": "voiceover", "text": ""},  # 空旁白校验失败
            {"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "有效"},
        ]
    )
    assert len(processed) == 1
    assert processed[0].text == "有效"


def test_process_cues_non_list_input() -> None:
    assert process_cues_for_remotion(None) == []
    assert process_cues_for_remotion("not a list") == []


# ── cues_to_storyboard 入口防御 ──────────────────────────────────────────


def test_cues_to_storyboard_keeps_visual_config_chart_data_when_top_level_missing() -> None:
    cue = ExplainerCue(
        time_range="00:00-00:06",
        visual_type="remotion_chart",
        text="数据图表",
        visual_config={"chart_data": '{"type": "bar", "values": [1]}'},
    )
    storyboard = cues_to_storyboard("测试", [cue])
    config = storyboard.segments[0].visual_config
    assert config["chart_data"] == {"type": "bar", "values": [1]}


def test_cues_to_storyboard_normalises_stringified_visual_config() -> None:
    cue = ExplainerCue(
        time_range="00:00-00:06",
        visual_type="remotion_chart",
        text="数据图表",
        visual_config={"chart_data": '{"values": [5]}', "highlight_selector": ".t"},
    )
    storyboard = cues_to_storyboard("测试", [cue])
    config = storyboard.segments[0].visual_config
    assert config["chart_data"] == {"values": [5]}
    assert config["highlight_selector"] == ".t"
    assert config["time_range"] == "00:00-00:06"


def test_storyboard_visual_config_is_always_a_dict() -> None:
    # 防御层保证:即便入参把 visual_config 整体字符串化(原始 dict 路径),
    # 产出仍是 dict——process_cues_for_remotion 先还原,再进 cues_to_storyboard。
    raw_cues = [
        {
            "time_range": "00:00-00:05",
            "visual_type": "voiceover",
            "text": "旁白",
            "visual_config": '{"assetUrl": "/a.mp4"}',
        }
    ]
    processed = process_cues_for_remotion(raw_cues)
    assert processed[0].visual_config == {"assetUrl": "/a.mp4"}
    storyboard = cues_to_storyboard("测试", processed)
    assert isinstance(storyboard.segments[0].visual_config, dict)
    assert storyboard.segments[0].visual_config["assetUrl"] == "/a.mp4"

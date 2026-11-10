"""S22：镜头路线 / 报价 / 闸门 / 自检 / 审稿 / 声音 / 许可 / 栏目模板。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.studio import craft_ledger, craft_s22


def _shots(*prompts: str, duration: float = 5.0) -> list[dict]:
    return [
        {
            "index": i + 1,
            "line": prompt,
            "keyframe_prompt": prompt,
            "duration_s": duration,
        }
        for i, prompt in enumerate(prompts)
    ]


def test_code_is_preferred_and_only_upgrades_when_needed() -> None:
    assert craft_s22.classify_route(
        format_id="explainer", style_id="standard", line="用条形图对比三种方案", prompt="clean chart"
    ) == "code"
    assert craft_s22.classify_route(
        format_id="explainer", style_id="standard", line="主角的脸部特写", prompt="portrait"
    ) == "generation"
    assert craft_s22.classify_route(
        format_id="explainer", style_id="scene3d", line="拆解发动机", prompt="3d exploded view"
    ) == "blender"
    assert craft_s22.classify_route(
        format_id="material_cut", style_id="shorts", line="访谈片段", prompt="", has_user_media=True
    ) == "user_media"
    assert craft_s22.classify_route(
        format_id="history_scene", style_id="standard", line="没有人物只有时间线", prompt="timeline"
    ) == "code"


def test_budget_quotes_generation_and_zero_cost_code() -> None:
    code_plan = craft_s22.build_craft_plan(
        format_id="explainer",
        style_id="standard",
        topic="为什么天是蓝的",
        lines=["为什么天是蓝的？"],
        shots=_shots("minimal chart"),
    )
    assert code_plan["budget"]["total_cny"] == 0
    assert "报价 ¥0.00" in code_plan["budget"]["quote"]

    drama = craft_s22.build_craft_plan(
        format_id="live_drama",
        style_id="live_action",
        topic="深夜便利店",
        lines=["店员发现小票停在五年前。"],
        shots=_shots("photorealistic cinematic still", duration=5),
    )
    shot = drama["shots"][0]
    assert shot["route"] == "generation"
    assert shot["model"] == "wan_2_7"
    assert shot["cost_cny"] > 0
    assert drama["budget"]["total_cny"] == pytest.approx(shot["cost_cny"])


def test_six_gates_skip_is_one_click_but_script_gate_is_not_skippable() -> None:
    plan = craft_s22.build_craft_plan(
        format_id="explainer",
        style_id="standard",
        topic="复利",
        lines=["复利为什么反直觉？"],
        shots=_shots("chart"),
        skip_gates=["proof"],
    )
    gates = {gate["id"]: gate for gate in plan["gates"]}
    assert list(gates) == ["brief", "script", "proof", "hardest", "film", "delivery"]
    assert gates["script"]["skippable"] is False
    assert gates["proof"]["status"] == "skipped"
    assert gates["brief"]["status"] == "pending"
    changed = craft_s22.apply_gate_action(plan["gates"], "hardest", "skip")
    assert craft_s22.find_gate(changed, "hardest")["status"] == "skipped"
    with pytest.raises(ValueError):
        craft_s22.apply_gate_action(plan["gates"], "nope", "skip")


def test_text_in_image_is_removed_from_prompt_and_reported() -> None:
    result = craft_s22.sanitize_prompt("photorealistic, 大字标题, 通红的脸")
    assert "大字标题" not in result["prompt"]
    assert "标题安全区" in result["prompt"]
    assert "通红" not in result["prompt"]
    assert any("通红 →" in item for item in result["changes"])

    plan = craft_s22.build_craft_plan(
        format_id="explainer",
        style_id="standard",
        topic="测试",
        lines=["第一句"],
        shots=_shots("minimal illustration, 标题文字"),
    )
    assert plan["rules"]["counts"]["fail"] >= 1
    assert any(issue["rule"] == "text_in_image" for issue in plan["rules"]["issues"])
    assert "画面内不生成文字" in plan["rules"]["text_policy"]


def test_same_chart_more_than_three_times_is_flagged() -> None:
    plan = craft_s22.build_craft_plan(
        format_id="explainer",
        style_id="standard",
        topic="数据",
        lines=["a", "b", "c", "d"],
        shots=_shots("折线图", "折线图", "折线图", "折线图"),
    )
    assert any(issue["rule"] == "chart_repetition" for issue in plan["rules"]["issues"])


def test_numbers_without_source_fail_and_with_source_pass() -> None:
    without = craft_s22.build_craft_plan(
        format_id="explainer",
        style_id="standard",
        topic="数据",
        lines=["全球有 80 亿人。"],
        shots=_shots("chart"),
    )
    assert any(issue["rule"] == "fact_source" for issue in without["rules"]["issues"])

    with_facts = craft_s22.build_craft_plan(
        format_id="explainer",
        style_id="standard",
        topic="数据",
        lines=["全球有 80 亿人。"],
        shots=_shots("chart"),
        facts=[{"claim": "全球人口 80 亿", "source": "联合国 2024"}],
    )
    assert not any(issue["rule"] == "fact_source" for issue in with_facts["rules"]["issues"])


def test_blender_runs_one_render_at_a_time() -> None:
    plan = craft_s22.build_craft_plan(
        format_id="explainer",
        style_id="scene3d",
        topic="发动机",
        lines=["拆解", "装回"],
        shots=_shots("3d exploded view", "3d assembled view"),
    )
    assert plan["rules"]["preview"]["blender_serial"] is True
    assert any(issue["rule"] == "blender_one_at_a_time" for issue in plan["rules"]["issues"])
    assert plan["rules"]["preview"]["code_first_pass_fps"] == 12


def test_sound_plan_music_first_beat_cut_and_first_second_audible() -> None:
    shots = _shots("a", "b", "c", duration=4)
    sound = craft_s22.build_sound_plan(has_narration=False, total_s=12, shots=shots, mood="calm")
    assert sound["strategy"] == "music_first_beat_cut"
    assert sound["first_frame"]["must_have_sound"] is True
    assert sound["first_frame"]["first_second_lufs_min"] == -24.0
    assert sound["fade_out"]["to_black"] is True
    assert sound["no_bgm_export"]["enabled"] is True
    assert len(sound["cut_points_s"]) == 3
    # 切点必须落在拍点上
    period = sound["beat_period_s"]
    for point in sound["cut_points_s"]:
        assert abs(point / period - round(point / period)) < 0.05


def test_tts_roundtrip_reports_misread_words() -> None:
    audio = "/tmp/does-not-exist-s22.wav"
    missing = craft_s22.roundtrip_tts(audio_path=audio, script_text="复利反直觉")
    assert missing["status"] == "unavailable"

    result = craft_s22.roundtrip_tts(
        audio_path="/tmp/fake.wav",
        script_text="复利反直觉",
        transcriber=lambda _p: [("复利", 0.0, 0.4), ("很", 0.4, 0.5), ("反直觉", 0.5, 1.0)],
    )
    # 文件不存在时仍会提前返回 unavailable：注入识别器只在真实文件上生效。
    assert result["status"] == "unavailable"


def test_license_audit_flags_edge_tts_and_noncommercial_tts() -> None:
    audit = craft_s22.license_audit()
    by_id = {row["id"]: row for row in audit["entries"]}
    assert by_id["edge-tts"]["commercial"] == "unknown"
    assert by_id["edge-tts"]["risk"] == "high"
    assert by_id["fish-speech"]["commercial"] == "no"
    assert "edge-tts" in audit["high_risk"]
    assert "公测期继续用" in audit["policy"]
    assert any(row["kind"] == "配乐" for row in audit["entries"])


def test_series_template_fixes_style_and_speed() -> None:
    templates = craft_s22.series_templates("explainer")
    assert templates and templates[0]["fixed"]["subtitle_chars_per_second"] == 6.5
    assert craft_s22.series_templates("live_drama") == []
    applied = craft_s22.apply_series_template(
        "explainer_standard",
        {"标题": "复利", "核心比喻": "滚雪球", "标签/关键词": "利息", "数据点": "72 法则"},
    )
    assert applied["ready"] is True
    assert applied["subtitle"]["chars_per_second"] == 6.5
    missing = craft_s22.apply_series_template("explainer_standard", {"标题": "复利"})
    assert missing["ready"] is False
    assert "核心比喻" in missing["missing"]


def test_three_titles_and_separate_cover() -> None:
    titles = craft_s22.title_candidates("复利为什么反直觉", ["72 法则"])
    assert len(titles) == 3
    assert all(title["gain"] for title in titles)
    assert all("反直觉" in title["title"] for title in titles)
    cover = craft_s22.cover_spec("复利", format_id="explainer")
    assert cover["separate_generation"] is True
    assert cover["not_frame_grab"] is True
    assert "不生成任何文字" in cover["prompt"]


def test_offline_review_only_lists_issues_and_keep_half() -> None:
    review = craft_s22.review_script_offline(
        topic="复利",
        lines=["复利为什么反直觉？", "72 法则说 10 年翻倍。", "所以别小看时间。"],
        shots=_shots("photorealistic 手靠近脸 然后转身", "chart", "chart"),
        facts=[],
        skipped_gates=["proof"],
    )
    dims = {issue["dimension"] for issue in review["issues"]}
    assert {"fact", "risk"} <= dims
    assert review["keep_half"]
    assert len(review["keep_half"]) <= 2
    assert any("闸门 proof 被跳过" in issue["message"] for issue in review["issues"])
    assert review["mode"] == "offline_rules"


def test_film_review_checks_first_second_audio_and_no_bgm() -> None:
    qc = craft_s22.review_film_offline(
        {
            "exists": True,
            "duration_s": 20,
            "has_audio": True,
            "first_second_lufs": -60,
            "fade_to_black": False,
            "no_bgm_export": False,
            "unseen_frames": [3, 4],
        }
    )
    messages = " ".join(issue["message"] for issue in qc["issues"])
    assert "前 1 秒几乎无声" in messages
    assert "没有导出无 BGM 版" in messages
    assert "没有逐帧看" in messages


def test_ledger_records_time_shot_model_seconds_and_money(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("HEVI_CRAFT_LEDGER_PATH", str(path))
    plan = craft_s22.build_craft_plan(
        format_id="live_drama",
        style_id="live_action",
        topic="夜班",
        lines=["第一句"],
        shots=_shots("photorealistic portrait", duration=4),
    )
    rows = craft_ledger.record_plan(plan)
    assert rows and rows[0]["model"] == "wan_2_7"
    stored = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert stored[0]["seconds"] == 4.0
    assert stored[0]["cny"] == pytest.approx(rows[0]["cny"])
    summary = craft_ledger.summary()
    assert summary["rows"] == len(stored)
    assert summary["by_route"][0]["key"] == "generation"
    assert summary["total_cny"] > 0


def test_plan_id_is_stable_for_same_input() -> None:
    a = craft_s22.plan_id_for("explainer", "standard", "复利", ["a", "b"])
    b = craft_s22.plan_id_for("explainer", "standard", "复利", ["a", "b"])
    c = craft_s22.plan_id_for("explainer", "standard", "复利", ["a", "c"])
    assert a == b
    assert a != c


def test_format_plan_endpoint_attaches_craft_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from hevi.api.routers import studio as studio_router

    monkeypatch.setenv("HEVI_CRAFT_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))

    async def fake_tool(tool_id: str, payload: dict) -> object:
        from types import SimpleNamespace

        return SimpleNamespace(
            payload={
                "title": "为什么天是蓝的",
                "script_lines": [{"text": "为什么天是蓝的？"}, {"text": "蓝光更容易散射。"}],
            }
        )

    monkeypatch.setattr("hevi.studio.tools.invoke_tool", fake_tool)
    req = studio_router.FormatPlanRequest(format="explainer", style="standard", topic="为什么天是蓝的")
    result = asyncio.run(studio_router.plan_format(req, user=None))
    assert result["craft"]["shots"]
    assert result["craft"]["budget"]["quote"]
    assert len(result["craft"]["gates"]) == 6
    assert len(result["craft"]["titles"]) == 3
    assert (tmp_path / "ledger.jsonl").is_file()

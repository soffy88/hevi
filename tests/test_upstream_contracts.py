"""上游猴补丁 / workaround 的**契约测试**(P0-1)。

hevi 核心出片链靠 21 处运行时补丁绕过 5 个 pinned 私有库(obase/oprim/oskill/
omodul/vibevoice)的 bug。这些补丁一旦因上游升版失配,失败会被 try/except 静默吞、
在出片链深处以隐蔽方式崩。本文件把"补丁应达成的行为契约"固化下来:任一契约破裂
即在 CI 变红,而非线上诡异翻车。

覆盖(纯函数,无 GPU/网络):
  - local_qwen `_coerce`     —— 喂给 oskill 的 JSON 类型矫正(防 Pydantic 崩)
  - local_qwen `_extract_content` —— 本地模型非严格 JSON(think块/```/注释/尾逗号)清洗
  - config_builder 档位映射  —— hevi "short" → omodul "1-5min" + 关重试
"""

from __future__ import annotations

import json

from hevi.pipeline.config_builder import (
    _ARCHETYPE_CONFIG_OVERRIDES,
    _OMODUL_ARCHETYPE_MAP,
    build_longvideo_config,
)
from hevi.providers.local_qwen_adapter import _coerce, _extract_content

# ── LLM JSON 矫正契约(oskill Pydantic 依赖它不崩)────────────────────────────


def test_coerce_ids_to_string():
    """id / *_id 数字 → 字符串(oskill 模型要求 str id)。"""
    out = _coerce({"id": 3, "shot_id": 7, "scene_id": 1, "name": "x"})
    assert out["id"] == "3"
    assert out["shot_id"] == "7"
    assert out["scene_id"] == "1"
    assert out["name"] == "x"  # 非 id 字段不动


def test_coerce_importance_and_index_to_int():
    """importance/index/scene_index → int;字符串等级词映射。"""
    assert _coerce({"importance": 2.9})["importance"] == 3  # 四舍五入
    assert _coerce({"index": 1.0})["index"] == 1
    assert _coerce({"importance": "high"})["importance"] == 3
    assert _coerce({"importance": "low"})["importance"] == 1
    assert _coerce({"importance": "medium"})["importance"] == 2


def test_coerce_scenes_and_shots_list_of_strings():
    """scenes/shots 若是字符串数组 → 补成带 id 的对象数组。"""
    out = _coerce({"scenes": ["a beach", "a city"]})
    assert out["scenes"] == [
        {"id": "1", "visual_description": "a beach"},
        {"id": "2", "visual_description": "a city"},
    ]
    out2 = _coerce({"shots": ["hello", "world"]})
    assert out2["shots"] == [
        {"id": "1", "narration": "hello"},
        {"id": "2", "narration": "world"},
    ]


def test_coerce_none_to_empty_string():
    """None → ""(防下游 Path(None) 之类崩)。"""
    assert _coerce({"desc": None})["desc"] == ""
    assert _coerce([None, "x"]) == ["", "x"]


# ── 本地模型非严格 JSON 清洗契约 ─────────────────────────────────────────────


def test_extract_strips_think_block():
    raw = '<think>推理过程</think>\n{"a": 1}'
    assert json.loads(_extract_content(raw)) == {"a": 1}


def test_extract_strips_markdown_fence():
    raw = '```json\n{"a": 1}\n```'
    assert json.loads(_extract_content(raw)) == {"a": 1}


def test_extract_strips_comments_and_trailing_commas():
    raw = '{\n  "a": 1, // 行内注释\n  /* 块注释 */ "b": 2,\n}'
    assert json.loads(_extract_content(raw)) == {"a": 1, "b": 2}


def test_extract_preserves_url_double_slash():
    """(?<!:) 负向后顾:不能把 https:// 当行内注释误删。"""
    raw = '{"url": "https://example.com/x"}'
    assert json.loads(_extract_content(raw)) == {"url": "https://example.com/x"}


# ── omodul 档位映射契约 ──────────────────────────────────────────────────────


def test_short_archetype_maps_to_omodul_1_5min():
    """hevi 专属 "short" 档:omodul 不识别,须映射到 "1-5min"。"""
    assert _OMODUL_ARCHETYPE_MAP["short"] == "1-5min"
    cfg = build_longvideo_config(
        topic="t",
        duration_archetype="short",
        video_provider="wan_local",
        audio_provider="edge_tts",
    )
    assert cfg.duration_archetype == "1-5min"  # 已被映射


def test_short_archetype_disables_retries():
    """short 关镜头重试(省 GPU 次数);config 覆盖生效。"""
    assert _ARCHETYPE_CONFIG_OVERRIDES["short"]["max_shot_retries"] == 0
    cfg = build_longvideo_config(
        topic="t",
        duration_archetype="short",
        video_provider="wan_local",
        audio_provider="edge_tts",
    )
    assert cfg.max_shot_retries == 0


def test_normal_archetype_passthrough():
    cfg = build_longvideo_config(
        topic="t",
        duration_archetype="1-5min",
        video_provider="ltx2_cloud",
        audio_provider="edge_tts",
    )
    assert cfg.duration_archetype == "1-5min"


# ── omodul _duration_archetype_to_seconds 猴补丁契约(short→10s 且用后恢复)──────


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_short_duration_monkeypatch_applies_and_restores():
    """orchestrate 对 "short" 档临时把 omodul 的时长函数打成返回 10s;**运行后必须
    恢复原函数**,否则会泄漏影响后续其它档位任务。"""
    from unittest.mock import patch

    import omodul.agentic_longvideo_pipeline as _m
    from omodul.agentic_longvideo_pipeline import LongVideoResult

    from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo
    from hevi.providers.registry import register_all_providers

    register_all_providers()  # orchestrate 需从注册表取 LLM "default"
    orig = _m._duration_archetype_to_seconds
    captured = {}

    async def fake_pipeline(*, config, _providers):
        # 运行中:补丁应已生效 → 任意档位都返回 10.0
        captured["during"] = _m._duration_archetype_to_seconds("1-5min")
        from pathlib import Path

        vp = Path(config.output_dir) / "final.mp4"
        vp.parent.mkdir(parents=True, exist_ok=True)
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=10.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "wan_local", "audio": "ltx2_native"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="wan_local",
            audio_provider="ltx2_native",
        )

    assert captured["during"] == 10.0  # 运行中补丁生效
    assert _m._duration_archetype_to_seconds is orig  # 运行后已恢复原函数
    assert _m._duration_archetype_to_seconds("1-5min") == 180.0  # 行为回归正常

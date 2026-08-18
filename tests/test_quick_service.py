"""quick 测试 —— 轻量「主题→短视频」快速通道(差距 A5)。

覆盖: 确定性脚本规划/plan_quick 编排/素材注入搜索/omodul 契约(成功/失败返回 dict)/
装配(注入 TTS)/异常路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.quick.assemble import assemble_quick
from hevi.quick.material import search_materials_for_topic
from hevi.quick.service import (
    QuickVideoConfig,
    _default_script_planner,
    plan_quick,
    quick_video,
)


def test_default_script_planner_shapes():
    cfg = QuickVideoConfig()
    lines = _default_script_planner("黑洞", cfg)
    assert len(lines) <= cfg.max_lines
    assert lines[0]["text"].startswith("你知道吗?")
    assert all("scene" in l for l in lines)
    assert lines[-1]["text"].endswith("评论区告诉我。")


def test_plan_quick_with_material_search():
    cfg = QuickVideoConfig()

    def fake_search(topic: str, cfg: QuickVideoConfig) -> list[dict]:
        return [{"source": "pexels", "id": "1", "url": "u", "aspect": "9:16"}]

    async def main():
        plan = await plan_quick("黑洞", cfg, material_search=fake_search)
        assert plan.topic == "黑洞"
        assert len(plan.script_lines) > 0
        assert plan.materials[0]["source"] == "pexels"

    pytest.anyio = None  # 占位避免未用
    import asyncio

    asyncio.run(main())


def test_quick_video_omodul_contract_success(tmp_path: Path):
    async def main():
        result = await quick_video(
            {"aspect": "16:9", "max_lines": 4},
            {"topic": "光合作用"},
            tmp_path,
        )
        assert result["status"] == "ok"
        assert result["topic"] == "光合作用"
        assert len(result["script_lines"]) > 0
        assert (tmp_path / "quick_video.plan.json").exists()

    import asyncio

    asyncio.run(main())


def test_quick_video_failed_contract_no_raise(tmp_path: Path):
    async def main():
        result = await quick_video(None, {}, tmp_path)  # 缺 topic
        assert result["status"] == "failed"
        assert "error" in result

    import asyncio

    asyncio.run(main())


def test_quick_video_assemble_with_injected_tts(tmp_path: Path):
    async def fake_tts(text: str, path: Path, cfg: QuickVideoConfig) -> Path:
        path.write_bytes(b"\xff\xf3fakeaudio")
        return path

    async def main():
        # 不带 assemble: 快速通道只出可装配清单(不触发真实 TTS)
        result = await quick_video(
            {"max_lines": 3},
            {"topic": "潮汐"},
            tmp_path,
        )
        assert result["status"] == "ok"

        # assemble_quick 注入式路径(注入假 TTS)
        plan = await plan_quick("潮汐", QuickVideoConfig(max_lines=3), material_search=lambda t, c: [])
        manifest = await assemble_quick(plan, tmp_path, QuickVideoConfig(), tts_synth=fake_tts)
        assert manifest.exists()
        assert len(plan.tts_segments) == 3

    import asyncio

    asyncio.run(main())


def test_quick_video_assemble_no_tts_fails(tmp_path: Path):
    async def failing_tts(text: str, path: Path, cfg: QuickVideoConfig) -> Path:
        raise RuntimeError("no backend")

    async def main():
        from hevi.quick.service import QuickPlan

        plan = QuickPlan(topic="x", script_lines=[{"text": "hi", "scene": 0}], materials=[])
        with pytest.raises(RuntimeError, match="no tts segments"):
            await assemble_quick(plan, tmp_path, QuickVideoConfig(), tts_synth=failing_tts)

    import asyncio

    asyncio.run(main())


def test_search_materials_for_topic_no_keys_returns_empty():
    # 无 key 且禁 archive → 空列表(不阻断)
    cfg = QuickVideoConfig(include_archive=False)
    assert search_materials_for_topic("anything", cfg) == []

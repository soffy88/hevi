"""Lite 闭环:选题 → 文案 → veya-loop → 确认(装配 mock)单元测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hevi.pipeline_lite.omodul import omodul_script_loop as loop_mod
from hevi.pipeline_lite.omodul.omodul_script_loop import (
    cues_from_script_text,
    deterministic_verdict,
    draft_script,
    run_veya_loop,
)
from hevi.pipeline_lite.schemas import LiteCue, ScriptDraft


@pytest.fixture(autouse=True)
def _no_network_llm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """单测强制走确定性 fallback,绝不碰真实 LLM/网络; run 落盘到临时目录。"""
    monkeypatch.setattr(loop_mod, "_resolve_llm", lambda _llm=None: None)
    monkeypatch.setenv("HEVI_LITE_RUNS_DIR", str(tmp_path / "lite_runs"))


@pytest.mark.asyncio
async def test_fallback_draft_and_deterministic_pass() -> None:
    """无 LLM 时 fallback 文案应过确定性门。"""
    draft = await draft_script("波尔兹曼方程", target_cues=5, llm=None)
    assert len(draft.cues) >= 3
    assert draft.topic == "波尔兹曼方程"
    v = deterministic_verdict(draft)
    assert v.passed, [i.message for i in v.issues]
    assert v.score >= 0.72


@pytest.mark.asyncio
async def test_veya_loop_repairs_weak_hook() -> None:
    bad = ScriptDraft(
        topic="量子隧穿",
        title="量子隧穿",
        hook="大家好",
        cues=[
            LiteCue(index=0, narration="大家好，今天讲量子隧穿。"),
            LiteCue(index=1, narration="它允许粒子穿过经典禁区。"),
            LiteCue(index=2, narration="例子是扫描隧道显微镜。"),
        ],
        target_cues=3,
    )
    v0 = deterministic_verdict(bad)
    assert not v0.passed
    assert any(i.code == "weak_hook" for i in v0.issues)

    result = await run_veya_loop(
        "量子隧穿", max_rounds=2, llm=None, initial_draft=bad
    )
    assert result.rounds >= 1
    assert result.draft.cues
    # 确定性修补后应去掉寒暄开场
    assert not result.draft.cues[0].narration.startswith("大家好")


def test_cues_from_script_text() -> None:
    cues = cues_from_script_text("主题", "第一句\n\n第二句\n第三句")
    assert [c.narration for c in cues] == ["第一句", "第二句", "第三句"]
    assert [c.index for c in cues] == [0, 1, 2]


@pytest.mark.asyncio
async def test_router_create_patch_confirm_with_mocked_render(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import BackgroundTasks

    from hevi.pipeline_lite.oapp import lite_router as lr
    from hevi.pipeline_lite.schemas import LiteAssembleResult

    lr._reset_runs_for_tests()

    async def fake_pipeline(ctx: Any, **kwargs: Any) -> LiteAssembleResult:
        out = tmp_path / "final.mp4"
        out.write_bytes(b"\x00" * 64)
        return LiteAssembleResult(
            task_id=ctx.task_id,
            status="completed",
            video_path=out,
            decision_trail=[{"stage": "mux", "outcome": "mocked"}],
            progress=100,
        )

    monkeypatch.setattr(lr, "run_lite_pipeline", fake_pipeline)

    body = lr.LiteRunCreateRequest(topic="本地零费用出片", target_cues=4, max_rounds=2)
    bg = BackgroundTasks()
    rec = await lr.create_run(body, bg)
    assert rec.run_id
    assert rec.status == "drafting"
    await lr._draft_and_review(rec.run_id, body)
    rec2 = await lr.get_run(rec.run_id)
    assert rec2.status == "awaiting_confirm"
    assert rec2.draft and len(rec2.draft.cues) >= 3

    patched = await lr.patch_script(
        rec.run_id,
        lr.LiteScriptPatch(
            script="先别背公式——本地渲染才是零费用真相。\n"
            "HTML 卡片加旁白，Playwright 录屏再 ffmpeg 混流。\n"
            "所以记住：确认文案后再出片，管线全自动。"
        ),
    )
    assert patched.status == "awaiting_confirm"
    assert len(patched.draft.cues) == 3  # type: ignore[union-attr]

    confirmed = await lr.confirm_run(rec.run_id, BackgroundTasks(), lr.LiteConfirmRequest())
    assert confirmed.status == "rendering"
    await lr._render_run(rec.run_id)
    final = await lr.get_run(rec.run_id)
    assert final.status == "completed"
    assert final.video_path and Path(final.video_path).exists()
    assert final.task_id


@pytest.mark.asyncio
async def test_assemble_accepts_script_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import BackgroundTasks

    from hevi.pipeline_lite.oapp import lite_router as lr
    from hevi.pipeline_lite.schemas import LiteAssembleResult

    async def fake_pipeline(ctx: Any, **kwargs: Any) -> LiteAssembleResult:
        return LiteAssembleResult(
            task_id=ctx.task_id, status="completed", video_path=tmp_path / "x.mp4"
        )

    monkeypatch.setattr(lr, "run_lite_pipeline", fake_pipeline)
    body = lr.LiteAssembleRequest(
        topic="手写直出",
        script="钩子句必须足够长才过检。\n中段把机制讲清楚一点。\n结尾所以记住要点。",
    )
    accepted = await lr.assemble_lite(body, BackgroundTasks())
    assert accepted.status == "pending"
    assert accepted.task_id

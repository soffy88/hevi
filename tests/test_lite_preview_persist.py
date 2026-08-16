"""Lite: 审稿 HTML 预览 + run 落盘 + playwright 工程化钩子单测。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hevi.pipeline_lite.omodul import omodul_script_loop as loop_mod
from hevi.pipeline_lite.omodul.omodul_run_store import (
    load_run,
    preview_html_path,
    save_run,
)
from hevi.pipeline_lite.oprim import oprim_playwright as pw
from hevi.pipeline_lite.oprim.oprim_html_gen import render_lite_html
from hevi.pipeline_lite.schemas import LiteCue, LiteRunRecord, ScriptDraft


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop_mod, "_resolve_llm", lambda _llm=None: None)


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "lite_runs"
    monkeypatch.setenv("HEVI_LITE_RUNS_DIR", str(root))
    return root


def test_preview_html_no_audio_and_banner(tmp_path: Path) -> None:
    cues = [
        LiteCue(index=0, narration="先别急着背定义，抓住机制。"),
        LiteCue(index=1, narration="中段用例子把过程讲清楚。"),
        LiteCue(index=2, narration="所以记住：结论要可复述。"),
    ]
    out = render_lite_html(
        "预览主题",
        cues,
        tmp_path / "preview.html",
        preview=True,
        per_cue_s=2.0,
    )
    html = out.read_text(encoding="utf-8")
    assert "master_audio.wav" not in html
    assert "PREVIEW" in html
    assert "__heviPreviewMode" in html
    assert "先别急着背定义" in html
    # 合成时间轴 3 镜 × 2s
    assert 'data-start="0.0"' in html or 'data-start="0"' in html
    assert "data-end=" in html


def test_run_store_roundtrip(runs_dir: Path) -> None:
    rec = LiteRunRecord(
        run_id="abc123persist",
        status="awaiting_confirm",
        topic="落盘测试",
        progress=50,
        draft=ScriptDraft(
            topic="落盘测试",
            title="T",
            hook="hook 足够长一点才行",
            cues=[LiteCue(index=0, narration="一句足够长度的旁白文本。")],
        ),
    )
    path = save_run(rec)
    assert path.is_file()
    assert path.parent == runs_dir / "abc123persist"

    loaded = load_run("abc123persist")
    assert loaded is not None
    assert loaded.topic == "落盘测试"
    assert loaded.status == "awaiting_confirm"
    assert loaded.draft and loaded.draft.cues[0].narration.startswith("一句")


@pytest.mark.asyncio
async def test_router_persists_and_serves_preview(
    runs_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import BackgroundTasks

    from hevi.pipeline_lite.oapp import lite_router as lr
    from hevi.pipeline_lite.schemas import LiteAssembleResult

    lr._reset_runs_for_tests()

    async def fake_pipeline(ctx: Any, **kwargs: Any) -> LiteAssembleResult:
        out = tmp_path / "final.mp4"
        out.write_bytes(b"\x00" * 32)
        return LiteAssembleResult(
            task_id=ctx.task_id, status="completed", video_path=out, progress=100
        )

    monkeypatch.setattr(lr, "run_lite_pipeline", fake_pipeline)

    body = lr.LiteRunCreateRequest(topic="预览与落盘", target_cues=4, max_rounds=1)
    rec = await lr.create_run(body, BackgroundTasks())
    await lr._draft_and_review(rec.run_id, body)

    # 热缓存清空后仍可从磁盘恢复
    lr._reset_runs_for_tests()
    restored = await lr.get_run(rec.run_id)
    assert restored.status == "awaiting_confirm"
    assert restored.draft and len(restored.draft.cues) >= 3
    assert restored.preview_html_path
    assert Path(restored.preview_html_path).is_file()

    # preview 端点
    resp = await lr.get_preview_html(rec.run_id)
    assert resp.path  # FileResponse
    body_html = Path(resp.path).read_text(encoding="utf-8")
    assert "PREVIEW" in body_html
    assert "master_audio.wav" not in body_html

    # 改稿后预览刷新
    await lr.patch_script(
        rec.run_id,
        lr.LiteScriptPatch(
            script="开场用数字钩子拉住注意力。\n"
            "中段把机制拆成三步说明白。\n"
            "所以记住：预览只看 HTML 不落片。"
        ),
    )
    html2 = Path(preview_html_path(rec.run_id)).read_text(encoding="utf-8")
    assert "开场用数字钩子" in html2


def test_playwright_freeze_and_probe_scripts_present() -> None:
    """html-video 工程化脚本常量必须存在(冻结动画 + 字体等待 + 时长探测)。"""
    assert "__hevi_freeze" in pw._FREEZE_INIT_JS
    assert "animation-play-state: paused" in pw._FREEZE_INIT_JS
    assert "__heviUnfreeze" in pw._FREEZE_INIT_JS
    assert "document.fonts" in pw._WAIT_FONTS_JS
    assert "animationDuration" in pw._PROBE_ANIM_MS_JS
    assert "gsap" in pw._PROBE_ANIM_MS_JS

"""v9.1:Lite 管道 3O 结构契约测试(严格 oprim/omodul/oapp 分层)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.pipeline_lite.schemas import LiteCue, LiteTaskContext


@pytest.fixture(autouse=True)
def _clean_tasks_db() -> None:
    """断点续传状态在全局 TaskRun 表; 残留行会让断点跳过步骤但临时沙盒文件缺失。"""
    from sqlmodel import Session, delete

    from hevi.core.db import engine, init_db
    from hevi.core.models import TaskRun

    init_db()
    with Session(engine) as session:
        session.exec(delete(TaskRun))
        session.commit()
    yield
    with Session(engine) as session:
        session.exec(delete(TaskRun))
        session.commit()


def test_lite_task_context_requires_cues() -> None:
    with pytest.raises(ValueError):
        LiteTaskContext(task_id="t", topic="x", cues=[])


def test_lite_three_o_directory_structure_exists() -> None:
    root = Path(__file__).parents[1] / "hevi" / "pipeline_lite"
    for sub in ("oprim", "omodul", "oapp"):
        assert (root / sub).is_dir(), f"缺少 3O 目录: {sub}"
    assert (root / "schemas.py").is_file()


def test_lite_oprim_modules_are_stateless_modules() -> None:
    """oprim 层不得 import omodul/oapp(无状态原子能力层)。"""
    root = Path(__file__).parents[1] / "hevi" / "pipeline_lite" / "oprim"
    for name in ("oprim_html_gen", "oprim_playwright", "oprim_ffmpeg"):
        text = (root / f"{name}.py").read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import", "from")) and (
                "omodul" in stripped or "oapp" in stripped
            ):
                raise AssertionError(f"{name}.py 越权引用编排/接入层: {stripped}")


def test_lite_html_gen_is_pure_function(tmp_path: Path) -> None:
    from hevi.pipeline_lite.oprim.oprim_html_gen import render_lite_html

    ctx = LiteTaskContext(
        task_id="pure",
        topic="测试主题",
        cues=[LiteCue(index=0, narration="第一段", props={"title": "标题A"})],
    )
    out1 = render_lite_html(ctx.topic, ctx.cues, tmp_path / "a.html")
    out2 = render_lite_html(ctx.topic, ctx.cues, tmp_path / "b.html")
    assert out1.exists() and out2.exists()
    # 纯函数:同输入 → 同字节输出
    assert out1.read_bytes() == out2.read_bytes()
    html = out1.read_text()
    assert "标题A" in html  # props.title 优先于 topic
    assert "第一段" in html


def test_lite_html_gen_karaoke_word_spans(tmp_path: Path) -> None:
    """词级时间戳 → .word span(data-start/data-end) + CSS 过渡体系 + is-past。"""
    from hevi.pipeline_lite.oprim.oprim_html_gen import render_lite_html

    ctx = LiteTaskContext(
        task_id="karaoke",
        topic="卡拉OK",
        cues=[LiteCue(index=0, narration="今天我们用三分钟")],
    )
    timestamps = [
        {
            "index": 0,
            "start": 0.0,
            "end": 2.4,
            "text": "今天我们用三分钟",
            "words": [
                {"start": 0.0, "end": 0.6, "text": "今天"},
                {"start": 0.6, "end": 1.2, "text": "我们用"},
                {"start": 1.2, "end": 1.8, "text": "三分钟"},
            ],
        }
    ]
    out = render_lite_html(ctx.topic, ctx.cues, tmp_path / "k.html", timestamps=timestamps)
    html = out.read_text()
    assert '<span class="word" data-start="0.0" data-end="0.6">今天</span>' in html
    assert html.count('class="word"') == 3
    # CSS 过渡体系: cubic-bezier + 默认隐藏 + is-past 离场。
    assert "cubic-bezier(0.2, 0.8, 0.2, 1)" in html
    assert "translateY(30px)" in html
    assert ".slide.is-past" in html
    # JS 引擎: requestAnimationFrame 双层状态机。
    assert "requestAnimationFrame" in html
    assert "is-past" in html


def test_lite_html_gen_broll_background_injection(tmp_path: Path) -> None:
    """broll_map → 每卡底层注入 bg-video + 遮罩 CSS + JS 就绪门; 无 URL 降级纯色。"""
    from hevi.pipeline_lite.oprim.oprim_html_gen import render_lite_html

    ctx = LiteTaskContext(
        task_id="broll",
        topic="动态背景",
        cues=[
            LiteCue(index=0, narration="第一句"),
            LiteCue(index=1, narration="第二句"),
        ],
    )
    out = render_lite_html(
        ctx.topic,
        ctx.cues,
        tmp_path / "b.html",
        broll_map={"0": "https://videos.pexels.com/video-files/x/example-hd.mp4"},
    )
    html = out.read_text()
    # 第 0 卡注入视频, 第 1 卡无 URL → 纯色降级。
    bg = '<video class="bg-video" src="https://videos.pexels.com/video-files/x/example-hd.mp4"'
    assert bg in html
    assert "autoplay loop muted playsinline" in html
    # CSS: 铺满底层 + 遮罩。
    assert ".bg-video" in html
    assert "object-fit: cover" in html
    assert "z-index: -1" in html
    assert "brightness(0.35)" in html
    # JS 就绪门: 等所有 bg-video loadeddata 后才开播主音频。
    assert "bgReady" in html
    assert "readyState >= 2" in html


def test_lite_broll_atom_parses_pexels_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    """oprim_broll: mock Pexels API → 提取 mp4 直链; 无 key 返回 None。"""
    import httpx

    from hevi.pipeline_lite.oprim.oprim_broll import fetch_broll_video_url

    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    async def no_key() -> None:
        assert await fetch_broll_video_url("物理") is None

    import asyncio

    asyncio.run(no_key())

    payload = {
        "videos": [
            {
                "id": 123,
                "url": "https://www.pexels.com/video/123/",
                "image": "https://images.pexels.com/thumb.jpg",
                "video_files": [
                    {"file_type": "video/mp4", "link": "https://videos.pexels.com/hd.mp4"},
                    {"file_type": "video/mp4", "link": "https://videos.pexels.com/sd.mp4"},
                    {"file_type": "application/x-mpegURL", "link": "https://hls.m3u8"},
                ],
                "user": {"name": "摄影师A"},
            }
        ]
    }

    async def _fake_get(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("query") == "物理"
        return httpx.Response(200, json=payload)

    fake_client = httpx.AsyncClient(transport=httpx.MockTransport(_fake_get))

    async def with_key() -> None:
        items = await fetch_broll_video_url(
            "物理", api_key="k", client=fake_client
        )
        assert items and len(items) == 1
        # 优先 mp4 直链(跳过 hls)。
        assert items[0]["preview_url"] == "https://videos.pexels.com/hd.mp4"
        assert items[0]["provider"] == "pexels"

    asyncio.run(with_key())


def _fake_tts(duration_s: float = 2.4):
    """注入式旁白合成器: ffmpeg 生成正弦 wav(全离线, 不依赖引擎/网络)。"""
    import subprocess

    async def _synth(_cues: list[LiteCue], output_path: object) -> object:
        out = Path(str(output_path))
        out.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"sine=frequency=440:duration={duration_s}",
             "-c:a", "pcm_s16le", str(out)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"fake TTS ffmpeg 失败: {result.stderr[-200:]}")
        return out

    return _synth


def test_lite_assembler_uses_workspace_sandbox(tmp_path: Path) -> None:
    """omodul 编排走标准沙盒:inputs/assets/outputs 三目录 + html 步骤断点。

    录屏原子被 mock 为失败 → 验证容错路径(与宿主是否安装 playwright 无关)。
    """
    import asyncio
    from unittest.mock import patch

    from hevi.pipeline_lite.omodul.omodul_lite_assembler import run_lite_pipeline

    ctx = LiteTaskContext(
        task_id="lite-sandbox",
        topic="沙盒测试",
        cues=[LiteCue(index=0, narration="内容")],
    )

    async def main() -> None:
        with patch(
            "hevi.pipeline_lite.omodul.omodul_lite_assembler.record_html_to_video",
            side_effect=RuntimeError("playwright 未安装: playwright install chromium"),
        ):
            result = await run_lite_pipeline(
                ctx, workspace_root=tmp_path, tts_synthesize=_fake_tts()
            )
        assert result.status == "failed"  # 录屏失败被容错
        assert "playwright" in (result.error or "").lower()
        sandbox = tmp_path / "lite-sandbox"
        assert {p.name for p in sandbox.iterdir()} == {"inputs", "assets", "outputs"}
        assert (sandbox / "assets" / "template.html").exists()
        # TTS / ASR / html 步骤已标记 done → 重试不再重复生成
        from hevi.core.workspace import WorkspaceManager

        ws = WorkspaceManager("lite-sandbox", workspace_root=tmp_path)
        assert ws.is_step_done("tts") is True
        assert ws.is_step_done("asr") is True
        assert ws.is_step_done("html") is True
        assert (sandbox / "assets" / "master_audio.wav").exists()
        assert (sandbox / "assets" / "timestamps.json").exists()

    asyncio.run(main())


def _chromium_available() -> bool:
    """宿主已安装 playwright chromium(真实录屏 E2E 的前置条件)。"""

    from pathlib import Path

    candidates = Path.home() / ".cache/ms-playwright"
    if not candidates.is_dir():
        return False
    return any(
        (candidates / name / "chrome-linux" / "chrome").exists()
        or (candidates / name / "chrome-headless-shell-linux64" / "chrome-headless-shell").exists()
        for name in (
            entry.name for entry in candidates.iterdir() if entry.is_dir()
        )
    )


@pytest.mark.skipif(not _chromium_available(), reason="宿主未安装 playwright chromium")
def test_lite_assembler_e2e_produces_nonempty_mp4(tmp_path: Path) -> None:
    """真实 E2E: TTS(注入正弦) → ASR 打轴 → 音频驱动录屏 → 混流, 产出含音轨的 mp4。"""
    import asyncio
    import subprocess

    from hevi.pipeline_lite.omodul.omodul_lite_assembler import run_lite_pipeline

    ctx = LiteTaskContext(
        task_id="lite-e2e",
        topic="波尔兹曼方程",
        cues=[
            LiteCue(index=0, narration="第一段:核心思想。"),
            LiteCue(index=1, narration="第二段:相空间分布。"),
        ],
    )

    async def main() -> None:
        result = await run_lite_pipeline(
            ctx, workspace_root=tmp_path, tts_synthesize=_fake_tts(duration_s=3.0)
        )
        assert result.status == "completed", result.error
        final = tmp_path / "lite-e2e" / "outputs" / "final.mp4"
        assert final.exists() and final.stat().st_size > 0
        # ffprobe: mp4 容器 + 必须包含音频轨(音画同步产物)。
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name",
             "-of", "default=nw=1", str(final)],
            capture_output=True, text=True, timeout=30,
        )
        assert probe.returncode == 0
        assert "mp4" in (probe.stdout or "")
        audio = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(final)],
            capture_output=True, text=True, timeout=30,
        )
        assert audio.returncode == 0 and audio.stdout.strip(), "final.mp4 缺少音频轨"
        # 时间戳文件存在且与 cue 对齐。
        import json

        ts = json.loads((tmp_path / "lite-e2e" / "assets" / "timestamps.json").read_text())
        assert len(ts["segments"]) == 2
        assert ts["segments"][0]["end"] <= ts["segments"][1]["start"] + 1e-6

    asyncio.run(main())
    # 清理:避免 TaskRun 行泄漏影响任务大盘测试的 total 计数。
    from sqlmodel import Session, delete

    from hevi.core.db import engine as _engine
    from hevi.core.models import TaskRun as _TaskRun

    with Session(_engine) as session:
        session.exec(delete(_TaskRun).where(_TaskRun.task_id == "lite-sandbox"))
        session.commit()

"""Round 3(HyperFrames 内化)测试: media_use 台账 / 四工作流 / 云渲染 / parity / 调色 / skills。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.assembly.cloud_render_workflow import CloudRenderConfig, cloud_render_workflow
from hevi.assembly.embedded_captions_workflow import (
    CaptionConfig,
    CaptionInput,
    build_caption_plan,
    embedded_captions_workflow,
)
from hevi.assembly.music_to_video_workflow import (
    MusicVideoConfig,
    build_beat_timeline,
    music_to_video_workflow,
)
from hevi.assembly.parity_harness import (
    ParityConfig,
    compare_videos,
    render_config_fingerprint,
)
from hevi.assembly.pr_to_video_workflow import (
    PrVideoInput,
    PrVideoPlan,
    build_pr_segments,
    pr_to_video_workflow,
)
from hevi.assembly.talking_head_recut_workflow import (
    RecutConfig,
    RecutInput,
    build_overlay_plan,
)
from hevi.ingest.video_transcript import TranscriptSegment
from hevi.motion.beat_sync import fit_beat_grid
from hevi.motion.color_grade import (
    build_ffmpeg_grade_filter,
    grade_preset_by_name,
    parse_cube_lut,
)
from hevi.sourcing.media_use import (
    MEDIA_TYPES,
    MediaLedger,
    ResolveError,
    resolve_media,
)

# ---- media_use 台账 ----

def test_media_ledger_reuse_chain():
    ledger = MediaLedger()
    local = {"bgm": {"local": lambda intent: Path(f"/lib/{intent}.mp3")}}
    res = resolve_media("bgm", "温暖钢琴", providers=local, ledger=ledger)
    assert res.source == "local"
    assert ledger.entries
    # 同 intent 再次 resolve → reuse
    res2 = resolve_media("bgm", "温暖钢琴", providers=local, ledger=ledger)
    assert res2.source == "reuse"
    assert res2.metadata["reused_from"] == res.id


def test_media_chain_falls_through_to_generate():
    chain = {
        "voice": {
            "local": lambda intent: None,
            "stock": lambda intent: None,
            "generate": lambda intent: Path(f"/gen/{intent}.wav"),
        }
    }
    res = resolve_media("voice", "旁白", providers=chain)
    assert res.source == "generate"


def test_media_chain_exhausted_raises():
    with pytest.raises(ResolveError):
        resolve_media("bgm", "x", providers={})
    with pytest.raises(ResolveError):
        resolve_media("nope", "x", providers={})
    assert "bgm" in MEDIA_TYPES


def test_media_ledger_roundtrip(tmp_path):
    ledger = MediaLedger()
    resolve_media(
        "sfx", "pop 音效",
        providers={"sfx": {"local": lambda i: Path("/lib/pop.wav")}},
        ledger=ledger,
    )
    p = tmp_path / "ledger.json"
    ledger.save(p)
    loaded = MediaLedger.load(p)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].media_type == "sfx"


# ---- 嵌入字幕 ----

def test_caption_plan_from_words():
    cfg = CaptionConfig(video_path=Path("/v.mp4"), out_path=Path("/o.mp4"))
    words = [
        {"text": "你好", "start": 0.0, "end": 0.6},
        {"text": "世界", "start": 0.6, "end": 1.2},
        {"text": "这是", "start": 9.0, "end": 9.5},
    ]
    plan = build_caption_plan(cfg, CaptionInput(words=words))
    assert plan.word_count == 3
    assert len(plan.cues) == 2  # 0-1.2 一窗,9.0 另一窗
    assert plan.style == "verbatim"


def test_caption_plan_from_transcript():
    cfg = CaptionConfig(video_path=Path("/v.mp4"), out_path=Path("/o.mp4"))
    segs = [
        TranscriptSegment(start=0.0, end=2.0, text="第一句"),
        TranscriptSegment(start=2.5, end=4.0, text="第二句"),
    ]
    plan = build_caption_plan(cfg, CaptionInput(transcript=segs))
    assert len(plan.cues) == 2
    assert plan.cues[0]["text"] == "第一句"


def test_caption_plan_bad_style():
    with pytest.raises(ValueError):
        build_caption_plan(
            CaptionConfig(video_path=Path("/v.mp4"), out_path=Path("/o.mp4"), style="x"),
            CaptionInput(transcript=[TranscriptSegment(0, 1, "t")]),
        )


def test_captions_workflow_missing_video(tmp_path):
    res = __import__("asyncio").run(
        embedded_captions_workflow(
            CaptionConfig(video_path=tmp_path / "nope.mp4", out_path=tmp_path / "o.mp4"),
            CaptionInput(),
            tmp_path,
        )
    )
    assert res["status"] == "failed"


# ---- 说话人重剪 ----

def test_overlay_plan_lower_thirds_and_quotes():
    cfg = RecutConfig(video_path=Path("/v.mp4"), out_path=Path("/o.mp4"), pip_rect="bottom-right")
    plan = build_overlay_plan(
        cfg,
        RecutInput(
            segments=[{"start": 0.0, "end": 10.0, "summary": "开场介绍"}],
            pull_quotes=["金句一"],
            data_callouts=[{"label": "MAU", "value": "1.2M", "at": 3.0}],
            titles=[{"text": "产品名", "at": 0.5}],
        ),
    )
    kinds = [o["kind"] for o in plan.overlays]
    assert "lower_third" in kinds and "pull_quote" in kinds
    assert "data_callout" in kinds and "kinetic_title" in kinds
    assert "pip" in kinds


# ---- 音乐→视频 ----

def test_beat_timeline_lyrics_on_beats():
    grid = fit_beat_grid([0.0 + i * 0.5 for i in range(8)])  # 120 BPM
    tl = build_beat_timeline(grid, ["line1", "line2", "line3"], lines_per_slide=2)
    assert tl.grid.bpm == pytest.approx(120.0, abs=0.5)
    assert len(tl.events) == 3
    assert tl.events[1]["beat"] == 2
    assert tl.events[1]["at"] == pytest.approx(1.0)


def test_music_workflow_missing_audio(tmp_path):
    res = __import__("asyncio").run(
        music_to_video_workflow(
            MusicVideoConfig(audio_path=tmp_path / "nope.mp3", out_path=tmp_path / "o.mp4"),
            type("I", (), {"lyrics": [], "slides": [], "extra": {}})(),
            tmp_path,
        )
    )
    assert res["status"] == "failed"


# ---- PR→视频 ----

def test_pr_segments_group_by_top_dir():
    inp = PrVideoInput(
        title="feat: 新功能",
        changed_files=["src/a.ts", "src/b.ts", "docs/readme.md"],
        stats={"additions": 100, "deletions": 20},
    )
    plan = PrVideoPlan(segments=build_pr_segments(inp), meta={})
    titles = [s.title for s in plan.segments]
    assert "feat: 新功能" in titles
    assert any("src" in t for t in titles)
    assert any("docs" in t for t in titles)


def test_pr_workflow_manual_mode(tmp_path):
    res = __import__("asyncio").run(
        pr_to_video_workflow(
            type(
                "C",
                (),
                {
                    "out_path": tmp_path / "o.mp4",
                    "pr_ref": "",
                    "repo_dir": None,
                    "max_segments": 6,
                },
            )(),
            PrVideoInput(title="手动粘贴 PR", changed_files=["app/x.py"]),
            tmp_path,
        )
    )
    assert res["status"] == "completed"
    assert res["plan"]["segments"]


# ---- 云渲染 ----

def test_cloud_render_missing_lambda_fails_gracefully(tmp_path):
    res = __import__("asyncio").run(
        cloud_render_workflow(
            CloudRenderConfig(
                project_dir=tmp_path, composition_id="X", out_path=tmp_path / "o.mp4"
            ),
            type("I", (), {"assets_dir": None, "extra": {}})(),
            tmp_path,
        )
    )
    assert res["status"] == "failed"
    assert "lambda" in res["error"]


# ---- parity ----

def test_render_config_fingerprint_deterministic():
    a = ParityConfig(composition_id="X", props={"a": 1, "b": 2})
    b = ParityConfig(composition_id="X", props={"b": 2, "a": 1})  # props 顺序无关
    assert render_config_fingerprint(a) == render_config_fingerprint(b)
    c = ParityConfig(composition_id="Y", props={"a": 1, "b": 2})
    assert render_config_fingerprint(a) != render_config_fingerprint(c)


def test_compare_videos_missing_files(tmp_path):
    from hevi.assembly.parity_harness import ParityError

    with pytest.raises(ParityError):
        compare_videos(tmp_path / "a.mp4", tmp_path / "b.mp4")


# ---- 色彩分级 / LUT ----

def test_grade_presets():
    assert grade_preset_by_name("neutral").contrast == 1.0
    assert grade_preset_by_name("bw_cinema").saturation == 0.0
    with pytest.raises(KeyError):
        grade_preset_by_name("nope")


def test_ffmpeg_grade_filter():
    assert build_ffmpeg_grade_filter(grade_preset_by_name("neutral")) == ""
    f = build_ffmpeg_grade_filter(grade_preset_by_name("retro_dv"))
    assert "eq=" in f and "vignette" in f


def test_cube_lut_parse(tmp_path):
    cube = tmp_path / "teal.cube"
    cube.write_text(
        "TITLE teal\nLUT_3D_SIZE 2\n0.0 0.0 0.0\n1.0 0.5 0.5\n0.5 1.0 0.5\n0.5 0.5 1.0\n"
        "0.25 0.25 0.25\n0.75 0.75 0.75\n0.1 0.9 0.1\n0.9 0.1 0.9\n",
        encoding="utf-8",
    )
    lut = parse_cube_lut(cube)
    assert lut.size == 2
    assert lut.valid
    assert len(lut.table) == 8
    # 行数不对 → 抛错
    bad = tmp_path / "bad.cube"
    bad.write_text("LUT_3D_SIZE 2\n0 0 0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_cube_lut(bad)


# ---- skills 安装器 ----

def test_installer_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_SKILLS_DIR", str(tmp_path / "claude"))
    from scripts.install_hevi_skills import SKILL_DIRS, install

    result = install("claude", dry_run=True)
    assert len(result) == len(SKILL_DIRS)
    assert all(created for _, _, created in result)
    # 真实安装 → symlink 存在
    install("claude", dry_run=False)
    for skill, target, _ in install("claude", dry_run=False):
        assert target.is_symlink(), skill

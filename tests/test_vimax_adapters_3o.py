"""ViMax 另外三条适配器的 3O 内化测试。"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from hevi.production.autocameo_workflow import (
    AutoCameoConfig,
    AutoCameoInput,
    autocameo_workflow,
)
from hevi.production.idea2video_workflow import (
    Idea2VideoConfig,
    Idea2VideoInput,
    idea2video_workflow,
)
from hevi.production.novel2video_workflow import (
    Novel2VideoConfig,
    Novel2VideoInput,
    novel2video_workflow,
)
from hevi.script2video.oprim.character_fuse import should_split_identities
from hevi.script2video.oprim.idea_parse import parse_length_budget
from hevi.script2video.oprim.novel_split import (
    extractive_compress_chunk,
    retrieve_chunks,
    split_chunks,
    stitch_overlap,
)
from hevi.script2video.oprim.source_route import classify_source
from hevi.script2video.oskill.autocameo import person_from_photo
from hevi.script2video.oskill.idea_screenwrite import plan_idea_screenplay
from hevi.script2video.oskill.novel_adapt import plan_novel_adaptation


def _png(path: Path) -> Path:
    width, height = 16, 9
    raw = b"".join(b"\x00" + (b"\x11\x22\x33" * width) for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def test_source_route_and_default_idea_budget() -> None:
    assert classify_source("一只猫和一只狗") == "idea"
    assert classify_source("EXT. GYM - DAY\nJohn shoots.") == "script"
    long_novel = "\n".join(f"第{i}段。" + "叙述" * 80 for i in range(20))
    assert len(long_novel) >= 2000
    assert classify_source(long_novel) == "novel"
    assert classify_source("hello", has_photos=True) == "cameo"
    assert classify_source("x", explicit="novel") == "novel"
    budget = parse_length_budget("给小孩看")
    assert budget.max_scenes == 1
    assert budget.max_shots_per_scene == 5
    wide = parse_length_budget("不超过 3 场, 每场不超过 8 镜")
    assert wide.max_scenes == 3
    assert wide.max_shots_per_scene == 8


def test_idea_screenplay_is_small_by_default() -> None:
    story, characters, scenes, budget = plan_idea_screenplay(
        "If a cat and a dog are best friends, what happens when they meet Luna?",
        "For children",
    )
    assert budget.max_scenes == 1
    assert len(scenes) == 1
    assert characters
    assert "Luna" in {c.name for c in characters} or "cat" in story.body.lower()
    assert story.title


@pytest.mark.asyncio
async def test_idea2video_workflow_writes_kernel_per_scene(tmp_path: Path) -> None:
    result = await idea2video_workflow(
        Idea2VideoConfig(style="Cartoon"),
        Idea2VideoInput(idea="A cat and a dog meet a new cat.", requirement="不超过 3 场"),
        tmp_path,
    )
    assert result["status"] == "completed"
    assert result["scene_count"] == 3
    assert Path(result["report_path"]).exists()


def test_novel_compress_retrieve_and_character_split() -> None:
    text = (
        "第一章 相遇\n"
        "小明走进咖啡馆。「你好。」小红抬起头。\n\n"
        "他们聊了很久。窗外下雨。小明决定离开。\n\n"
        "第二章 分手\n"
        "老年小明走在街道上。他不再是青年。小红没有出现。\n"
    )
    compressed = extractive_compress_chunk(text)
    assert "「你好。」" in compressed
    chunks = split_chunks(text * 3, chunk_size=80, overlap=20)
    assert len(chunks) >= 2
    stitched = stitch_overlap(["abcdefoverlap", "overlapXYZ"])
    assert stitched == "abcdefoverlapXYZ"
    hits = retrieve_chunks("咖啡馆 小明", [text], floor=0.1)
    assert hits
    assert should_split_identities("青年 短发", "老年 白发 皱纹 手杖") is True


def test_novel_adaptation_builds_event_scene_book() -> None:
    novel = "\n".join(
        [
            "第一章 咖啡馆",
            "小明走进咖啡馆遇见小红。「好久不见。」",
            "两人坐下点了两杯咖啡。",
            "窗外的雨忽然变大。",
            "第二章 街道",
            "小明冲出咖啡馆跑上街道。",
            "小红在后面追。一把伞被风吹走。",
            "他们在公园门口停下。",
        ]
    )
    compressed, ratio, events, scenes, book = plan_novel_adaptation(novel)
    assert compressed
    assert 0 < ratio <= 1
    assert events and events[-1].is_last
    assert scenes
    assert book
    assert len(events) <= 50


@pytest.mark.asyncio
async def test_novel2video_workflow(tmp_path: Path) -> None:
    novel = "\n".join(f"段落{i}。角色甲做了动作{i}。角色乙回答。" for i in range(6))
    result = await novel2video_workflow(
        Novel2VideoConfig(max_events=4, max_scenes_per_event=2),
        Novel2VideoInput(novel_text=novel),
        tmp_path,
    )
    assert result["status"] == "completed"
    assert result["event_count"] >= 1
    assert Path(result["report_path"]).exists()


@pytest.mark.asyncio
async def test_autocameo_locks_photo_as_front(tmp_path: Path) -> None:
    photo = _png(tmp_path / "my_cat.png")
    info = person_from_photo(photo)
    slug = info.name.lower().replace(" ", "")
    assert slug == "mycat" or "Cat" in info.name
    result = await autocameo_workflow(
        AutoCameoConfig(max_characters=2),
        AutoCameoInput(photos=[str(photo)], story_context="主角是我的宠物"),
        tmp_path,
    )
    assert result["status"] == "completed"
    assert result["character_count"] == 1
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "protagonist" in report
    assert "my_cat.png" in report


@pytest.mark.asyncio
async def test_adapter_workflows_fail_closed(tmp_path: Path) -> None:
    idea = await idea2video_workflow(Idea2VideoConfig(), Idea2VideoInput(idea=""), tmp_path)
    novel = await novel2video_workflow(
        Novel2VideoConfig(), Novel2VideoInput(novel_text=""), tmp_path
    )
    cameo = await autocameo_workflow(AutoCameoConfig(), AutoCameoInput(photos=[]), tmp_path)
    assert idea["status"] == novel["status"] == cameo["status"] == "failed"

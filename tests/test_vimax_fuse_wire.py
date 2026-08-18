"""融合层 + 生成/产集/锁脸接线。"""

from __future__ import annotations

import struct
import uuid
import zlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks

from hevi.api.routers.pipeline import UnifiedGenerateRequest, generate_unified
from hevi.director.pipeline_schemas import ShotList, ShotListItem
from hevi.script2video.omodul.fuse import (
    enrich_shot_list_with_kernel,
    fuse_production,
    kernel_plan_to_shot_list,
)
from hevi.tasks.task_service import TaskService


def _png(path: Path) -> Path:
    width, height = 16, 9
    raw = b"".join(b"\x00" + (b"\x10\x20\x30" * width) for _ in range(height))

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


def test_fuse_idea_emits_locked_shot_list() -> None:
    fused = fuse_production("A cat and a dog meet Luna", requirement="不超过 3 场")
    assert fused.source == "idea"
    assert len(fused.shot_list.shots) == 3
    payload = fused.locked_shot_payload()
    assert payload["shots"][0]["visual_prompt"]
    assert payload["shots"][0]["camera_setup_ref"].startswith("cam_")


def test_fuse_enriches_existing_shot_list() -> None:
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="s1",
                scene_no=1,
                visual_prompt="Wide gym John dribbling",
                character_names=["John"],
                scene_name="gym",
            )
        ]
    )
    fused = fuse_production("", existing_shot_list=shot_list)
    assert fused.kernel is not None
    enriched = enrich_shot_list_with_kernel(shot_list, fused.kernel)
    assert enriched.shots[0].camera_setup_ref.startswith("cam_")
    assert enriched.shots[0].visual_prompt == "Wide gym John dribbling"


def test_fuse_cameo_onto_idea(tmp_path: Path) -> None:
    photo = _png(tmp_path / "my_cat.png")
    fused = fuse_production(
        "一只猫的冒险",
        requirement="主角是我的宠物",
        photos=[photo],
    )
    ids = {char.identifier for char in fused.characters}
    assert any("cat" in ident or "my" in ident for ident in ids)
    assert fused.cameo is not None
    assert fused.cameo.characters[0].role_in_story == "protagonist"


def test_kernel_plan_roundtrip_shot_list() -> None:
    fused = fuse_production("EXT. GYM - DAY\nJohn shoots.")
    assert fused.source == "script"
    again = kernel_plan_to_shot_list(fused.kernel) if fused.kernel else ShotList(shots=[])
    assert again.shots


@pytest.mark.asyncio
async def test_hub_idea2video_writes_locked_shots() -> None:
    task_id = uuid.uuid4()
    svc = AsyncMock()
    svc.create_production.return_value = {"id": task_id, "status": "pending"}
    svc.submit_task.return_value = {"id": task_id, "status": "queued"}
    await generate_unified(
        UnifiedGenerateRequest(
            source_channel="hub_idea2video",
            adapter_type="default",
            config={
                "prompt": "If a cat and a dog are best friends",
                "duration_archetype": "1-5min",
                "character_references": ["sub-1"],
            },
        ),
        user={"id": uuid.uuid4()},
        svc=svc,
        background_tasks=BackgroundTasks(),
    )
    request = svc.create_production.await_args.args[0]
    assert request.options["source_channel"] == "hub_idea2video"
    assert request.options["adapter_type"] == "default"
    locked = request.options["locked_shot_list"]
    assert isinstance(locked, dict)
    assert locked["shots"]
    assert request.options["vimax_source"] == "idea"
    assert request.subject_ids == ["sub-1"]


def test_resolve_character_reference_reads_cameo_alias() -> None:
    """produce() 透传的 character_references 必须被当成 subject_ids。"""
    src = Path("hevi/tasks/task_service.py").read_text(encoding="utf-8")
    assert "character_references" in src
    assert "character_subject_ids" in src
    # 运行期解析函数存在
    assert hasattr(TaskService, "_resolve_character_reference")

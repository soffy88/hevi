"""配方履约 / 镜头砖 / 过检叠人 / NLE / 矩阵包装。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.production.studio_combine_workflow import (
    StudioCombineConfig,
    StudioCombineInput,
    studio_combine_workflow,
)
from hevi.studio.brick import brick_from_payload, import_brick
from hevi.studio.compose_gate import apply_compose_after_qc, qc_allows_compose, should_defer_avatar
from hevi.studio.fulfill import fulfill_order
from hevi.studio.nle import ffmpeg_recut_args, plan_recut
from hevi.studio.packaging import pack_queue
from hevi.studio.slate import Slate, run_slate
from hevi.studio.timeline import export_timeline, split_at, timeline_from_film
from hevi.studio.tools import invoke_tool
from hevi.studio.veya import produce


@pytest.mark.asyncio
async def test_fulfill_drives_explainer_not_just_ticket(tmp_path: Path) -> None:
    issued = await fulfill_order({"target": "explainer", "topic": "盐税"}, execute=False)
    assert issued["status"] == "issued"
    done = await fulfill_order(
        {"target": "explainer", "topic": "盐税", "script_lines": ["钩子", "展开"]},
        execute=True,
        output_dir=tmp_path,
    )
    assert done["status"] == "dispatched"
    assert done["cue_count"] == 2
    assert Path(done["dispatch_path"]).is_file()
    assert "assemble" in done["next"]


@pytest.mark.asyncio
async def test_slate_execute_requires_real_explainer_artifact() -> None:
    result = await run_slate(Slate(line_id="explainer", slots={"topic": "盐税"}, execute=True))
    assert result.status in {"blocked", "failed"}
    assert result.data["fulfill"]["status"] in {"blocked", "failed"}
    planned = await run_slate(Slate(line_id="explainer", slots={"topic": "盐税"}))
    assert planned.status == "scheduled"


@pytest.mark.asyncio
async def test_veya_execute_fulfills(tmp_path: Path) -> None:
    job = await produce(
        line_id="explainer",
        slots={"topic": "盐税"},
        execute=True,
        output_dir=tmp_path,
    )
    assert job.status in {"blocked", "failed"}
    assert job.fulfill.get("status") in {"blocked", "failed"}


def test_shot_brick_exports_and_imports() -> None:
    brick = brick_from_payload(
        {
            "shot_id": "s3",
            "visual_prompt": "韩康子推开木门",
            "camera": "side-45",
            "duration_s": 4.0,
            "subject_ids": ["sub-han"],
            "reference_paths": ["/refs/han.png"],
            "clip_path": "/clips/s3.mp4",
            "character_names": ["韩康子"],
            "scene_no": 2,
            "audio_desc": "门轴吱呀。",
        }
    )
    expl = import_brick(brick, "explainer")
    assert expl["cue"]["clip_path"] == "/clips/s3.mp4"
    assert expl["cue"]["subject_ids"] == ["sub-han"]
    hist = import_brick(brick, "history_scene")
    assert hist["shot"]["visual_desc"] == "韩康子推开木门"
    director = import_brick(brick, "director_pipeline")
    assert director["shot"]["character_subject_ids"] == ["sub-han"]


@pytest.mark.asyncio
async def test_shot_export_tool_writes_brick(tmp_path: Path) -> None:
    dest = tmp_path / "s1.brick.json"
    result = await invoke_tool(
        "shot.export",
        {
            "shot_id": "s1",
            "prompt": "空镜城门",
            "dest": str(dest),
            "import_line": "explainer",
        },
    )
    assert result.status == "ok"
    assert dest.is_file()
    assert result.payload["imported"]["target"] == "explainer"


def test_compose_gate_requires_qc() -> None:
    assert not qc_allows_compose({})
    assert qc_allows_compose({"passed": True})
    assert should_defer_avatar(compose_after_qc=True, has_presenter=True)
    assert not should_defer_avatar(preview=True, compose_after_qc=True, has_presenter=True)


@pytest.mark.asyncio
async def test_compose_after_qc_skips_without_qc() -> None:
    out = await apply_compose_after_qc(
        base_video="a.mp4",
        image_path="p.png",
        audio_path="a.wav",
        output_path="o.mp4",
        qc_report={"passed": False},
    )
    assert out["status"] == "skipped"


def test_nle_plan_trims_and_drops_bgm_label() -> None:
    plan = plan_recut(
        [
            {
                "track": "video",
                "action": "keep",
                "source": "film.mp4",
                "source_in_s": 1.5,
                "duration_s": 2.0,
            },
            {
                "track": "video",
                "action": "drop",
                "source": "film.mp4",
                "source_in_s": 3.5,
                "duration_s": 2.0,
            },
        ],
        bgm="warm",
        output="out.mp4",
    )
    assert len(plan.segments) == 1
    assert plan.segments[0].in_s == 1.5
    assert plan.bgm == ""
    args = ffmpeg_recut_args(plan)
    assert "-ss" in args and "1.500" in args
    assert "amix" not in " ".join(args)


def test_import_film_split_export(tmp_path: Path) -> None:
    film = tmp_path / "done.mp4"
    film.write_bytes(b"x")
    tl = timeline_from_film(film, duration_s=8.0, title="成片")
    split_at(tl.timeline_id, 3.0)
    video = [c for c in tl.clips if c.track == "video"]
    assert len(video) == 2
    assert video[1].source_in_s == pytest.approx(3.0)
    out = export_timeline(tl.timeline_id, tmp_path / "recut.mp4")
    assert out["kept"] == 2
    assert "plan" in out


def test_pack_queue_platforms_and_accounts() -> None:
    queue = pack_queue(
        "盐税如何发军饷",
        ["douyin", "xiaohongshu"],
        accounts={"douyin": ["main", "alt"], "xiaohongshu": ["note"]},
        media_path="out.mp4",
    )
    assert queue.to_dict()["count"] == 3
    titles = {item.platform: item.title for item in queue.variants}
    assert "盐税" in titles["douyin"]
    assert len(titles["xiaohongshu"]) <= 24


@pytest.mark.asyncio
async def test_combine_workflow_five_kernels(tmp_path: Path) -> None:
    film = tmp_path / "base.mp4"
    film.write_bytes(b"x")
    result = await studio_combine_workflow(
        StudioCombineConfig(execute=True, platforms=["douyin", "bilibili"]),
        StudioCombineInput(
            order={"target": "explainer", "topic": "盐税"},
            shot={"shot_id": "s1", "visual_prompt": "城门", "clip_path": str(film)},
            import_line="history_scene",
            timeline_clips=[
                {
                    "track": "video",
                    "action": "keep",
                    "source": str(film),
                    "source_in_s": 0,
                    "duration_s": 2,
                }
            ],
            film=str(film),
            topic="盐税如何发军饷",
            accounts={"douyin": ["main"]},
            qc_report={"passed": False},
        ),
        tmp_path / "out",
    )
    assert result["status"] == "completed"
    assert result["fulfill"]["status"] == "dispatched"
    assert Path(result["report_path"]).is_file()
    assert (tmp_path / "out" / "pack").is_dir()

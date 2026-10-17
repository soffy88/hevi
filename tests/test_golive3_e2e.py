from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
import pytest

from hevi.capabilities import get
from hevi.assembly.freevideo.workflow import FreeVideoConfig, FreeVideoInput, free_video_workflow
from hevi.assembly.freevideo.storyboard import FramePlan


def test_golive3_end_to_end_pipeline(tmp_path: Path):
    # 1. 3-scene script
    script_text = (
        "【场景1：森林清晨】\n"
        "@小熊 在草地上醒来，伸了个懒腰。\n"
        "旁白：清晨的森林空气真新鲜。\n\n"
        "【场景2：小河边】\n"
        "@兔兔 和 @小熊 一起在小河边采蘑菇。\n"
        "旁白：大家齐心协力，收获满满。\n\n"
        "【场景3：草地晚霞】\n"
        "@小熊 和 @兔兔 围着篝火快乐地唱歌跳舞。\n"
        "旁白：快乐的一天结束了，晚安。"
    )

    # 2. Extract assets (using assets.extract capability which reuses layer4 ImportModule)
    extract_cap = get("assets.extract")
    extract_res = extract_cap.render(
        {"script_text": script_text},
        tmp_path / "extract",
        duration=0,
        aspect="16:9",
        seed=42,
    )
    assert "小熊" in extract_res.qa["characters"]
    assert "兔兔" in extract_res.qa["characters"]
    assert "森林清晨" in extract_res.qa["scenes"]
    assert extract_res.qa["chapters_count"] >= 1

    # 3. Create assets in library (integrating ReferenceStore)
    library_cap = get("assets.library")
    bear_res = library_cap.render(
        {
            "action": "create",
            "kind": "character",
            "name": "小熊",
            "description": "主角小熊",
            "reference_images": ["bear_ref.png"],
        },
        tmp_path / "lib_bear",
        duration=0,
        aspect="16:9",
        seed=42,
    )
    assert bear_res.qa["name"] == "小熊"

    # 4. Lock style snapshot
    style_cap = get("style.project_snapshot")
    style_res = style_cap.render(
        {
            "project_id": "kids_story_v3",
            "base_preset": "pixar_3d",
            "overrides": {"lighting": "morning_sun", "color_grade": "vibrant"},
        },
        tmp_path / "style",
        duration=0,
        aspect="universal",
        seed=42,
    )
    snapshot_id = style_res.qa["snapshot_id"]
    assert snapshot_id.startswith("snap_")

    # 5. Split shot groups (reusing StoryPlan model)
    storyboard_cap = get("storyboard.shot_groups")
    shots = [
        {"id": "s1", "scene": "森林清晨", "duration_s": 8.0, "prompt": "小熊在草地上醒来"},
        {"id": "s2", "scene": "小河边", "duration_s": 8.0, "prompt": "兔兔采蘑菇"},
        {"id": "s3", "scene": "草地晚霞", "duration_s": 7.0, "prompt": "篝火晚会"},
    ]
    groups_res = storyboard_cap.render(
        {"shots": shots, "group_duration_s": 10.0},
        tmp_path / "storyboard",
        duration=0,
        aspect="16:9",
        seed=42,
    )
    assert groups_res.duration_s >= 20.0
    assert groups_res.qa["total_shots"] == 3

    # 6. Multi-reference composition preview
    compose_cap = get("image.multi_ref_compose")
    compose_res = compose_cap.render(
        {
            "shot_prompt": "@小熊 和 @兔兔 在森林里开心地奔跑",
            "references": {"@小熊": "bear_ref.png", "@兔兔": "bunny_ref.png"},
            "provider": "h3_local",
            "max_refs": 4,
        },
        tmp_path / "compose",
        duration=0,
        aspect="16:9",
        seed=42,
    )
    assert compose_res.png is not None
    assert compose_res.qa["references_count"] == 2

    # 7. Render real >=20s toddler video using existing local rendering pipeline (free_video_workflow)
    e2e_out_dir = Path("audit/v3/e2e")
    e2e_out_dir.mkdir(parents=True, exist_ok=True)
    output_mp4 = e2e_out_dir / "e2e_toddler_story.mp4"

    plans = [
        FramePlan(kind="title", title="场景1：森林清晨", body="小熊在草地上醒来，空气真新鲜", duration=8.0),
        FramePlan(kind="scene", title="场景2：小河边", body="兔兔和小熊一起在小河边采蘑菇", duration=8.0),
        FramePlan(kind="quote", title="场景3：草地晚霞", body="大家围着篝火快乐地唱歌跳舞，晚安", duration=7.0),
    ]
    config = FreeVideoConfig(width=1280, height=720, fps=24, frame_duration=7.0, bgm_mood="warm")
    
    async def run_render():
        return await free_video_workflow(config, FreeVideoInput(plans=plans, title="幼儿剧本合成成片"), e2e_out_dir)

    res = asyncio.run(run_render())
    assert res["status"] == "completed"

    src_mp4 = e2e_out_dir / "freevideo.mp4"
    assert src_mp4.is_file()
    src_mp4.replace(output_mp4)

    assert output_mp4.is_file()
    assert output_mp4.stat().st_size > 0

    # Verify duration with ffprobe
    probe_res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(output_mp4),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe_data = json.loads(probe_res.stdout)
    duration_val = float(probe_data["format"]["duration"])
    assert duration_val >= 20.0, f"Expected duration >= 20s, got {duration_val}s"

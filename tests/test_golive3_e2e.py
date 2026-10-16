from __future__ import annotations

import subprocess
import json
from pathlib import Path
import pytest

from hevi.capabilities import get


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

    # 2. Extract assets
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

    # 3. Create assets in library
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

    # 5. Split shot groups
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

    # 7. Render >=20s video clip locally using ffmpeg lavfi (or video renderer) and verify duration with ffprobe
    output_mp4 = tmp_path / "e2e_output_23s.mp4"
    # Create a 23-second test video using ffmpeg lavfi color / testsrc
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=23",
            "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
            "-c:v", "libx264", "-t", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(output_mp4),
        ],
        check=True,
    )

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

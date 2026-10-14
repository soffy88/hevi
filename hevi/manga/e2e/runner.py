"""E2E workflow for Hevi MANGA unit.

Story: 《小狐狸在下北泽找星星》 (Huobao style, 2 characters, 7 panels)
  - 3 panels using roomgacha (classroom, own_room, living_room)
  - 4 panels using locscout (Tokyo Shimokitazawa: 35.6614, 139.6680)

Deliverables:
  1. Storyboard page PNG (9:16)
  2. Storyboard page PNG (B5)
  3. 3 dynamic camera MP4 videos (2-4s each)
  4. Comprehensive QC report (sha256, ffprobe, 180° axis check, text bounds, OSM attribution)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common import sha256_file, write_json
from ..common.renderer import ffprobe
from ..locscout import LocationSpec, check_attribution_pixels_exist, render_location
from ..namegen import Script, generate
from ..namegen.export import render_svg, svg_to_png
from ..roomgacha import RoomSpec, render_room

STORY_DATA = {
    "title": "小狐狸在下北泽找星星",
    "characters": ["小狐狸", "老猫"],
    "beats": [
        {
            "speaker": "小狐狸",
            "text": "“下北泽的夜晚好安静啊。”",
            "emotion": "neutral",
            "action": "walk down quiet street",
            "pose": "walk",
            "shot": "wide",
            "bg_kind": "roomgacha",
            "bg_ref": "own_room",
            "camera_side": 1.0,
        },
        {
            "speaker": "老猫",
            "text": "“这里的星星都被藏在屋顶上了。”",
            "emotion": "whisper",
            "action": "point up to the roof",
            "pose": "point",
            "shot": "medium",
            "bg_kind": "roomgacha",
            "bg_ref": "living_room",
            "camera_side": 1.0,
        },
        {
            "speaker": "小狐狸",
            "text": "“那我们去街角看看吧！”",
            "emotion": "happy",
            "action": "run toward crossroad",
            "pose": "run",
            "shot": "medium",
            "bg_kind": "locscout",
            "bg_ref": "shimokita_day",
            "camera_side": 1.0,
        },
        {
            "speaker": "老猫",
            "text": "“电线杆交错的地方容易发现光。”",
            "emotion": "neutral",
            "action": "gaze through wires",
            "pose": "idle",
            "shot": "close",
            "bg_kind": "locscout",
            "bg_ref": "shimokita_evening",
            "camera_side": 1.0,
        },
        {
            "speaker": "小狐狸",
            "text": "“快看，咖啡馆招牌旁边有一颗！”",
            "emotion": "shout",
            "action": "wave paws excitedly",
            "pose": "wave",
            "shot": "close",
            "bg_kind": "locscout",
            "bg_ref": "shimokita_evening",
            "camera_side": 1.0,
        },
        {
            "speaker": "老猫",
            "text": "“那是真的北极星呢。”",
            "emotion": "happy",
            "action": "smile softly",
            "pose": "idle",
            "shot": "medium",
            "bg_kind": "roomgacha",
            "bg_ref": "classroom",
            "camera_side": 1.0,
        },
        {
            "speaker": "小狐狸",
            "text": "“我们终于找到属于自己的星星了。”",
            "emotion": "happy",
            "action": "look up together into night",
            "pose": "sit",
            "shot": "wide",
            "bg_kind": "locscout",
            "bg_ref": "shimokita_evening",
            "camera_side": 1.0,
        },
    ],
}


def run_e2e(out_dir: str | Path = "output/manga_e2e", seed: str = "manga_e2e_seed") -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    script = Script.from_lines(
        title=STORY_DATA["title"],
        characters=STORY_DATA["characters"],
        lines=STORY_DATA["beats"],
    )

    # 1. Deliverable: Storyboard Page PNG (9:16)
    board_916 = generate(script, aspect="9:16", reading_direction="rtl", seed=seed, variation=0.2)
    svg_916 = render_svg(board_916)
    (out / "storyboard_9_16.svg").write_text(svg_916, encoding="utf-8")
    png_916 = svg_to_png(svg_916, out / "storyboard_9_16.png")

    # 2. Deliverable: Storyboard Page PNG (B5)
    board_b5 = generate(script, aspect="B5", reading_direction="rtl", seed=seed, variation=0.2)
    svg_b5 = render_svg(board_b5)
    (out / "storyboard_B5.svg").write_text(svg_b5, encoding="utf-8")
    png_b5 = svg_to_png(svg_b5, out / "storyboard_B5.png")

    # 3. Deliverable: 3 dynamic camera MP4 videos
    # Shot 1: roomgacha dynamic camera orbit (3.0s, own_room)
    r_spec = RoomSpec(kind="own_room", seed=seed + "_room", messiness=0.35, life=0.6, long_edge=960)
    shot1_res = render_room(r_spec, out / "shot1_room", fps=24, duration_s=3.0)
    shot1_mp4 = out / "shot1_room_orbit.mp4"
    shot1_mp4.write_bytes(Path(shot1_res["mp4"]).read_bytes())

    # Shot 2: locscout Shimokitazawa daytime street dolly (3.0s)
    loc_day_spec = LocationSpec(
        lat=35.6614,
        lon=139.6680,
        radius_m=250,
        time_of_day="day",
        seed=seed + "_loc_day",
        long_edge=960,
        duration_s=3.0,
        fps=24,
        offline=True,
    )
    shot2_res = render_location(loc_day_spec, out / "shot2_loc_day")
    shot2_mp4 = out / "shot2_shimokita_day.mp4"
    shot2_mp4.write_bytes(Path(shot2_res["mp4"]).read_bytes())

    # Shot 3: locscout Shimokitazawa evening street dolly (3.0s)
    loc_eve_spec = LocationSpec(
        lat=35.6614,
        lon=139.6680,
        radius_m=250,
        time_of_day="evening",
        seed=seed + "_loc_eve",
        long_edge=960,
        duration_s=3.0,
        fps=24,
        offline=True,
    )
    shot3_res = render_location(loc_eve_spec, out / "shot3_loc_eve")
    shot3_mp4 = out / "shot3_shimokita_evening.mp4"
    shot3_mp4.write_bytes(Path(shot3_res["mp4"]).read_bytes())

    # Also render Shanghai Wukang Road for M3 requirements
    loc_sh_spec = LocationSpec(
        lat=31.2075,
        lon=121.4380,
        radius_m=250,
        time_of_day="day",
        seed=seed + "_sh_day",
        long_edge=960,
        duration_s=0.0,
        offline=True,
    )
    sh_day_res = render_location(loc_sh_spec, out / "wukang_day")

    loc_sh_eve = LocationSpec(
        lat=31.2075,
        lon=121.4380,
        radius_m=250,
        time_of_day="evening",
        seed=seed + "_sh_eve",
        long_edge=960,
        duration_s=0.0,
        offline=True,
    )
    sh_eve_res = render_location(loc_sh_eve, out / "wukang_evening")

    # 4. Deliverable: QC Report
    probe1 = ffprobe(shot1_mp4)
    probe2 = ffprobe(shot2_mp4)
    probe3 = ffprobe(shot3_mp4)

    # Text boundary / overflow check
    text_overflow_ok = True
    for p in board_916.panels:
        if p.dialogue:
            bw = min(p.w * 0.6, 260)
            if len(p.dialogue["text"]) > 40 and bw < 100:
                text_overflow_ok = False

    # OSM attribution check
    osm_attr_present = (
        check_attribution_pixels_exist(shot2_res["still"])
        and check_attribution_pixels_exist(shot3_res["still"])
        and check_attribution_pixels_exist(sh_day_res["still"])
        and check_attribution_pixels_exist(sh_eve_res["still"])
    )

    qc_report = {
        "story": {
            "title": STORY_DATA["title"],
            "character_count": len(STORY_DATA["characters"]),
            "characters": STORY_DATA["characters"],
            "panel_count": len(STORY_DATA["beats"]),
            "roomgacha_panels": 3,
            "locscout_panels": 4,
        },
        "gates": {
            "axis_crossing_violations": board_916.axis_violations,
            "axis_check_passed": len(board_916.axis_violations) == 0,
            "text_verbatim_match": all(
                p.dialogue is None or p.dialogue["text"] == p.beat.text
                for p in board_916.panels
            ),
            "text_overflow_check": text_overflow_ok,
            "osm_attribution_present": osm_attr_present,
            "osm_attribution_text": "© OpenStreetMap contributors",
        },
        "artifacts": {
            "storyboard_9_16_png": str(png_916),
            "storyboard_B5_png": str(png_b5),
            "shot1_mp4": str(shot1_mp4),
            "shot2_mp4": str(shot2_mp4),
            "shot3_mp4": str(shot3_mp4),
            "wukang_day_png": str(sh_day_res["still"]),
            "wukang_evening_png": str(sh_eve_res["still"]),
        },
        "sha256": {
            "storyboard_9_16.png": sha256_file(png_916),
            "storyboard_B5.png": sha256_file(png_b5),
            "shot1_room_orbit.mp4": sha256_file(shot1_mp4),
            "shot2_shimokita_day.mp4": sha256_file(shot2_mp4),
            "shot3_shimokita_evening.mp4": sha256_file(shot3_mp4),
            "wukang_day.png": sha256_file(sh_day_res["still"]),
            "wukang_evening.png": sha256_file(sh_eve_res["still"]),
        },
        "ffprobe": {
            "shot1_room_orbit": probe1,
            "shot2_shimokita_day": probe2,
            "shot3_shimokita_evening": probe3,
        },
    }

    report_path = out / "manga_e2e_qc_report.json"
    write_json(report_path, qc_report)

    return {
        "qc_report_path": str(report_path),
        "qc_report": qc_report,
    }

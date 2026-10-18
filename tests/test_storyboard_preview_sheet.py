"""Unit tests for storyboard.preview_sheet capability (漫画格分镜表生成)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hevi.capabilities import get, names, resolve
from hevi.capabilities.errors import CapabilityError
from hevi.storyplan.autofill import autofill_story_plan


def test_storyboard_preview_sheet_registered():
    assert "storyboard.preview_sheet" in names()
    cap = get("storyboard.preview_sheet")
    assert cap.name == "storyboard.preview_sheet"
    assert "16:9" in cap.aspects
    assert "9:16" in cap.aspects


def test_render_preview_sheet_from_shot_groups(tmp_path: Path):
    cap = resolve("storyboard.preview_sheet")
    out_dir = tmp_path / "sheet_groups"

    mock_groups = [
        {
            "group_id": "group_1",
            "shots": [
                {
                    "id": "shot_1",
                    "scale": "远景",
                    "prompt": "微光穿透森林树冠，小狐狸在晨雾中好奇四顾",
                    "dialogue": "清晨的森林里，泛着一层金色的光芒...",
                    "duration_s": 5.0,
                },
                {
                    "id": "shot_2",
                    "scale": "中景",
                    "prompt": "小狐狸蹲下身子，伸出小爪子触碰草叶上的微光种子",
                    "dialogue": "咦，草叶尖上躺着一颗好小好小的发光种子！",
                    "duration_s": 4.5,
                },
            ],
        },
        {
            "group_id": "group_2",
            "shots": [
                {
                    "id": "shot_3",
                    "scale": "特写",
                    "prompt": "种子表面泛起清澈的蓝色水光，露珠倒映着星光",
                    "dialogue": "小种子像一颗眨眼睛的微小星星。",
                    "duration_s": 4.0,
                }
            ],
        },
    ]

    result = cap.render(
        {"title": "森林奇妙种子", "shot_groups": mock_groups},
        out_dir,
        aspect="16:9",
        seed=101,
    )

    assert result.png is not None
    png_path = Path(result.png)
    assert png_path.is_file()

    # 验证图像尺寸为 16:9 (1920x1080)
    with Image.open(png_path) as im:
        assert im.size == (1920, 1080)

    # 验证元数据
    meta_path = out_dir / "preview_sheet_meta.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["total_shots"] == 3
    assert meta["title"] == "森林奇妙种子"
    assert meta["aspect"] == "16:9"

    # 验证景别包含远景、中景、特写
    scales = [s["scale"] for s in meta["shots"]]
    assert "远景" in scales
    assert "中景" in scales
    assert "特写" in scales


def test_render_preview_sheet_portrait_9_16(tmp_path: Path):
    cap = get("storyboard.preview_sheet")
    out_dir = tmp_path / "sheet_portrait"

    shots = [
        {"id": "S01", "shot_type": "establishing", "description": "远山晨雾", "dialogue": "大山醒来了", "duration_s": 3.0},
        {"id": "S02", "shot_type": "character", "description": "小熊伸懒腰", "dialogue": "呼啊，早安！", "duration_s": 3.5},
        {"id": "S03", "shot_type": "insert", "description": "蜂蜜罐特写", "dialogue": "甜甜的蜂蜜真香", "duration_s": 2.5},
        {"id": "S04", "shot_type": "character", "description": "小熊大步奔跑", "dialogue": "去找小伙伴玩喽", "duration_s": 4.0},
    ]

    result = cap.render(
        {"title": "小熊的清晨", "shots": shots, "aspect": "9:16"},
        out_dir,
        aspect="9:16",
        seed=202,
    )

    png_path = Path(result.png)
    assert png_path.is_file()
    with Image.open(png_path) as im:
        assert im.size == (1080, 1920)

    meta = json.loads((out_dir / "preview_sheet_meta.json").read_text(encoding="utf-8"))
    assert meta["columns"] == 2
    assert meta["total_shots"] == 4


def test_render_preview_sheet_from_storyplan(tmp_path: Path):
    cap = get("storyboard.preview_sheet")
    out_dir = tmp_path / "sheet_plan"

    plan = autofill_story_plan("小松鼠种向日葵", aspect="16:9")
    result = cap.render(
        {"plan": plan.model_dump()},
        out_dir,
        aspect="16:9",
        seed=303,
    )

    assert result.png is not None
    assert Path(result.png).is_file()
    assert (out_dir / "preview_sheet_meta.json").is_file()


def test_preview_sheet_invalid_params():
    cap = get("storyboard.preview_sheet")
    with pytest.raises(CapabilityError):
        cap.validate_params({"unsupported_arg": True})

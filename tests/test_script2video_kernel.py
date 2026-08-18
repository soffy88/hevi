"""Script2Video 内核 3O 内化:五原语 / 五技能 / 三件套 workflow / ShotList 桥。"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from hevi.director.kernel_bridge import kernel_shot_payload, plan_kernel_from_shot_list
from hevi.director.pipeline_schemas import ShotBlocking, ShotList, ShotListItem
from hevi.production.script2video_kernel_workflow import (
    Script2VideoKernelConfig,
    Script2VideoKernelInput,
    script2video_kernel_workflow,
)
from hevi.script2video.omodul.kernel_plan import plan_kernel_artifacts
from hevi.script2video.oprim.camera_graph import generation_order, validate_camera_tree
from hevi.script2video.oprim.image_score import score_image_basic, score_image_dimensions
from hevi.script2video.oprim.portrait_prompt import build_portrait_prompt
from hevi.script2video.oprim.reference_pick import pick_portrait_view, select_pairs_by_indices
from hevi.script2video.oprim.transition_prompt import build_transition_prompt
from hevi.script2video.oprim.variation import classify_variation, needs_last_frame
from hevi.script2video.oskill.portrait_triptych import generate_portrait_triptych
from hevi.script2video.oskill.reference_select import select_reference_images_and_prompt
from hevi.script2video.oskill.shot_decompose import decompose_shot_visual
from hevi.script2video.oskill.transition_video import generate_transition_video
from hevi.script2video.schemas import (
    CameraNode,
    CameraTree,
    CharacterPortrait,
    KernelShot,
    PortraitRegistry,
    PortraitView,
    TransitionSpec,
)


def _png_bytes(width: int = 32, height: int = 18) -> bytes:
    raw = b"".join(b"\x00" + (b"\x00\x80\xff" * width) for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _write_png(path: Path, width: int = 32, height: int = 18) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(width, height))
    return path


def test_three_o_directory_structure_exists() -> None:
    root = Path(__file__).parents[1] / "hevi" / "script2video"
    for sub in ("oprim", "oskill", "omodul"):
        assert (root / sub).is_dir(), f"缺少 3O 目录: {sub}"
    assert (root / "schemas.py").is_file()


def test_oprim_does_not_import_oskill_or_omodul() -> None:
    root = Path(__file__).parents[1] / "hevi" / "script2video" / "oprim"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import", "from")) and (
                "script2video.oskill" in stripped or "script2video.omodul" in stripped
            ):
                raise AssertionError(f"{path.name} 越权引用: {stripped}")


def test_oskill_does_not_import_omodul() -> None:
    root = Path(__file__).parents[1] / "hevi" / "script2video" / "oskill"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import", "from")) and "script2video.omodul" in stripped:
                raise AssertionError(f"{path.name} 越权引用: {stripped}")


def test_portrait_prompt_covers_three_views() -> None:
    front = build_portrait_prompt("front", identifier="Alice", features="short hair", style="anime")
    side = build_portrait_prompt("side", identifier="Alice", features="short hair", style="anime")
    back = build_portrait_prompt("back", identifier="Alice", features="short hair", style="anime")
    assert "16:9" in front and "front-view" in front
    assert "side-view" in side and "Alice" in side
    assert "back-view" in back and "No facial features" in back
    with pytest.raises(ValueError):
        build_portrait_prompt("left", identifier="A", features="", style="")  # type: ignore[arg-type]


def test_variation_markers_and_last_frame_gate() -> None:
    assert classify_variation("航拍穿越城市")[0] == "large"
    assert classify_variation("她转身面对镜头")[0] == "medium"
    assert classify_variation("Alice 微笑点头")[0] == "small"
    assert needs_last_frame("medium") is True
    assert needs_last_frame("small") is False


def test_camera_tree_parent_before_child_and_missing_chars() -> None:
    plan = plan_kernel_artifacts(
        [
            {
                "idx": 0,
                "visual_desc": "Wide supermarket aisle, Alice and Bob in profile",
                "cam_key": "master",
                "environment": "supermarket",
                "visible_chars": ["Alice", "Bob"],
            },
            {
                "idx": 1,
                "visual_desc": "Close-up of Alice facing camera",
                "cam_key": "alice_cu",
                "environment": "supermarket",
                "visible_chars": ["Alice"],
            },
            {
                "idx": 2,
                "visual_desc": "Close-up of Carol entering",
                "cam_key": "carol_cu",
                "environment": "supermarket",
                "visible_chars": ["Carol"],
            },
        ]
    )
    order = generation_order(plan.camera_tree)
    assert order[0] == 0
    assert set(order) == {0, 1, 2}
    carol = next(node for node in plan.camera_tree.all_cameras if 2 in node.shot_idxs)
    assert carol.missing_info is not None and "Carol" in carol.missing_info
    assert carol.is_parent_fully_covers_child is False
    alice = next(node for node in plan.camera_tree.all_cameras if 1 in node.shot_idxs)
    assert alice.is_parent_fully_covers_child is True
    assert plan.visual_plans[0].variation_type == "small"


def test_camera_tree_rejects_cycle() -> None:
    tree = CameraTree()
    tree.add(CameraNode(cam_idx=0, shot_idxs=[0], parent_cam_idx=1, parent_shot_idx=1))
    tree.add(CameraNode(cam_idx=1, shot_idxs=[1], parent_cam_idx=0, parent_shot_idx=0))
    problems = validate_camera_tree(tree)
    assert any("cycle" in item for item in problems)


def test_reference_pick_facing_and_index_guard() -> None:
    assert pick_portrait_view(facing_text="背对镜头") == "back"
    assert pick_portrait_view(cam_azimuth_deg=0, char_facing_deg=0) == "front"
    assert pick_portrait_view(cam_azimuth_deg=90, char_facing_deg=0) == "side"
    pairs = [("a.png", "A"), ("b.png", "B")]
    assert select_pairs_by_indices(pairs, [1]) == [("b.png", "B")]
    with pytest.raises(ValueError):
        select_pairs_by_indices(pairs, [-1])
    with pytest.raises(ValueError):
        select_pairs_by_indices(pairs, [2])


def test_reference_select_uses_matching_portrait_view(tmp_path: Path) -> None:
    front = _write_png(tmp_path / "front.png")
    side = _write_png(tmp_path / "side.png")
    back = _write_png(tmp_path / "back.png")
    registry = PortraitRegistry()
    registry.register(
        CharacterPortrait(
            name="Alice",
            identifier="Alice",
            physical_description="short hair",
            front=PortraitView("front", front, "front Alice"),
            side=PortraitView("side", side, "side Alice"),
            back=PortraitView("back", back, "back Alice"),
        )
    )
    selected = select_reference_images_and_prompt(
        frame_description="OTS behind Alice",
        portraits=registry,
        visible_characters=["Alice"],
        facing_hints={"Alice": "背对"},
        transition_anchor=(str(tmp_path / "anchor.png"), "parent composition"),
        missing_info="frontal view of Alice",
    )
    assert any("back Alice" in pair[1] for pair in selected.pairs)
    assert "frontal view of Alice" in selected.text_prompt
    assert len(selected.pairs) <= 8


def test_image_score_reads_png_header(tmp_path: Path) -> None:
    path = _write_png(tmp_path / "wide.png", width=32, height=18)
    assert score_image_basic(path) == 1.0
    assert score_image_dimensions(path) > 0.5


def test_decompose_uses_action_beats() -> None:
    shot = KernelShot(
        idx=0,
        visual_desc="Medium shot of Alice at the table",
        action_beats=["reaches for the cup", "drinks", "sets the cup down"],
        visible_chars=["Alice"],
    )
    plan = decompose_shot_visual(shot)
    assert "reaches for the cup" in plan.ff_desc
    assert "sets the cup down" in plan.lf_desc
    assert "drinks" in plan.motion_desc


@pytest.mark.asyncio
async def test_portrait_triptych_cameo_and_side_fallback(tmp_path: Path) -> None:
    photo = _write_png(tmp_path / "me.png")

    async def failing_gen(**kwargs: object) -> Path:
        raise RuntimeError("provider down")

    portrait = await generate_portrait_triptych(
        character_name="Me",
        identifier="me",
        description="black hair",
        output_dir=tmp_path / "portraits",
        image_gen=failing_gen,
        reference_photo=photo,
    )
    assert portrait.front is not None and portrait.front.path.exists()
    assert portrait.side is not None and portrait.side.path.exists()
    assert "fallback" in (portrait.side.generation_prompt or "")


@pytest.mark.asyncio
async def test_transition_prompt_and_video_gen_success(tmp_path: Path) -> None:
    src = _write_png(tmp_path / "src.png")
    out = tmp_path / "trans.mp4"
    prompt = build_transition_prompt("wide street", "alice close-up", missing_info="Alice face")
    assert "Alice face" in prompt

    async def fake_video_gen(**kwargs: object) -> Path:
        path = Path(str(kwargs["output_path"]))
        path.write_bytes(b"mp4")
        return path

    result = await generate_transition_video(
        TransitionSpec(
            source_frame=src,
            target_frame=None,
            output_path=out,
            first_shot_visual_desc="wide street",
            second_shot_visual_desc="alice close-up",
            missing_info="Alice face",
        ),
        video_gen=fake_video_gen,
    )
    assert result.strategy_used == "video_gen"
    assert out.exists()


@pytest.mark.asyncio
async def test_kernel_workflow_writes_report(tmp_path: Path) -> None:
    result = await script2video_kernel_workflow(
        Script2VideoKernelConfig(style="anime"),
        Script2VideoKernelInput(
            shots=[
                {
                    "visual_prompt": "Wide gym, John dribbling",
                    "camera_setup_ref": "master",
                    "scene_name": "gym",
                    "character_names": ["John"],
                    "cam_idx": 0,
                },
                {
                    "visual_prompt": "Close-up John 转身面对镜头",
                    "camera_setup_ref": "cu",
                    "scene_name": "gym",
                    "character_names": ["John"],
                },
            ],
            characters=[{"name": "John", "description": "tall athlete"}],
        ),
        tmp_path,
    )
    assert result["status"] == "completed"
    assert result["generation_order"][0] == 0
    report = Path(result["report_path"])
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "decision_trail" in text
    assert "last_frame_shots" in text


@pytest.mark.asyncio
async def test_kernel_workflow_empty_shots_fails_without_raise(tmp_path: Path) -> None:
    result = await script2video_kernel_workflow(
        Script2VideoKernelConfig(),
        Script2VideoKernelInput(shots=[]),
        tmp_path,
    )
    assert result["status"] == "failed"
    assert "no shots" in result["error"]


def test_shot_list_bridge_projects_blocking_and_beats() -> None:
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="s1",
                scene_no=1,
                visual_prompt="Master of the gym",
                camera_setup_ref="master",
                scene_name="gym",
                character_names=["John", "Jane"],
                action_beats=["dribble", "shoot"],
                blocking=[ShotBlocking(character_name="John", facing="背对")],
                azimuth_deg=30,
            )
        ]
    )
    payload = kernel_shot_payload(shot_list.shots[0], index=0)
    assert payload["facing_hints"]["John"] == "背对"
    assert payload["action_beats"] == ["dribble", "shoot"]
    plan = plan_kernel_from_shot_list(shot_list)
    assert plan.shots[0].cam_key == "master"
    assert plan.visual_plans[0].idx == 0


def test_cam_idx_zero_is_a_valid_key() -> None:
    plan = plan_kernel_artifacts(
        [
            {"visual_desc": "A", "cam_idx": 0, "environment": "hall"},
            {"visual_desc": "B", "cam_idx": 0, "environment": "hall"},
            {"visual_desc": "C", "cam_idx": 1, "environment": "hall"},
        ]
    )
    assert len(plan.camera_tree.cameras) == 2
    assert plan.shots[0].cam_idx == plan.shots[1].cam_idx

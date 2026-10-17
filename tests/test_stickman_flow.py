import json
import subprocess
from pathlib import Path
import pytest

from hevi.stickman.proposal import StoryboardScene, DirectorProposal
from hevi.stickman.credits_ledger import CreditsLedger, CREDITS_PER_CLIP
from hevi.stickman.flow_pack import export_flow_pack
from hevi.stickman.flow_import import (
    import_and_stitch_flow_clips,
    probe_clip,
    FlowImportValidationError,
    FFMPEG,
)


def _make_dummy_clip(path: Path, duration_s: float, w: int = 1280, h: int = 720, color: str = "white") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={duration_s}",
        "-f", "lavfi", "-i", f"sine=f=440:d={duration_s},volume=0.05",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-t", str(duration_s),
        str(path),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def test_credits_ledger_operations(tmp_path):
    ledger_file = tmp_path / "credits.json"
    ledger = CreditsLedger(ledger_file, monthly_quota=1000, daily_quota=50)

    assert ledger.monthly_remaining == 1000
    assert ledger.daily_remaining == 50
    assert len(ledger.check_warnings()) == 0

    # Consume 2 clips (30 credits)
    res = ledger.record_consumption(proposal_id="p1", clip_count=2)
    assert res["total_cost"] == 30
    assert ledger.monthly_remaining == 970
    assert ledger.daily_remaining == 20
    assert len(ledger.check_warnings()) == 0

    # Consume another 1 clip (15 credits) -> daily remaining 5 (< 15 threshold)
    res2 = ledger.record_consumption(proposal_id="p2", clip_count=1)
    assert ledger.daily_remaining == 5
    warnings = ledger.check_warnings()
    assert len(warnings) >= 1
    assert "今日积分余额不足 15 点" in warnings[0]

    # Reload from file
    ledger2 = CreditsLedger(ledger_file)
    assert ledger2.monthly_remaining == 955
    assert ledger2.daily_remaining == 5


def test_flow_pack_export(tmp_path):
    scenes = [
        StoryboardScene(
            scene_index=1,
            stage="悬念追问",
            duration_s=10.0,
            visual_beats=["[0-3s] hook", "[3-7s] middle", "[7-10s] end"],
            narration_zh="为什么冰块放水里浮起来放油里沉底？",
            narration_en="Why does ice float in water but sink in oil?",
        ),
        StoryboardScene(
            scene_index=2,
            stage="常识铺垫",
            duration_s=10.0,
            visual_beats=["[0-3s] assume", "[3-7s] test", "[7-10s] finish"],
            narration_zh="我们总以为冰比所有液体都轻。",
            narration_en="We assume ice is lighter than all liquids.",
        ),
    ]

    proposal = DirectorProposal(
        proposal_id="prop_flow_test",
        title="浮力与密度",
        topic="浮力与密度",
        hook="为什么冰块会浮？",
        color_palette={"bg": "pure_white", "accent": "vivid red"},
        storyboard=scenes,
        voiceover={"profile": "Analytical Male", "pace_wpm": 130},
        bgm_style="Kinetic Piano",
        aspect_ratio="16:9",
        art_style="classic_minimalist",
        status="approved",
    )

    ledger = CreditsLedger(monthly_quota=1000, daily_quota=50)
    out_dir = tmp_path / "flow_pack_out"
    pack = export_flow_pack(proposal, out_dir, ledger=ledger)

    assert Path(pack["json_path"]).exists()
    assert Path(pack["txt_path"]).exists()
    assert pack["total_clips"] == 2
    assert pack["total_estimated_credits"] == 30

    data = json.loads(Path(pack["json_path"]).read_text(encoding="utf-8"))
    assert data["model_spec"]["model_name"] == "Omni Flash"
    assert data["model_spec"]["resolution"] == "720P"
    assert len(data["clips"]) == 2
    assert "CHARACTER DNA LOCK" in data["clips"][0]["prompt"]
    assert "Omni Flash" in data["clips"][0]["prompt"]

    # Ledger recorded
    assert ledger.daily_remaining == 20


def test_flow_import_and_stitch(tmp_path):
    scenes = [
        StoryboardScene(
            scene_index=1,
            stage="悬念追问",
            duration_s=3.0,
            visual_beats=["[0-3s] hook"],
            narration_zh="第一镜：为什么冰浮水沉油？",
            narration_en="Shot 1: Why ice floats in water but sinks in oil?",
        ),
        StoryboardScene(
            scene_index=2,
            stage="揭秘",
            duration_s=3.0,
            visual_beats=["[0-3s] reveal"],
            narration_zh="第二镜：因为水密度大于冰！",
            narration_en="Shot 2: Water density is higher than ice!",
        ),
    ]

    proposal = DirectorProposal(
        proposal_id="prop_import_test",
        title="导入测试",
        topic="测试",
        hook="测试",
        color_palette={"bg": "white"},
        storyboard=scenes,
        voiceover={"profile": "test"},
        bgm_style="piano",
        aspect_ratio="16:9",
        art_style="classic_minimalist",
        status="approved",
    )

    # Generate 2 test clips (3.0s each)
    c1 = tmp_path / "clip_01.mp4"
    c2 = tmp_path / "clip_02.mp4"
    _make_dummy_clip(c1, 3.0, color="gray")
    _make_dummy_clip(c2, 3.0, color="blue")

    out_stitched = tmp_path / "flow_stitched.mp4"
    res = import_and_stitch_flow_clips([c1, c2], proposal, out_stitched)

    assert Path(res["out_path"]).exists()
    assert res["duration_s"] >= 5.8
    assert res["clips_count"] == 2
    assert res["qa"]["ffprobe_verified"] is True

    # Test error when clip duration exceeds 10.5s
    c_long = tmp_path / "clip_long.mp4"
    _make_dummy_clip(c_long, 12.0)
    with pytest.raises(FlowImportValidationError) as exc:
        import_and_stitch_flow_clips([c_long, c2], proposal, tmp_path / "err.mp4")
    assert "超过限制" in str(exc.value)

    # Clean up test videos to preserve disk space
    for f in [c1, c2, c_long, out_stitched]:
        if f.exists():
            f.unlink()

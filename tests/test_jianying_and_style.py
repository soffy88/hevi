"""剪映草稿 + Style Skill —— 对照 jianying-editor-skill / OpenStoryline。"""

from __future__ import annotations

from hevi.studio.jianying import JianyingClip, JianyingDraft, clips_from_recut, write_jianying_draft
from hevi.studio.style_skill import apply_style, archive_style, load_style, save_style


def test_write_jianying_plan_is_not_a_draft(tmp_path):
    draft = JianyingDraft(
        name="demo",
        clips=[
            JianyingClip(path="/tmp/a.mp4", start_s=1.0, duration_s=2.5, track="video"),
            JianyingClip(path="", start_s=0.0, duration_s=2.5, track="text", text="秘密"),
        ],
    )
    dest = write_jianying_draft(draft, tmp_path / "draft")
    content = (dest / "plan.json").read_text(encoding="utf-8")
    meta = (dest / "plan_meta.json").read_text(encoding="utf-8")
    assert "JianyingPro" in meta
    assert "videos" in content
    assert "texts" in content
    assert not (dest / "draft_content.json").exists()
    assert draft.duration_s() == 2.5


def test_clips_from_recut_drops_and_bgm():
    clips = clips_from_recut(
        [
            {"action": "drop", "source": "x.mp4", "duration_s": 9},
            {"source": "a.mp4", "source_in_s": 3, "duration_s": 5},
        ],
        bgm="bed.mp3",
    )
    tracks = {c.track for c in clips}
    assert "video" in tracks and "audio" in tracks
    assert all(c.path != "x.mp4" for c in clips)


def test_style_skill_roundtrip(tmp_path):
    skill = archive_style(
        name="zhongcao",
        caption_mode="bilingual_ass",
        remove_fillers=True,
        recipe_cards=["karaoke-caption-lock"],
        timeline={"tracks": [{"name": "video"}, {"name": "voice"}]},
    )
    path = save_style(skill, tmp_path / "zhongcao.json")
    loaded = load_style(path)
    assert loaded.name == "zhongcao"
    assert loaded.remove_fillers is True
    plan = apply_style(loaded, media_path="new.mp4")
    assert plan["cuts"][0]["source"] == "new.mp4"
    assert plan["caption"]["mode"] == "bilingual_ass"
    assert "karaoke-caption-lock" in plan["recipe_cards"]


def test_native_draft_when_library_installed(tmp_path):
    import pytest
    from pathlib import Path

    pytest.importorskip("pyJianYingDraft")
    from hevi.studio.jianying_native import NativeItem, validate_native_draft, write_native_draft

    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"not-real-audio")
    # A text-only draft exercises the writer without probing media containers.
    items = [NativeItem(track="text", start_s=0, duration_s=2, text="你好")]
    export = write_native_draft("native-demo", items, tmp_path / "native")
    report = validate_native_draft(export.draft_dir)
    assert report["valid"], report["errors"]
    assert report["stats"]["material_buckets"] >= 40
    import zipfile

    assert Path(export.draft_zip).is_file()
    with zipfile.ZipFile(export.draft_zip) as zf:
        names = zf.namelist()
    assert "IMPORT_README.md" in names
    assert any(name.endswith("draft_content.json") for name in names)

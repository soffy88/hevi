"""Tests for image.pose_library (pose index only, no images bundled)."""

import json
from pathlib import Path

import pytest

from hevi.capabilities import pose_library
from hevi.capabilities.errors import CapabilityError


def test_counts_match_verified_numbers():
    counts = pose_library.counts()
    assert counts["records"] == 1439
    assert counts["groups"] == 288
    assert counts["distinct_names"] == 287
    assert counts["categories"] == 26
    assert counts["systems"] == {
        "full_standard": 365,
        "full_sexy": 399,
        "upper_body": 400,
        "two_person": 275,
    }
    assert counts["views"] == {
        "正面": 288,
        "斜侧": 288,
        "侧面": 288,
        "俯视": 288,
        "仰视": 287,
    }


def test_systems_and_categories():
    systems = pose_library.list_systems()
    assert [s["key"] for s in systems] == [
        "full_standard",
        "full_sexy",
        "upper_body",
        "two_person",
    ]
    assert sum(s["groups"] for s in systems) == 288
    categories = pose_library.list_categories()
    assert len(categories) == 26
    assert "站姿" in categories
    assert "骑乘位" in categories


def test_index_groups_are_complete_except_one_known_gap():
    index = pose_library.load_index()
    incomplete = [g for g in index["groups"] if not g["complete"]]
    assert [(g["key"], g["missing_views"]) for g in incomplete] == [
        ("full_sexy_P018", ["仰视"])
    ]
    for group in index["groups"]:
        assert set(group["views"]) == set(pose_library.VIEWS)
        assert group["view_count"] == 5 - len(group["missing_views"])
        for view, entry in group["views"].items():
            if entry is not None:
                assert entry["thumb"].startswith("thumbs/")
                assert entry["image"].startswith("img/")


def test_search_by_name_and_category():
    hits = pose_library.search_poses(query="比心")
    assert hits
    assert all("比心" in h["name"] for h in hits)
    assert all(h["system"] == "upper_body" for h in hits)
    hits = pose_library.search_poses(category="站姿", system="full_standard")
    assert hits
    assert all(h["category"] == "站姿" and h["system"] == "full_standard" for h in hits)
    assert pose_library.search_poses(query="不存在的姿势名称xyz") == []


def test_search_view_filter_excludes_group_missing_that_view():
    hits = pose_library.search_poses(system="full_sexy", view="仰视", limit=200)
    assert all(h["key"] != "full_sexy_P018" for h in hits)
    assert len(hits) == 79  # 80 groups in the system minus the one missing 仰视


def test_search_rejects_unknown_filters():
    with pytest.raises(CapabilityError):
        pose_library.search_poses(system="nope")
    with pytest.raises(CapabilityError):
        pose_library.search_poses(category="不存在的分类")
    with pytest.raises(CapabilityError):
        pose_library.search_poses(view="背面")
    with pytest.raises(CapabilityError):
        pose_library.search_poses(limit=0)


def test_get_pose_and_unknown():
    pose = pose_library.get_pose("full_standard", "P001")
    assert pose["system"] == "full_standard"
    assert pose["views"]["正面"] is not None
    assert pose_library.get_pose_by_key(pose["key"]) == pose
    with pytest.raises(CapabilityError):
        pose_library.get_pose("full_standard", "P999")
    with pytest.raises(CapabilityError):
        pose_library.get_pose("nope", "P001")


def test_risk_hints_follow_tier_vocabulary():
    two = pose_library.get_pose("two_person", "P001")
    hint = pose_library.risk_hint(two)
    assert hint["tier"] == "high"
    assert hint["suggestion"]
    sexy = pose_library.get_pose("full_sexy", "P001")
    assert pose_library.risk_hint(sexy)["tier"] == "medium"
    standard = pose_library.get_pose("full_standard", "P001")
    assert pose_library.risk_hint(standard)["tier"] == "low"


def _make_fixture_gallery(tmp_path: Path, present_rels: list[str]) -> Path:
    home = tmp_path / "gallery"
    for rel in present_rels:
        target = home / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")
    return home


def test_check_gallery_reports_missing_by_name(tmp_path, monkeypatch):
    index = pose_library.load_index()
    first = index["groups"][0]
    rels = []
    for entry in first["views"].values():
        rels += [entry["thumb"], entry["image"]]
    home = _make_fixture_gallery(tmp_path, rels)
    report = pose_library.check_gallery(str(home))
    assert report["home_exists"] is True
    assert report["total_files"] == 2878
    assert report["files_present"] == len(rels)
    assert report["files_missing"] == 2878 - len(rels)
    assert rels[0] not in report["missing"]


def test_missing_gallery_is_reported_not_faked(tmp_path, monkeypatch):
    missing_home = tmp_path / "no-such-gallery"
    report = pose_library.check_gallery(str(missing_home))
    assert report["home_exists"] is False
    assert report["files_present"] == 0
    assert report["files_missing"] == 2878
    monkeypatch.setenv("HEVI_POSE_GALLERY_HOME", str(missing_home))
    with pytest.raises(CapabilityError, match="not found"):
        pose_library.require_gallery_home()
    pose = pose_library.get_pose("full_standard", "P001")
    with pytest.raises(CapabilityError, match="not found"):
        pose_library.view_files(pose, "正面", strict=True)


def test_view_files_flags_and_strict_missing_file(tmp_path, monkeypatch):
    pose = pose_library.get_pose("full_standard", "P001")
    entry = pose["views"]["正面"]
    home = _make_fixture_gallery(tmp_path, [entry["thumb"]])
    flags = pose_library.view_files(pose, "正面", str(home))
    assert flags["thumb_exists"] is True
    assert flags["image_exists"] is False
    with pytest.raises(CapabilityError, match="missing pose files"):
        pose_library.view_files(pose, "正面", str(home), strict=True)
    with pytest.raises(CapabilityError, match="has no"):
        pose_library.view_files(
            pose_library.get_pose("full_sexy", "P018"), "仰视", str(home)
        )


def test_index_source_note_is_non_commercial():
    source = pose_library.load_index()["source"]
    assert source["non_commercial"] is True
    assert "original author" in source["license_note"]
    assert source["data_sha256"]


def test_registration_is_idempotent():
    names = pose_library.register_pose_library_capabilities_once()
    assert names == [] or names == ["image.pose_library"]


def test_render_check_action(tmp_path):
    out = tmp_path / "out"
    result = pose_library._render(
        {"action": "check", "home": str(tmp_path / "absent")},
        out,
        duration=0.0,
        aspect="16:9",
        seed=1,
    )
    report = json.loads((out / "pose_library_report.json").read_text(encoding="utf-8"))
    assert report["gallery"]["files_missing"] == 2878
    assert result.qa["report_json"].endswith("pose_library_report.json")

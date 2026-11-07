"""Tests for the portrait prompt vocabulary (hevi.image.portrait_vocab)
and its capability (image.portrait_vocab).

Offline and zero-cost: the library only assembles text.  The index
integrity tests pin the verbatim transcription of the source pages
(66 entries, 8 categories); the 窗边 (window seat) case replays the
source's own worked example.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.image import portrait_vocab as pv
from hevi.image.portrait_vocab import PortraitVocabError

EXPECTED_COUNTS = {
    "video_micro": 6,
    "posture": 8,
    "hair_head": 8,
    "hands": 9,
    "motion": 8,
    "sitting": 8,
    "standing": 9,
    "gaze": 10,
}

WINDOW_SELECTION = {
    "sitting": "SI-02",
    "gaze": "GA-01",
    "hands": "HA-08",
    "posture": "PO-02",
}
WINDOW_KWARGS = {
    "identity": "脸型五官按参考图",
    "subject": "成年女性穿燕麦色针织开衫",
    "scene": "雨后暖窗光照亮脸与手，玻璃留雨珠，室内稍暗",
    "framing": "拍到腰部，双手和支撑肘入画，写实皮肤，16:9",
}


# ---------------------------------------------------------------------------
# Index integrity (pins the transcription)
# ---------------------------------------------------------------------------


def test_index_counts_and_total() -> None:
    assert pv.counts() == EXPECTED_COUNTS
    assert pv.load_index()["total"] == 66
    assert len(pv.entries()) == 66


def test_index_fields_complete_and_ids_unique() -> None:
    seen: set[str] = set()
    for entry in pv.entries():
        for field in ("id", "category", "zh", "en", "how", "feeling"):
            assert entry[field], f"{entry.get('id')} missing {field}"
        assert entry["category"] in EXPECTED_COUNTS
        assert entry["id"] not in seen
        seen.add(entry["id"])
    assert len(seen) == 66


def test_index_spot_entries_verbatim() -> None:
    cup = pv.get_entry("HA-08")
    assert cup["zh"] == "手捧杯子"
    assert cup["en"] == "holding a cup"
    assert cup["how"] == "交代握杯把或扶杯身，以及杯子高度；坐姿可让前臂有支撑"
    assert cup["feeling"] == "日常温暖"
    closed = pv.get_entry("eyes closed")
    assert closed["id"] == "GA-08"
    assert closed["zh"] == "闭眼"
    chin = pv.get_entry("托腮")
    assert chin["id"] == "HA-05"
    assert chin["en"] == "chin resting on a hand"
    steps = pv.get_entry("SI-05")
    assert steps["en"] == "sitting on steps / on a bench"


def test_search_filters() -> None:
    hits = pv.search("gaze", query="镜头")
    assert {e["id"] for e in hits} >= {"GA-01", "GA-02"}
    assert all(e["category"] == "gaze" for e in hits)
    assert pv.search("", query="holding a cup")[0]["id"] == "HA-08"
    with pytest.raises(PortraitVocabError):
        pv.entries("expression")  # absent in the source; not invented


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


def test_assemble_window_example() -> None:
    out = pv.assemble(WINDOW_SELECTION, **WINDOW_KWARGS)
    zh = out["prompt_zh"]
    # identity first, then subject (person before scene)
    assert zh.startswith("脸型五官按参考图。成年女性穿燕麦色针织开衫。")
    # every pick expanded by its concrete `how` text, not bare terms
    assert "先有椅子等座位，再选身体朝向窗边或室内" in zh  # sitting SI-02
    assert "目光落在镜头，脸可略侧" in zh  # gaze GA-01
    assert "交代握杯把或扶杯身" in zh  # hands HA-08
    assert "肩自然下沉，颈部不缩" in zh  # posture PO-02
    # scene and framing come after the person
    assert "雨后暖窗光照亮脸与手，玻璃留雨珠，室内稍暗" in zh
    assert zh.endswith("拍到腰部，双手和支撑肘入画，写实皮肤，16:9。")
    en = out["prompt_en"]
    for phrase in (
        "relaxed shoulders",
        "sitting by the window",
        "holding a cup",
        "looking at the camera",
    ):
        assert phrase in en
    assert out["conflicts"] == []
    assert out["motion_prompt"] is None


def test_assemble_resolves_by_name_and_phrase() -> None:
    out = pv.assemble({"gaze": "看向镜头", "hands": "holding a cup"})
    assert [e["id"] for e in out["entries"]] == ["HA-08", "GA-01"]


def test_assemble_rejects_multi_pick_per_category() -> None:
    with pytest.raises(PortraitVocabError, match="at most one"):
        pv.assemble({"gaze": ["GA-01", "GA-02"]})


def test_assemble_rejects_wrong_category_and_unknown() -> None:
    with pytest.raises(PortraitVocabError, match="belongs to category"):
        pv.assemble({"gaze": "HA-08"})
    with pytest.raises(PortraitVocabError, match="unknown portrait vocab entry"):
        pv.assemble({"gaze": "GA-99"})
    with pytest.raises(PortraitVocabError, match="empty selection"):
        pv.assemble({})


def test_conflict_eyes_closed_vs_camera_gaze() -> None:
    picked = [pv.get_entry("GA-08"), pv.get_entry("GA-01")]
    conflicts = pv.find_conflicts(picked)
    assert any(
        {c["a"], c["b"]} == {"GA-08", "GA-01"} for c in conflicts
    )
    picked2 = [pv.get_entry("GA-08"), pv.get_entry("GA-02")]
    assert pv.find_conflicts(picked2)


def test_conflict_sitting_vs_standing_and_motion() -> None:
    with pytest.raises(PortraitVocabError, match="conflicting"):
        pv.assemble({"sitting": "SI-01", "standing": "ST-01"})
    with pytest.raises(PortraitVocabError, match="conflicting"):
        pv.assemble({"sitting": "SI-03", "motion": "MO-01"})
    out = pv.assemble(
        {"sitting": "SI-01", "standing": "ST-01"}, on_conflict="warn"
    )
    assert out["conflicts"] and out["warnings"]


def test_assemble_motion_mode() -> None:
    out = pv.assemble(
        {"video_micro": "VM-06", "gaze": "GA-01", "posture": "PO-02"},
        mode="motion",
    )
    assert out["motion_prompt"] is not None
    assert out["motion_prompt"].startswith(
        "turning her head toward the camera"
    )
    assert "looking at the camera" in out["motion_prompt"]
    assert "blinking naturally" not in out["motion_prompt"]


# ---------------------------------------------------------------------------
# Phrasing spec (the writing standard distilled from the vocabulary)
# ---------------------------------------------------------------------------


def test_phrasing_rules_present_and_grounded() -> None:
    rules = pv.phrasing_rules()
    assert len(rules) == 12
    titles = [r["title"] for r in rules]
    assert "动作必带支撑点与承重关系" in titles
    assert "视线、脸、身体三轴分开写" in titles
    assert "每轮只改最差一处，其余保持" in titles
    text = pv.phrasing_path().read_text(encoding="utf-8")
    # every rule carries a vocabulary-grounded example and a counter-example
    assert text.count("正例") >= 12
    assert text.count("反例") >= 12
    # grounded in actual `how` wording from the index
    assert pv.get_entry("HA-05")["how"] in text
    assert pv.get_entry("GA-01")["how"] in text


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


def test_capability_registered() -> None:
    import hevi.capabilities.portrait_vocab  # noqa: F401
    from hevi.capabilities.registry import contains, describe, get

    assert contains("image.portrait_vocab")
    cap = get("image.portrait_vocab")
    assert cap.kind == "shot"
    assert cap.line == "image"
    by_name = {item["name"]: item for item in describe()}
    assert by_name["image.portrait_vocab"].get("description")


def test_capability_list_and_assemble(tmp_path: Path) -> None:
    import hevi.capabilities.portrait_vocab  # noqa: F401
    from hevi.capabilities.registry import get

    cap = get("image.portrait_vocab")
    result = cap.render(
        {"action": "list", "category": "gaze"},
        tmp_path / "list",
        duration=0,
        aspect="16:9",
        seed=1,
    )
    catalogue = json.loads(
        Path(result.qa["catalogue_json"]).read_text(encoding="utf-8")
    )
    assert catalogue["returned"] == 10
    assert catalogue["counts"] == EXPECTED_COUNTS
    assert len(catalogue["phrasing"]["rules"]) == 12
    assert catalogue["phrasing"]["doc"].endswith("PHRASING.md")

    result = cap.render(
        {"action": "assemble", **WINDOW_SELECTION, **WINDOW_KWARGS},
        tmp_path / "asm",
        duration=0,
        aspect="16:9",
        seed=1,
    )
    payload = json.loads(
        Path(result.qa["prompt_json"]).read_text(encoding="utf-8")
    )
    assert payload["entry_ids"] == ["PO-02", "SI-02", "HA-08", "GA-01"]
    assert "looking at the camera" in payload["prompt_en"]
    assert payload["prompt_zh"].startswith("脸型五官按参考图。")
    assert result.qa["motion_prompt"] is None
    assert len(result.qa["phrasing_rules"]) == 12
    assert result.qa["phrasing_doc"].endswith("PHRASING.md")


def test_capability_assemble_motion_and_conflict(tmp_path: Path) -> None:
    import hevi.capabilities.portrait_vocab  # noqa: F401
    from hevi.capabilities.errors import CapabilityError
    from hevi.capabilities.registry import get

    cap = get("image.portrait_vocab")
    result = cap.render(
        {"action": "assemble", "mode": "motion", "video_micro": "VM-01"},
        tmp_path / "motion",
        duration=0,
        aspect="9:16",
        seed=1,
    )
    assert result.qa["motion_prompt"] == "blinking naturally"

    with pytest.raises(CapabilityError, match="conflicting"):
        cap.render(
            {"action": "assemble", "sitting": "SI-01", "standing": "ST-01"},
            tmp_path / "conflict",
            duration=0,
            aspect="9:16",
            seed=1,
        )

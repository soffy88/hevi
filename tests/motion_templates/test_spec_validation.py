"""Spec validation tests for Hevi Motion Templates."""

import json
from pathlib import Path
import pytest

SPECS_DIR = Path(__file__).resolve().parents[2] / "hevi" / "motion_templates" / "specs"

BANNED_BLUE_PURPLE_HEXES = ["#8b5cf6", "#7c3aed", "#6366f1", "#4f46e5", "#a855f7", "#9333ea"]

# Common multi-character words that must never be cut across two kinetic tokens.
COMMON_WORDS = [
    "宽高比", "阶跃响应", "弹簧", "过冲", "毫秒", "确定性", "复现",
    "像素", "重构", "节点", "点亮", "贯通", "交付", "出炉", "纯粹",
    "函数", "渲染", "多画幅", "自适应",
]

# Manually verified correct segmentation for two representative kinetic specs.
EXPECTED_TOKENS = {
    "kinetic_engine_tempo.json": {
        3: ["多画幅", "宽高比", "自动", "适配"],
    },
    "kinetic_bpm_beat_drop.json": {
        2: ["阶跃响应", "纯粹", "函数", "渲染"],
    },
}


def _split_word_across_tokens(tokens, word):
    """True if `word` occurs in the joined tokens but a token boundary cuts it."""
    joined = "".join(tokens)
    boundaries = set()
    acc = 0
    for tk in tokens[:-1]:
        acc += len(tk)
        boundaries.add(acc)
    start = joined.find(word)
    while start != -1:
        end = start + len(word)
        if any(start < b < end for b in boundaries):
            return True
        start = joined.find(word, start + 1)
    return False


def get_all_specs() -> list[Path]:
    assert SPECS_DIR.is_dir(), f"Specs directory {SPECS_DIR} must exist"
    specs = sorted(list(SPECS_DIR.glob("*.json")))
    assert len(specs) >= 6, f"Expected at least 6 specs, found {len(specs)}"
    return specs


@pytest.mark.parametrize("spec_path", get_all_specs())
def test_spec_structure_and_invariants(spec_path: Path):
    with open(spec_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Base required fields
    assert "title" in data, f"Missing title in {spec_path.name}"
    assert "duration" in data, f"Missing duration in {spec_path.name}"
    duration = float(data["duration"])
    assert 0 < duration <= 15.0, f"Duration must be <= 15.0s, got {duration} in {spec_path.name}"

    # 2. Rule: NO Chinese full stops ("。") on screen
    raw_json_str = json.dumps(data, ensure_ascii=False)
    assert "。" not in raw_json_str, f"Prohibited Chinese full stop '。' found in {spec_path.name}"

    # 3. Rule: NO large blue-purple dominant colors
    for banned in BANNED_BLUE_PURPLE_HEXES:
        assert banned.lower() not in raw_json_str.lower(), f"Banned blue-purple color {banned} in {spec_path.name}"

    # 4. Template-specific structure checks
    if "morph_ui" in spec_path.stem:
        assert "states" in data
        assert len(data["states"]) >= 4
        for s in data["states"]:
            assert "id" in s
            assert "type" in s
            assert "title" in s
            assert "accent" in s
    elif "timeline" in spec_path.stem:
        assert "milestones" in data
        assert len(data["milestones"]) >= 3
        for m in data["milestones"]:
            assert "index" in m
            assert "title_zh" in m
            assert "title_en" in m
            assert "desc_zh" in m
    elif "kinetic" in spec_path.stem:
        assert "bpm" in data
        assert "phrases" in data
        assert len(data["phrases"]) >= 3
        for p in data["phrases"]:
            assert "start_beat" in p
            assert "beats_count" in p
            assert "words" in p
            assert len(p["words"]) >= 3
    elif "layer_build" in spec_path.stem:
        assert "layers" in data
        assert len(data["layers"]) >= 3
        for l in data["layers"]:
            assert "id" in l
            assert "name_zh" in l
            assert "tag" in l


def get_kinetic_specs() -> list[Path]:
    return sorted(SPECS_DIR.glob("kinetic_*.json"))


@pytest.mark.parametrize("spec_path", get_kinetic_specs())
def test_kinetic_tokens_do_not_split_common_words(spec_path: Path):
    with open(spec_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for p_idx, phrase in enumerate(data["phrases"]):
        tokens = [str(w) for w in phrase["words"]]
        for word in COMMON_WORDS:
            assert not _split_word_across_tokens(tokens, word), (
                f"{spec_path.name} phrase {p_idx} splits common word '{word}' "
                f"across tokens {tokens}"
            )


def test_hand_verified_kinetic_tokenization():
    """Assert the manually corrected word segmentation for two example specs."""
    for spec_name, expected in EXPECTED_TOKENS.items():
        spec_path = SPECS_DIR / spec_name
        assert spec_path.is_file(), f"Missing example spec {spec_name}"
        with open(spec_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for phrase_idx, words in expected.items():
            actual = [str(w) for w in data["phrases"][phrase_idx]["words"]]
            assert actual == words, (
                f"{spec_name} phrase {phrase_idx} tokenization drift: {actual} != {words}"
            )
            for word in words:
                assert len(word) >= 1

"""Tests for the Gemini Omni Flash / Google Flow prompt pack export.

Contract under test (DIRSTYLE_TASK_ADD1):
- export_flow_pack writes pack.md + pack.json and calls no API.
- Hook lands inside the required 2-5 s window for 15/30/60 s.
- Every clip prompt independently repeats the full continuity
  lock block verbatim (character DNA, line weight, palette,
  composition, rhythm, voice profile, negative constraints).
- 9:16 and 16:9 produce different composition sentences
  (vertical recompose, not just a label change).
- Prompts contain no hex / RGB notation, no photorealistic /
  realistic wording, and no director names.
- Stickman art style + director overlay (e.g. wes_anderson)
  composes: stickman character + director composition/motion,
  while the art dimension (line / no realism) wins.
- Narration is audio-only; word-count scales per clip length.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hevi.layer4_legacy.dirstyle.omodul_impl.export_flow_pack import (
    FlowPack,
    export_flow_pack,
)

# A real Chinese source text (general knowledge, no invented data).
SOURCE_ZH = (
    "猫为什么总爱把桌上的东西推下去？背后有三个原因。"
    "首先，猫的脚垫非常敏感，触碰物体是在测试猎物。"
    "轻轻一推，如果物体会动或逃跑，就意味着可能是活物。"
    "其次，高处跌落产生的声音和运动轨迹，对猫的神经系统是强烈刺激。"
    "最后，猫咪发现只要东西掉地，主人就会立刻冲过来，"
    "哪怕被责备两句也是极好的互动。"
)

DIRECTOR_NAMES = [
    "王家卫",
    "张艺谋",
    "侯孝贤",
    "姜文",
    "杜琪峰",
    "贾樟柯",
    "诺兰",
    "韦斯",
    "昆汀",
    "大卫·芬奇",
    "wong kar wai",
    "zhang yimou",
    "hou hsiao hsien",
    "jiang wen",
    "johnnie to",
    "jia zhangke",
    "nolan",
    "wes anderson",
    "tarantino",
    "david fincher",
]

REALISM_WORDS = [
    "photorealistic",
    "photorealism",
    "realistic",
    "realism",
    "photo-real",
    "hyperrealistic",
    "cgi",
    "3d render",
    "photoreal",
    "写实",
    "照片级",
    "照片般",
]


def _tmp_output(tmp_path: Path) -> Path:
    return tmp_path / "flow_pack"


class TestExportFiles:
    def test_writes_pack_md_and_json(self, tmp_path):
        out = _tmp_output(tmp_path)
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=60,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=out,
        )
        assert Path(pack.pack_md_path).exists()
        assert Path(pack.pack_json_path).exists()
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        js = json.loads(Path(pack.pack_json_path).read_text(encoding="utf-8"))
        assert "Gemini Omni Flash" in md or "Google Flow" in md
        assert js["pack_version"] == 1
        assert js["art_style"] == "stickman_1a_light"

    def test_default_output_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=15,
            aspect="9:16",
            art_style="stickman_1a_light",
        )
        assert Path(pack.pack_md_path).exists()
        assert Path(pack.pack_json_path).exists()

    def test_invalid_duration_raises(self, tmp_path):
        with pytest.raises(ValueError):
            export_flow_pack(
                source_text=SOURCE_ZH,
                duration_s=0,
                aspect="9:16",
                art_style="stickman_1a_light",
                output_dir=_tmp_output(tmp_path),
            )

    def test_invalid_aspect_raises(self, tmp_path):
        with pytest.raises(ValueError):
            export_flow_pack(
                source_text=SOURCE_ZH,
                duration_s=30,
                aspect="4:3",
                art_style="stickman_1a_light",
                output_dir=_tmp_output(tmp_path),
            )


class TestHookTiming:
    @pytest.mark.parametrize("duration", [15, 30, 60])
    def test_hook_lands_2_to_5_seconds(self, tmp_path, duration):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=duration,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        assert pack.plan.hook_timing is not None
        assert pack.plan.hook_timing.hook_start_s == 2.0
        assert pack.plan.hook_timing.within_window() is True
        assert pack.plan.segments[0].hook is True
        for seg in pack.plan.segments[1:]:
            assert seg.hook is False

    def test_180s_hook_lands_5_to_15_seconds(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=180,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        assert pack.plan.hook_timing.hook_start_s == 5.0
        assert pack.plan.hook_timing.within_window() is True


class TestContinuityLockBlock:
    """Every clip prompt independently repeats the full lock block."""

    LOCK_KEYS = [
        "character_dna",
        "line_weight",
        "palette_words",
        "composition_aspect",
        "rhythm",
        "voice_profile",
        "negative_constraints",
    ]

    @pytest.mark.parametrize("duration", [15, 30, 60])
    def test_every_clip_has_complete_lock_block(self, tmp_path, duration):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=duration,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        for cp in pack.clip_prompts:
            gl = cp["global_continuity_lock"]
            for key in self.LOCK_KEYS:
                assert key in gl, f"clip {cp['clip_index']} missing {key}"
                assert gl[key], f"clip {cp['clip_index']} empty {key}"

    def test_lock_block_repeated_verbatim_in_markdown(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        dna = pack.clip_prompts[0]["global_continuity_lock"]["character_dna"]
        count = md.count(dna)
        assert count >= len(pack.clip_prompts), (
            f"character DNA appears {count}x, expected >= {len(pack.clip_prompts)}"
        )

    def test_no_same_character_shortcuts(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        md = Path(pack.pack_md_path).read_text(encoding="utf-8").lower()
        assert "same character" not in md
        assert "same as before" not in md
        assert "同上" not in md
        assert "see above" not in md

    def test_lock_block_identical_across_clips(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        blocks = [cp["global_continuity_lock"] for cp in pack.clip_prompts]
        for block in blocks[1:]:
            assert block == blocks[0], "lock block differs between clips"


class TestAspectRecompose:
    """9:16 and 16:9 must have genuinely different composition."""

    def test_9_16_vs_16_9_composition_differs(self, tmp_path):
        pack9 = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path) / "nine",
        )
        pack16 = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="16:9",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path) / "sixteen",
        )
        comp9 = pack9.clip_prompts[0]["global_continuity_lock"]["composition_aspect"]
        comp16 = pack16.clip_prompts[0]["global_continuity_lock"]["composition_aspect"]
        assert comp9 != comp16, "9:16 and 16:9 composition sentences are identical"
        assert "vertical" in comp9.lower() or "depth" in comp9.lower()
        assert "left" in comp16.lower() and "right" in comp16.lower()

    def test_9_16_uses_vertical_recompose_not_label(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        comp = pack.clip_prompts[0]["global_continuity_lock"]["composition_aspect"]
        assert "9:16" not in comp or "vertical" in comp.lower()
        assert any(w in comp.lower() for w in ("vertical", "depth", "stacked", "reveal"))


# ---------------------------------------------------------------------------
# FIX-R3 strengthened assertions (F1-F6 + B3 + B5)
# ---------------------------------------------------------------------------

#: The long Chinese fixture (>= 380 CJK chars) used for the 60 s pack.
FIXTURE_ZH = (Path(__file__).parent / "fixtures" / "long_zh_source.md").read_text(encoding="utf-8")

#: F3 forbidden terms that must never appear in a compiled prompt.
FORBIDDEN_PROMPT_TERMS = [
    "16:9",
    "2.39:1",
    "left, center, and right",
    "lateral",
    "horizontal",
    "vivid red",
    "electric blue",
    "mechanical horizontal track",
]

#: F2 words that are picture directions, not narration.
NARRATION_FORBIDDEN = ["火柴人", "画面", "背景", "镜头"]

#: F1 stickman beats must avoid facial + horizontal-motion directions.
STICKMAN_BEAT_FORBIDDEN = [
    "face",
    "facial",
    "expression",
    "眼神",
    "表情",
    "微笑",
    "horizontal",
    "lateral",
    "left to right",
    "横移",
    "左右",
]


def _cjk(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def _pack60(tmp_path: Path):
    return export_flow_pack(
        source_text=FIXTURE_ZH,
        duration_s=60,
        aspect="9:16",
        art_style="stickman_1a_light",
        narration_lang="zh",
        output_dir=tmp_path / "pack60",
    )


class TestF1Beats:
    """F1: three complete, distinct, narration-free beats per clip."""

    def test_beats_distinct_within_and_across_clips(self, tmp_path):
        pack = _pack60(tmp_path)
        all_beats: list[str] = []
        for cp in pack.clip_prompts:
            beats = cp["beats"]
            vals = [beats["0-3s"], beats["3-7s"], beats["7-10s"]]
            assert len(set(vals)) == 3, f"clip {cp['clip_index']} beats repeat: {vals}"
            all_beats.extend(vals)
        # Cross-clip: the first beat of a clip must not equal any earlier beat.
        firsts = [cp["beats"]["0-3s"] for cp in pack.clip_prompts]
        assert len(set(firsts)) == len(firsts), "clip first-beats are not all distinct"
        assert len(set(all_beats)) == len(all_beats), "beats repeat across clips"

    def test_beats_are_not_narration_and_not_truncated(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            narr = cp["narration"]
            for b in cp["beats"].values():
                assert "..." not in b
                assert "transition from" not in b.lower()
                assert b != narr
                assert narr not in b
                # a beat is a picture action, so it must mention the figure
                assert "stickman" in b.lower()

    def test_stickman_beats_avoid_face_and_horizontal(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for b in cp["beats"].values():
                low = b.lower()
                for w in STICKMAN_BEAT_FORBIDDEN:
                    assert w.lower() not in low, f"beat contains {w!r}: {b}"


class TestF2Narration:
    """F2: 40-66 Chinese chars, source-only, no picture words, clean punct."""

    def test_narration_cjk_in_range(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            n = _cjk(cp["narration"])
            assert 40 <= n <= 66, f"clip {cp['clip_index']} narration cjk={n}"

    def test_narration_has_no_picture_words(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for w in NARRATION_FORBIDDEN:
                assert w not in cp["narration"], f"narration has picture word {w!r}"

    def test_narration_no_dirty_punctuation(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            assert "。，" not in cp["narration"]
            assert "，。" not in cp["narration"]

    def test_narration_numbers_subset_of_source(self, tmp_path):
        src_nums = set(re.findall(r"\d+", FIXTURE_ZH))
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for num in re.findall(r"\d+", cp["narration"]):
                assert num in src_nums, f"invented number {num}"

    def test_narration_chars_come_from_source(self, tmp_path):
        # Every CJK char in the narration must appear in the source text.
        src_chars = set(re.findall(r"[一-鿿]", FIXTURE_ZH))
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for ch in re.findall(r"[一-鿿]", cp["narration"]):
                assert ch in src_chars, f"narration char {ch!r} not in source"


class TestF3CompiledPrompt:
    """F3: palette match, no forbidden terms, no CJK, no narration echo."""

    def test_prompt_palette_matches_lock_block(self, tmp_path):
        pack = _pack60(tmp_path)
        lock = pack.clip_prompts[0]["global_continuity_lock"]["palette_words"]
        lock_words = [w.strip() for w in lock.split(",")]
        assert len(lock_words) <= 3
        for cp in pack.clip_prompts:
            pos = cp["prompt"]["positive"]
            for w in lock_words:
                assert w in pos, f"palette word {w!r} missing from compiled prompt"
            # no colour-bearing word beyond the lock block (checked as whole
            # phrases so 'crimson red' is not double-counted as crimson + red)
            colour_terms = [
                "crimson red",
                "cobalt blue",
                "amber gold",
                "pastel pink",
                "mustard yellow",
                "mint green",
                "sky blue",
                "warm gold",
                "vivid red",
                "electric blue",
                "magenta",
                "vermillion",
                "imperial yellow",
                "cyan-blue",
                "seafoam",
                "teal green",
            ]
            extra = [c for c in colour_terms if c in pos and c not in lock_words]
            assert not extra, f"prompt has colour terms outside lock block: {extra}"

    def test_prompt_no_forbidden_terms(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            pos = cp["prompt"]["positive"]
            for term in FORBIDDEN_PROMPT_TERMS:
                assert term.lower() not in pos.lower(), f"forbidden term {term!r} in prompt"

    def test_prompt_en_has_no_cjk(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            pos = cp["prompt"]["positive"]
            assert not re.search(r"[一-鿿]", pos), "CJK leaked into compiled prompt"

    def test_prompt_does_not_echo_narration(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            narr = cp["narration"]
            assert narr not in cp["prompt"]["positive"]
            assert narr not in cp["prompt"]["negative"]


class TestF5VoiceProfile:
    """F5: a frozen 'Voice profile:' line, verbatim in every clip + json."""

    def test_lock_block_has_voice_profile(self, tmp_path):
        pack = _pack60(tmp_path)
        lock = pack.clip_prompts[0]["global_continuity_lock"]
        assert lock["voice_profile"].startswith("Voice profile:")
        assert "字/秒" in lock["voice_profile"]

    def test_voice_profile_verbatim_across_clips(self, tmp_path):
        pack = _pack60(tmp_path)
        profiles = {cp["global_continuity_lock"]["voice_profile"] for cp in pack.clip_prompts}
        assert len(profiles) == 1, "voice profile differs between clips"

    def test_voice_profile_in_pack_md_per_clip(self, tmp_path):
        pack = _pack60(tmp_path)
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        vp = pack.clip_prompts[0]["global_continuity_lock"]["voice_profile"]
        assert md.count(vp) >= len(pack.clip_prompts)


class TestF6Transitions:
    """F6: full transition table + First/Last frame per clip."""

    def test_transition_table_complete(self, tmp_path):
        pack = _pack60(tmp_path)
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        # one table row per clip, and no truncated cell anywhere in the table
        rows = [l for l in md.splitlines() if re.match(r"^\| Clip \d", l)]
        assert len(rows) == len(pack.clip_prompts)
        assert "Opening Frame" in md and "Closing Frame" in md
        for row in rows:
            assert "..." not in row, f"truncated transition row: {row}"

    def test_last_frame_equals_next_first_frame(self, tmp_path):
        pack = _pack60(tmp_path)
        segs = pack.plan.segments
        for i in range(1, len(segs)):
            assert segs[i].visual_state_start == segs[i - 1].visual_state_end, (
                f"handoff broken between clip {i - 1} and {i}"
            )

    def test_first_frame_differs_from_last_frame(self, tmp_path):
        pack = _pack60(tmp_path)
        for seg in pack.plan.segments:
            assert seg.visual_state_start != seg.visual_state_end

    def test_frames_are_not_narration(self, tmp_path):
        pack = _pack60(tmp_path)
        for seg in pack.plan.segments:
            assert seg.visual_state_start != seg.narration
            assert seg.visual_state_end != seg.narration
            assert seg.narration not in seg.visual_state_start

    def test_clip_md_has_first_and_last_frame(self, tmp_path):
        pack = _pack60(tmp_path)
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        assert md.count("**First frame:**") == len(pack.clip_prompts)
        assert md.count("**Last frame:**") == len(pack.clip_prompts)


class TestB3CleanSource:
    """B3: the E2E source must be text-free and not the forbidden footage."""

    def test_source_record_declares_generated(self):
        rec_path = Path("output/dirstyle_e2e/record.json")
        if not rec_path.exists():
            pytest.skip("record.json not present")
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        src = rec["source"]
        assert src["kind"] in {"generated", "cc0"}
        blob = json.dumps(src, ensure_ascii=False).lower()
        for bad in ("长城", "greatwall", "shot 02", "watermark"):
            assert bad not in blob

    def test_source_name_has_no_forbidden_token(self):
        rec_path = Path("output/dirstyle_e2e/record.json")
        if not rec_path.exists():
            pytest.skip("record.json not present")
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        name = rec["source"]["path"].lower()
        for bad in ("长城", "greatwall", "shot"):
            assert bad not in name

    def test_source_frames_have_no_burned_text(self):
        """OCR-free check: no dense horizontal-stroke band in caption zones.

        Burned-in subtitles / watermarks show up as a cluster of short,
        high-contrast horizontal strokes.  We extract three frames from the
        source and assert the bottom 25% band and the top corners carry no
        such dense stroke cluster (measured by per-row count of strong
        horizontal edges).
        """
        src = Path("output/dirstyle_e2e/source_clean.mp4")
        if not src.exists():
            pytest.skip("source_clean.mp4 not present")
        import subprocess

        import numpy as np
        from PIL import Image

        for frac in (0.25, 0.5, 0.75):
            png = Path("/tmp") / f"_b3_src_{int(frac * 100)}.png"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(12.0 * frac),
                    "-i",
                    str(src),
                    "-frames:v",
                    "1",
                    str(png),
                ],
                check=True,
                capture_output=True,
            )
            arr = np.array(Image.open(png).convert("L")).astype(float)
            h, w = arr.shape
            # strong horizontal edges per row (a caption row lights up)
            edges = (np.abs(np.diff(arr, axis=1)) > 60).mean(axis=1)
            bottom = edges[int(h * 0.75) :]
            top = edges[: int(h * 0.15)]
            assert bottom.max() < 0.25, f"dense strokes in bottom band ({bottom.max():.2f})"
            assert top.max() < 0.25, f"dense strokes in top band ({top.max():.2f})"


class TestB5Stickman:
    """B5: subtitle lines inside [90, 990]; >=4 distinct poses."""

    def test_pose_metadata_has_four_plus_poses(self):
        p = Path("output/dirstyle_e2e/stickman_poses.json")
        if not p.exists():
            pytest.skip("stickman_poses.json not present")
        meta = json.loads(p.read_text(encoding="utf-8"))
        assert meta["distinct_pose_count"] >= 4, meta["distinct_poses"]
        # adjacent pose segments must differ in keypoints
        frames = meta["frames"]
        seen = []
        prev = None
        for f in frames:
            kp = tuple(f["pose_keypoints"])
            if prev is None or kp != prev:
                seen.append(kp)
                prev = kp
        assert len(seen) >= 4, "fewer than 4 distinct pose segments"

    def test_subtitle_boxes_in_safe_band(self):
        p = Path("output/dirstyle_e2e/stickman_poses.json")
        if not p.exists():
            pytest.skip("stickman_poses.json not present")
        meta = json.loads(p.read_text(encoding="utf-8"))
        for f in meta["frames"]:
            assert len(f["subtitle_boxes"]) <= 2, "more than 2 subtitle lines"
            for x0, y0, x1, y1 in f["subtitle_boxes"]:
                assert x0 >= 90 - 1, f"subtitle left {x0} < 90"
                assert x1 <= 990 + 1, f"subtitle right {x1} > 990"

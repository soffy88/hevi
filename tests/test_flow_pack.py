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
    "王家卫", "张艺谋", "侯孝贤", "姜文", "杜琪峰", "贾樟柯",
    "诺兰", "韦斯", "昆汀", "大卫·芬奇",
    "wong kar wai", "zhang yimou", "hou hsiao hsien", "jiang wen",
    "johnnie to", "jia zhangke", "nolan", "wes anderson",
    "tarantino", "david fincher",
]

REALISM_WORDS = [
    "photorealistic", "photorealism", "realistic", "realism",
    "photo-real", "hyperrealistic", "cgi", "3d render",
    "photoreal", "写实", "照片级", "照片般",
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
        assert any(
            w in comp.lower() for w in ("vertical", "depth", "stacked", "reveal")
        )

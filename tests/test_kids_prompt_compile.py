"""Tests for prompt compilation with Style Bible verbatim front-loading (FIX-14)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from hevi.kids.consistency_manifest import KidsConsistencyManifest
from hevi.kids.prompt_compile import compile_shot_prompt, validate_style_bible_preamble, style_bible_preamble

FIX = Path(__file__).parent / "fixtures" / "kids"


def test_compile_shot_prompt_verbatim_prefix() -> None:
    raw = json.loads((FIX / "manifest_fox_star.json").read_text(encoding="utf-8"))
    manifest = KidsConsistencyManifest.model_validate(raw)

    prompt = compile_shot_prompt(manifest, 1)
    preamble = style_bible_preamble(manifest.style_bible)

    assert prompt.startswith(preamble)
    errors = validate_style_bible_preamble(prompt, manifest.style_bible)
    assert errors == []


def test_compile_shot_prompt_tampered_fails() -> None:
    raw = json.loads((FIX / "manifest_fox_star.json").read_text(encoding="utf-8"))
    manifest = KidsConsistencyManifest.model_validate(raw)

    prompt = compile_shot_prompt(manifest, 1)
    # 篡改 prompt 中的 Style Bible 内容
    tampered = prompt.replace("明亮柔和马卡龙调", "暗黑重金属风")
    errors = validate_style_bible_preamble(tampered, manifest.style_bible)
    assert len(errors) > 0


def test_style_bible_change_reflects_in_prompt() -> None:
    raw = json.loads((FIX / "manifest_fox_star.json").read_text(encoding="utf-8"))
    m1 = KidsConsistencyManifest.model_validate(raw)
    p1 = compile_shot_prompt(m1, 1)

    raw2 = json.loads((FIX / "manifest_fox_star.json").read_text(encoding="utf-8"))
    raw2["style_bible"]["art_style"] = "纯色极简线条风"
    m2 = KidsConsistencyManifest.model_validate(raw2)
    p2 = compile_shot_prompt(m2, 1)

    assert p1 != p2
    assert "纯色极简线条风" in p2
    assert "纯色极简线条风" not in p1

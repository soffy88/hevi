"""Tests for the prompt compiler (oskill, pure function)."""
from __future__ import annotations

import re

import pytest

from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import compile_prompt


VAGUE_WORDS = [
    "电影感", "cinematic", "大片感", "epic", "masterpiece",
    "高级感", "氛围感", "beautiful", "stunning", "gorgeous",
    "dreamy", "moody", "atmospheric", "photorealistic", "8k masterpiece",
    "质感",
]


DIRECTOR_NAMES = [
    "王家卫", "张艺谋", "侯孝贤", "姜文", "杜琪峰", "贾樟柯",
    "诺兰", "韦斯", "昆汀", "大卫·芬奇",
    "wong kar wai", "zhang yimou", "hou hsiao hsien", "jiang wen",
    "johnnie to", "jia zhangke", "nolan", "wes anderson",
    "tarantino", "david fincher",
]


class TestCompiler:
    def test_basic_compile(self):
        r = compile_prompt(
            "wong_kar_wai",
            scene="雨夜电话亭",
            action="打电话",
            camera_move="handheld slight sway",
            aspect="9:16",
            lang="zh",
            target="video",
        )
        assert r["style_id"] == "wong_kar_wai"
        assert "positive" in r and "negative" in r and "provenance" in r
        assert r["positive"].strip()
        assert r["negative"].strip()
        assert r["provenance"]

    def test_no_vague_words_in_positive(self):
        for sid in ["wong_kar_wai", "nolan", "fincher", "wes_anderson", "zhang_yimou", "tarantino"]:
            r = compile_prompt(sid, scene="city night", target="video")
            for w in VAGUE_WORDS:
                assert w.lower() not in r["positive"].lower(), (
                    f"{sid}: found vague word {w!r} in positive"
                )

    def test_no_director_name_in_positive(self):
        for sid in ["wong_kar_wai", "nolan", "wes_anderson", "fincher"]:
            r = compile_prompt(sid, scene="city night", target="video")
            pos_lower = r["positive"].lower()
            for name in DIRECTOR_NAMES:
                assert name.lower() not in pos_lower, (
                    f"{sid}: found director name {name!r} in positive"
                )

    def test_keyframe_truncation(self):
        r = compile_prompt(
            "wong_kar_wai", scene="雨夜电话亭", target="keyframe"
        )
        # keyframe target should be shorter than video target
        r_video = compile_prompt(
            "wong_kar_wai", scene="雨夜电话亭", target="video"
        )
        assert len(r["positive"]) <= len(r_video["positive"])
        assert len(r["positive"]) <= 250

    def test_all_styles_compile(self):
        from hevi.layer4_legacy.dirstyle.oprim_impl import list_styles
        for sid in list_styles():
            r = compile_prompt(sid, scene="city", target="video")
            assert r["positive"].strip(), f"{sid} empty positive"
            assert r["negative"].strip(), f"{sid} empty negative"

    def test_keyframe_keeps_signature(self):
        """Signature elements (missing-one-not-allowed) must survive truncation."""
        r = compile_prompt(
            "wong_kar_wai",
            scene="city street at night with a neon-lit alley and rain-slicked pavement",
            target="keyframe",
        )
        # 王家卫签名三要素必须都在（英文）
        pos_lower = r["positive"].lower()
        assert "step-printed" in pos_lower or "拖影" in pos_lower, "Missing 拖影 in keyframe"
        assert "teal" in pos_lower or "青绿" in pos_lower, "Missing 青绿 in keyframe"
        assert any(k in pos_lower for k in ("foreground", "框架", "遮挡", "peek")), "Missing 框架 in keyframe"

    def test_negative_from_style(self):
        r = compile_prompt("wes_anderson", scene="dollhouse", target="video")
        # Wes negative should include 'asymmetry' or 'handheld'
        neg_lower = r["negative"].lower()
        assert "asymmetry" in neg_lower or "handheld" in neg_lower


class TestAnimeSafeFiltering:
    """Test that guofeng_anime + director styles don't emit photoreal conflict words."""

    def test_wong_kar_wai_anime_safe(self):
        """王家卫 + 国风动漫 must not emit photoreal/realistic/photo."""
        from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import compile_prompt
        r = compile_prompt(
            "wong_kar_wai", scene="city night", target="video",
            keyframe_style="anime_guofeng",
        )
        positive = r["positive"]
        assert "photoreal" not in positive.lower(), "Found photoreal in wong+anime"
        assert "photo" not in positive.lower() or "foreground" in positive.lower(), "Found bare photo"
        assert "realistic" not in positive.lower(), "Found realistic in wong+anime"

    def test_finch_anime_safe(self):
        r = compile_prompt(
            "fincher", scene="office", target="video",
            keyframe_style="anime_guofeng",
        )
        assert "photoreal" not in r["positive"].lower()

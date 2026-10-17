"""Tests for director-style library and schema validation."""
from __future__ import annotations

import pytest

from hevi.layer4_legacy.dirstyle.oprim_impl.models import ARTICLE_DIRECTOR_IDS
from hevi.layer4_legacy.dirstyle.oprim_impl import (
    check_article_directors,
    get_style,
    list_styles,
    load_styles,
)


class TestLoadStyles:
    def test_loads_all_styles(self):
        styles = load_styles()
        assert len(styles) >= 18, f"Expected >=18 styles, got {len(styles)}"

    def test_list_styles_sorted(self):
        ids = list_styles()
        assert ids == sorted(ids)

    def test_all_styles_have_required_fields(self):
        styles = load_styles()
        required = [
            "id", "display_zh", "display_en", "source",
            "lens_aspect", "composition", "lighting", "color",
            "motion", "rhythm", "signature", "negative",
            "fits", "avoid", "vertical_9x16", "grade",
        ]
        for sid, s in styles.items():
            for field in required:
                val = getattr(s, field)
                assert val is not None and val != "", (
                    f"{sid} missing required field '{field}'"
                )


class TestArticleDirectors:
    """The 10 article directors must all be present with non-empty fields."""

    def test_all_10_present(self):
        present = check_article_directors()
        missing = set(ARTICLE_DIRECTOR_IDS) - present
        assert not missing, f"Missing article directors: {missing}"

    @pytest.mark.parametrize("did", ARTICLE_DIRECTOR_IDS)
    def test_article_director_fields_nonempty(self, did):
        s = get_style(did)
        assert s.lens_aspect["focal"], f"{did}: lens.focal empty"
        assert s.lens_aspect["aspect"], f"{did}: lens.aspect empty"
        assert s.composition["rules"], f"{did}: composition.rules empty"
        assert s.lighting["rules"], f"{did}: lighting.rules empty"
        assert s.color["rules"], f"{did}: color.rules empty"
        assert s.motion["rules"], f"{did}: motion.rules empty"
        assert s.rhythm["avg_shot_s"] > 0, f"{did}: rhythm.avg_shot_s"
        assert s.signature, f"{did}: signature empty"
        assert s.negative, f"{did}: negative empty"
        assert s.vertical_9x16["mode"] in (
            "letterbox", "recompose", "letterbox_and_recompose", "native"
        )

    def test_wong_kar_wai_signature_three_elements(self):
        """王家卫签名三要素必须都在."""
        s = get_style("wong_kar_wai")
        required = [sig for sig in s.signature if sig.get("required")]
        req_zh = [r["zh"] for r in required]
        assert any("拖影" in z for z in req_zh), "Missing 抽帧拖影"
        assert any("双色调" in z or "青绿" in z for z in req_zh), "Missing 双色/青绿"
        assert any("框架" in z or "偷窥" in z or "遮挡" in z for z in req_zh), "Missing 框架/偷窥"


class TestSchemaValidation:
    def test_invalid_style_raises(self):
        from hevi.layer4_legacy.dirstyle.oprim_impl.models import from_dict
        bad = {"id": "bad"}
        with pytest.raises(KeyError):
            from_dict(bad)


class TestWideAspect:
    @pytest.mark.parametrize(
        "did", ["wong_kar_wai", "zhang_yimou", "nolan", "fincher", "tarantino"]
    )
    def test_wide_directors_flagged(self, did):
        s = get_style(did)
        assert s.is_wide_aspect(), f"{did} should be wide aspect"

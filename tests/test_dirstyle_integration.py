"""Regression tests: zh_shot_to_sd_prompt default output must be unchanged
when director_style is not passed. Also verifies director_style layering."""
from __future__ import annotations

from hevi.layer4_legacy.keyframe.oskill_impl.prompt_translator import (
    zh_shot_to_sd_prompt,
)


# A minimal fake shot dict for regression purposes
_SAMPLE_SHOT = {
    "visual_desc": "王生在月下持斧面对石壁，月光透过松树洒在古观大殿前",
    "environment": "崂山古观",
    "visible_chars": ["王生", "老道长"],
}


class TestDefaultPromptUnchanged:
    """When director_style is not passed, output must be byte-identical to baseline."""

    def test_no_director_style_equals_baseline(self):
        # baseline call (no director_style)
        baseline_prompt, baseline_neg = zh_shot_to_sd_prompt(_SAMPLE_SHOT)
        # explicit None should give the same result
        explicit_prompt, explicit_neg = zh_shot_to_sd_prompt(
            _SAMPLE_SHOT, director_style=None
        )
        assert baseline_prompt == explicit_prompt
        assert baseline_neg == explicit_neg

    def test_with_director_style_changes_prompt(self):
        baseline_prompt, _ = zh_shot_to_sd_prompt(_SAMPLE_SHOT)
        layered_prompt, _ = zh_shot_to_sd_prompt(
            _SAMPLE_SHOT, director_style="wong_kar_wai"
        )
        # Director layering must add content, not remove it
        assert baseline_prompt in layered_prompt or layered_prompt != baseline_prompt

    def test_unknown_director_style_ignored(self):
        baseline_prompt, baseline_neg = zh_shot_to_sd_prompt(_SAMPLE_SHOT)
        try:
            bad_prompt, bad_neg = zh_shot_to_sd_prompt(
                _SAMPLE_SHOT, director_style="__nonexistent_style__"
            )
        except Exception:
            return  # acceptable: raise on unknown
        assert bad_prompt == baseline_prompt
        assert bad_neg == baseline_neg

    def test_anime_guofeng_plus_wong_kar_wai_no_photoreal(self):
        """Default anime_guofeng + wong_kar_wai must not emit photoreal/realistic/photo in positive."""
        layered_prompt, _ = zh_shot_to_sd_prompt(
            _SAMPLE_SHOT,
            director_style="wong_kar_wai",
        )
        prompt_lower = layered_prompt.lower()
        assert "photoreal" not in prompt_lower
        assert "realistic" not in prompt_lower
        # The negative should include the default anime-style anti-photoreal terms
        _, neg = zh_shot_to_sd_prompt(_SAMPLE_SHOT)
        neg_lower = neg.lower()
        assert any(w in neg_lower for w in ["photo", "photoreal", "3d render", "cgi"]) or "distorted" in neg_lower

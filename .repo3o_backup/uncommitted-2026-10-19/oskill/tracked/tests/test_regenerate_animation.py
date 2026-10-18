"""Tests for regenerate_animation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from oprim._animation_types import AnimationResult

from oskill._regenerate_animation import regenerate_animation

_GOOD = AnimationResult(
    html="<html><body>new</body></html>",
    is_valid=True,
    validation_violations=[],
    entity_meta={},
)


class TestRegenerateAnimation:
    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_returns_animation_result(self, mock_gen):
        mock_gen.return_value = _GOOD
        result = await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            previous_html="<html>old</html>",
            llm=None,
        )
        assert isinstance(result, AnimationResult)

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_previous_html_included_in_prompt(self, mock_gen):
        mock_gen.return_value = _GOOD
        await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="Make better",
            previous_html="<html>PREV</html>",
            llm=None,
        )
        call_kwargs = mock_gen.call_args.kwargs
        assert "PREV" in call_kwargs["domain_prompt"]

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_entity_meta_is_regeneration_true(self, mock_gen):
        mock_gen.return_value = _GOOD
        result = await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            previous_html="<p>old</p>",
            llm=None,
        )
        assert result.entity_meta.get("is_regeneration") is True

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_entity_meta_has_previous_html_len(self, mock_gen):
        prev = "<html>old version</html>"
        mock_gen.return_value = _GOOD
        result = await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            previous_html=prev,
            llm=None,
        )
        assert result.entity_meta.get("previous_html_len") == len(prev)

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_empty_previous_html_works(self, mock_gen):
        mock_gen.return_value = _GOOD
        result = await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            previous_html="",
            llm=None,
        )
        assert isinstance(result, AnimationResult)
        assert result.entity_meta.get("previous_html_len") == 0

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_domain_prompt_preserved_in_augmented_prompt(self, mock_gen):
        mock_gen.return_value = _GOOD
        await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="ORIGINAL_DOMAIN",
            previous_html="<p>old</p>",
            llm=None,
        )
        call_kwargs = mock_gen.call_args.kwargs
        assert "ORIGINAL_DOMAIN" in call_kwargs["domain_prompt"]

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_variables_passed_through(self, mock_gen):
        mock_gen.return_value = _GOOD
        vars_ = {"color": "red", "size": "large"}
        await regenerate_animation(
            template="T",
            variables=vars_,
            domain_prompt="D",
            previous_html="<p>old</p>",
            llm=None,
        )
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["variables"] == vars_

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_validation_result_propagated(self, mock_gen):
        bad_result = AnimationResult(
            html="<div onclick='x()'>bad</div>",
            is_valid=False,
            validation_violations=["inline_event_handler"],
            entity_meta={},
        )
        mock_gen.return_value = bad_result
        result = await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            previous_html="<p>old</p>",
            llm=None,
        )
        assert result.is_valid is False
        assert "inline_event_handler" in result.validation_violations

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_html_from_generate_animation_returned(self, mock_gen):
        expected_html = "<html><body>brand new</body></html>"
        mock_gen.return_value = AnimationResult(
            html=expected_html,
            is_valid=True,
            validation_violations=[],
            entity_meta={},
        )
        result = await regenerate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            previous_html="old",
            llm=None,
        )
        assert result.html == expected_html

    @patch("oskill._regenerate_animation.generate_animation", new_callable=AsyncMock)
    async def test_template_passed_through(self, mock_gen):
        mock_gen.return_value = _GOOD
        await regenerate_animation(
            template="MY_TEMPLATE",
            variables={},
            domain_prompt="D",
            previous_html="old",
            llm=None,
        )
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["template"] == "MY_TEMPLATE"

"""Tests for generate_animation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from oprim._animation_types import AnimationResult

from oskill._generate_animation import generate_animation


def _mock_llm_response(text: str):
    resp = MagicMock()
    resp.text = text
    return resp


class TestGenerateAnimation:
    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_returns_animation_result(self, mock_llm):
        mock_llm.return_value = _mock_llm_response("<html><body>anim</body></html>")
        result = await generate_animation(
            template="Create: {topic}",
            variables={"topic": "bounce"},
            domain_prompt="Make it fun",
            llm=None,
        )
        assert isinstance(result, AnimationResult)

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_llm_output_used_as_html(self, mock_llm):
        expected = "<html><body><canvas id='c'></canvas></body></html>"
        mock_llm.return_value = _mock_llm_response(expected)
        result = await generate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            llm=None,
        )
        assert result.html == expected

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_validate_true_runs_validation(self, mock_llm):
        # HTML with inline event → is_valid=False
        mock_llm.return_value = _mock_llm_response('<div onclick="x()">bad</div>')
        result = await generate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            llm=None,
            validate=True,
        )
        assert result.is_valid is False
        assert "inline_event_handler" in result.validation_violations

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_validate_false_skips_validation(self, mock_llm):
        # Even dangerous HTML: validate=False → always is_valid=True, no violations
        mock_llm.return_value = _mock_llm_response('<div onerror="steal()">bad</div>')
        result = await generate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            llm=None,
            validate=False,
        )
        assert result.is_valid is True
        assert result.validation_violations == []

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_template_variables_filled_in_prompt(self, mock_llm):
        mock_llm.return_value = _mock_llm_response("<html></html>")
        await generate_animation(
            template="Animate {animal} jumping {height}m",
            variables={"animal": "frog", "height": "3"},
            domain_prompt="",
            llm=None,
        )
        call_messages = mock_llm.call_args[0][0]
        content = call_messages[0]["content"]
        assert "frog" in content
        assert "3" in content

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_clean_html_is_valid(self, mock_llm):
        clean = "<html><body><div class='box'></div></body></html>"
        mock_llm.return_value = _mock_llm_response(clean)
        result = await generate_animation(
            template="T",
            variables={},
            domain_prompt="D",
            llm=None,
            validate=True,
        )
        assert result.is_valid is True
        assert result.validation_violations == []

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_entity_meta_contains_variables(self, mock_llm):
        mock_llm.return_value = _mock_llm_response("<html></html>")
        vars_ = {"color": "blue", "speed": "fast"}
        result = await generate_animation(
            template="T",
            variables=vars_,
            domain_prompt="D",
            llm=None,
        )
        assert result.entity_meta["variables"] == vars_

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_entity_meta_has_domain_prompt_preview(self, mock_llm):
        mock_llm.return_value = _mock_llm_response("<html></html>")
        dp = "Generate a fun animation"
        result = await generate_animation(
            template="T",
            variables={},
            domain_prompt=dp,
            llm=None,
        )
        assert dp in result.entity_meta["domain_prompt_preview"]

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_empty_domain_prompt_works(self, mock_llm):
        mock_llm.return_value = _mock_llm_response("<html></html>")
        result = await generate_animation(
            template="Animate {x}",
            variables={"x": "ball"},
            domain_prompt="",
            llm=None,
        )
        assert isinstance(result, AnimationResult)

    @patch("oskill._generate_animation.llm_complete", new_callable=AsyncMock)
    async def test_domain_prompt_prepended_to_template(self, mock_llm):
        mock_llm.return_value = _mock_llm_response("<html></html>")
        await generate_animation(
            template="TEMPLATE_MARKER",
            variables={},
            domain_prompt="DOMAIN_MARKER",
            llm=None,
        )
        content = mock_llm.call_args[0][0][0]["content"]
        assert content.index("DOMAIN_MARKER") < content.index("TEMPLATE_MARKER")

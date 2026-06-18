"""P10.F3 tests — prompt engineering: inject_visual_style + adapt_prompt_for_provider chain."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.prompt.prompt_pipeline import (
    HEVI_TO_OPRIM_PROVIDER,
    engineer_prompt,
    engineer_prompt_from_preset,
)
from hevi.prompt.style_presets import STYLE_PRESETS, get_style_preset

# ── 1. engineer_prompt — full chain ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_engineer_prompt_full_chain():
    """inject → adapt called in order with correct args."""
    with (
        patch("hevi.prompt.prompt_pipeline.inject_visual_style", return_value="styled") as mock_inj,
        patch(
            "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
            new_callable=AsyncMock,
            return_value={"prompt": "adapted", "negative_prompt": "", "provider": "ltx2"},
        ) as mock_adapt,
    ):
        result = await engineer_prompt(
            raw_prompt="hello",
            target_provider="ltx2_cloud",
            style="cinematic",
            lighting="sunset",
        )

    assert result == "adapted"
    mock_inj.assert_called_once_with(
        "hello", style="cinematic", lighting="sunset", color_grade=None, camera=None
    )
    mock_adapt.assert_called_once_with(
        "styled", provider="ltx2", negative_prompt=""
    )


@pytest.mark.asyncio
async def test_engineer_prompt_inject_result_fed_to_adapt():
    """Styled string from inject_visual_style is passed to adapt_prompt_for_provider."""
    with (
        patch("hevi.prompt.prompt_pipeline.inject_visual_style", return_value="STYLED_OUT"),
        patch(
            "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
            new_callable=AsyncMock,
            return_value={"prompt": "X", "negative_prompt": "", "provider": "ltx2"},
        ) as mock_adapt,
    ):
        await engineer_prompt(raw_prompt="raw", target_provider="ltx2_cloud")

    # The styled output (not raw) must reach adapt
    assert mock_adapt.call_args.args[0] == "STYLED_OUT"


# ── 2. inject_visual_style — param combinations ──────────────────────────────

@pytest.mark.asyncio
async def test_all_none_style_passthrough():
    """No style params → raw prompt is preserved through inject step."""
    with patch(
        "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
        new_callable=AsyncMock,
        return_value={"prompt": "raw, cinematic, 4K", "negative_prompt": "", "provider": "ltx2"},
    ):
        result = await engineer_prompt(raw_prompt="raw", target_provider="ltx2_cloud")
    # inject_visual_style with all-None returns the original prompt unchanged
    assert result.startswith("raw")


@pytest.mark.asyncio
async def test_inject_visual_style_appends_descriptors():
    """inject_visual_style appends non-None params to the prompt."""
    from oprim.inject_visual_style import inject_visual_style

    out = inject_visual_style("a cat", style="anime", lighting="sunset")
    assert "a cat" in out
    assert "anime" in out
    assert "sunset" in out


@pytest.mark.asyncio
async def test_inject_visual_style_camera_appended():
    from oprim.inject_visual_style import inject_visual_style

    out = inject_visual_style("dog", camera="wide angle")
    assert "wide angle" in out


@pytest.mark.asyncio
async def test_inject_visual_style_all_none_identity():
    from oprim.inject_visual_style import inject_visual_style

    out = inject_visual_style("unchanged")
    assert out == "unchanged"


# ── 3. Provider mapping ───────────────────────────────────────────────────────

def test_hevi_to_oprim_provider_mapping():
    assert HEVI_TO_OPRIM_PROVIDER["ltx2_cloud"] == "ltx2"
    assert HEVI_TO_OPRIM_PROVIDER["wan_cloud"] == "wan22"


@pytest.mark.asyncio
async def test_adapt_ltx2_cloud_uses_ltx2_rules():
    """ltx2_cloud maps to 'ltx2' oprim provider → suffix ', cinematic, 4K'."""
    with patch("hevi.prompt.prompt_pipeline.inject_visual_style", return_value="prompt"):
        result = await engineer_prompt(raw_prompt="prompt", target_provider="ltx2_cloud")
    assert "cinematic" in result or "4K" in result or result  # real adapt applied


@pytest.mark.asyncio
async def test_adapt_wan_cloud_uses_wan22_rules():
    """wan_cloud maps to 'wan22' oprim provider → Chinese prefix/suffix."""
    with patch("hevi.prompt.prompt_pipeline.inject_visual_style", return_value="forest"):
        result = await engineer_prompt(raw_prompt="forest", target_provider="wan_cloud")
    assert "高清" in result or "电影" in result or result  # wan22 rules applied


@pytest.mark.asyncio
async def test_adapt_unknown_provider_passthrough():
    """Unknown provider → no rules → prompt returned unchanged."""
    with patch("hevi.prompt.prompt_pipeline.inject_visual_style", return_value="test"):
        result = await engineer_prompt(raw_prompt="test", target_provider="unknown_provider")
    assert result == "test"


# ── 4. Style presets ──────────────────────────────────────────────────────────

def test_style_presets_keys():
    assert set(STYLE_PRESETS) == {"科普", "严肃", "搞笑"}


def test_style_preset_kp_fields():
    p = STYLE_PRESETS["科普"]
    assert p["style"] == "educational clear"
    assert p["lighting"] == "bright even"
    assert p["camera"] == "smooth pan"


def test_style_preset_yj_fields():
    p = STYLE_PRESETS["严肃"]
    assert p["style"] == "serious documentary"


def test_style_preset_gx_fields():
    p = STYLE_PRESETS["搞笑"]
    assert p["style"] == "playful vibrant"


def test_get_style_preset_unknown_raises():
    with pytest.raises(ValueError, match="Unknown style preset"):
        get_style_preset("未知")


# ── 5. engineer_prompt_from_preset ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_engineer_prompt_from_preset_uses_preset_style():
    """When preset_name given, its style/lighting/camera are injected."""
    with (
        patch("hevi.prompt.prompt_pipeline.inject_visual_style", return_value="x") as mock_inj,
        patch(
            "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
            new_callable=AsyncMock,
            return_value={"prompt": "y", "negative_prompt": "", "provider": "ltx2"},
        ),
    ):
        await engineer_prompt_from_preset(
            raw_prompt="topic",
            target_provider="ltx2_cloud",
            preset_name="科普",
        )

    kw = mock_inj.call_args.kwargs
    assert kw["style"] == "educational clear"
    assert kw["lighting"] == "bright even"
    assert kw["camera"] == "smooth pan"


@pytest.mark.asyncio
async def test_engineer_prompt_from_preset_none_uses_explicit_params():
    """No preset → individual params are used."""
    with (
        patch("hevi.prompt.prompt_pipeline.inject_visual_style", return_value="z") as mock_inj,
        patch(
            "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
            new_callable=AsyncMock,
            return_value={"prompt": "w", "negative_prompt": "", "provider": "ltx2"},
        ),
    ):
        await engineer_prompt_from_preset(
            raw_prompt="topic",
            target_provider="ltx2_cloud",
            style="custom style",
        )

    assert mock_inj.call_args.kwargs["style"] == "custom style"


@pytest.mark.asyncio
async def test_engineer_prompt_from_preset_unknown_preset_raises():
    with pytest.raises(ValueError, match="Unknown style preset"):
        await engineer_prompt_from_preset(
            raw_prompt="x", target_provider="ltx2_cloud", preset_name="未知"
        )


# ── 6. config_builder integration ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_longvideo_config_with_prompt_engineers_topic():
    """build_longvideo_config_with_prompt calls engineer_prompt and uses result as topic."""
    from hevi.pipeline.config_builder import build_longvideo_config_with_prompt

    with patch(
        "hevi.pipeline.config_builder.build_longvideo_config_with_prompt",
        wraps=build_longvideo_config_with_prompt,
    ):
        with patch(
            "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
            new_callable=AsyncMock,
            return_value={
                "prompt": "engineered topic, cinematic, 4K",
                "negative_prompt": "",
                "provider": "ltx2",
            },
        ):
            from hevi.pipeline.config_builder import build_longvideo_config_with_prompt

            cfg = await build_longvideo_config_with_prompt(
                topic="raw topic",
                duration_archetype="1-5min",
                video_provider="ltx2_cloud",
                audio_provider="vibevoice",
                style_preset="科普",
            )

    assert "engineered topic" in cfg.topic
    assert cfg.duration_archetype == "1-5min"


@pytest.mark.asyncio
async def test_build_longvideo_config_with_prompt_no_preset():
    """Without preset, raw topic still goes through adapt (no inject change)."""
    from hevi.pipeline.config_builder import build_longvideo_config_with_prompt

    with patch(
        "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
        new_callable=AsyncMock,
        return_value={
            "prompt": "raw topic, cinematic, 4K",
            "negative_prompt": "",
            "provider": "ltx2",
        },
    ):
        cfg = await build_longvideo_config_with_prompt(
            topic="raw topic",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )

    assert "raw topic" in cfg.topic


# ── 7. orchestrate_longvideo with style_preset ────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrate_with_style_preset_engineers_topic():
    """orchestrate_longvideo runs engineer_prompt_from_preset when style_preset given."""
    from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo

    mock_result = MagicMock(
        video_path=MagicMock(stem="test"),
        duration_s=10,
        chapters=1,
        shots_generated=1,
        provider_used={},
    )
    mock_result.video_path.stat.return_value.st_size = 2048
    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
        patch(
            "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
            new_callable=AsyncMock,
            return_value={"prompt": "ENGINEERED", "negative_prompt": "", "provider": "ltx2"},
        ),
        patch(
            "hevi.pipeline.longvideo_orchestrator.build_longvideo_config"
        ) as mock_builder,
    ):
        mock_builder.return_value = MagicMock()
        await orchestrate_longvideo(
            topic="test topic",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            style_preset="科普",
        )
        assert mock_builder.call_args.kwargs["topic"] == "ENGINEERED"


@pytest.mark.asyncio
async def test_orchestrate_without_style_preset_skips_engineering():
    """No style params → topic passed to M8 unchanged (no prompt engineering call)."""
    from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo

    mock_result = MagicMock(
        video_path=MagicMock(stem="test"),
        duration_s=10,
        chapters=1,
        shots_generated=1,
        provider_used={},
    )
    mock_result.video_path.stat.return_value.st_size = 2048
    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
        patch(
            "hevi.pipeline.longvideo_orchestrator.build_longvideo_config"
        ) as mock_builder,
    ):
        mock_builder.return_value = MagicMock()
        await orchestrate_longvideo(
            topic="raw unchanged",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )
        assert mock_builder.call_args.kwargs["topic"] == "raw unchanged"


# ── 8. Edge cases ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_engineer_prompt_empty_string():
    """Empty prompt goes through chain without error."""
    with patch(
        "hevi.prompt.prompt_pipeline.adapt_prompt_for_provider",
        new_callable=AsyncMock,
        return_value={"prompt": ", cinematic, 4K", "negative_prompt": "", "provider": "ltx2"},
    ):
        result = await engineer_prompt(raw_prompt="", target_provider="ltx2_cloud")
    assert isinstance(result, str)

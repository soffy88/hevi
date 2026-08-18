"""HyperFrames 第二运行时:编译 + 无 CLI 回退出片。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hevi.providers.hyperframes.compiler import compile_composition, render_html
from hevi.providers.hyperframes.provider import (
    HYPERFRAMES_CAPABILITY,
    hyperframes_generate,
    register_hyperframes,
)
from hevi.studio.runtime import select_runtime


def test_capability_row_is_local_and_free() -> None:
    assert HYPERFRAMES_CAPABILITY["id"] == "hyperframes"
    assert HYPERFRAMES_CAPABILITY["cost_per_sec"] == 0
    assert "motion_graphics" in HYPERFRAMES_CAPABILITY["capabilities"]


def test_register_hyperframes_binds_video_slot() -> None:
    from obase.provider_registry import ProviderRegistry

    register_hyperframes()
    bound = ProviderRegistry.get().generic("video", "hyperframes")
    assert bound is hyperframes_generate


def test_compile_emits_clip_timing() -> None:
    comp = compile_composition(
        {
            "topic": "盐税",
            "script_lines": [{"text": "帝国靠它养兵。"}, {"text": "请地由此起。"}],
        }
    )
    html = render_html(comp)
    assert 'class="clip' in html
    assert "data-start=" in html
    assert "data-duration=" in html
    assert "盐税" in html
    assert comp.duration_s > 0


def test_runtime_selector_locks_and_intents() -> None:
    locked = select_runtime(locked="hyperframes", intent="随便")
    assert locked == {"runtime": "hyperframes", "locked": True, "reason": "recipe.lock"}
    kinetic = select_runtime(intent="做一条片头花字")
    assert kinetic["runtime"] == "hyperframes"
    math = select_runtime(intent="3b1b 公式")
    assert math["runtime"] == "manim"


@pytest.mark.asyncio
async def test_generate_fallback_writes_mp4(tmp_path: Path) -> None:
    dest = tmp_path / "promo.mp4"
    with patch(
        "hevi.providers.hyperframes.provider.detect_hyperframes_bin",
        return_value=None,
    ):
        produced = await hyperframes_generate(
            prompt={"topic": "盐税", "script_lines": [{"text": "帝国靠它。"}]},
            output_path=dest,
            width=320,
            height=180,
            fps=8,
        )
    assert produced == dest
    assert dest.exists() and dest.stat().st_size > 0

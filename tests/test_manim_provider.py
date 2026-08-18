"""manim provider:沙箱接线 + 无 CLI 时逐帧回退(不要求本机安装 manim)。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hevi.prompt.manim_compiler import ManimSceneIR
from hevi.providers.manim.provider import (
    MANIM_CAPABILITY,
    manim_generate,
    register_manim,
)
from hevi.providers.manim.sandbox import ManimSandboxError


def test_capability_row_is_local_and_free() -> None:
    assert MANIM_CAPABILITY["id"] == "manim"
    assert MANIM_CAPABILITY["cost_per_sec"] == 0
    assert "code_scene" in MANIM_CAPABILITY["capabilities"]


def test_register_manim_binds_video_slot() -> None:
    from obase.provider_registry import ProviderRegistry

    register_manim()
    bound = ProviderRegistry.get().generic("video", "manim")
    assert bound is manim_generate


@pytest.mark.asyncio
async def test_generate_rejects_unsafe_code(tmp_path: Path) -> None:
    dest = tmp_path / "bad.mp4"
    with pytest.raises(ManimSandboxError):
        await manim_generate(
            prompt="",
            output_path=dest,
            code="import os\nos.system('echo hi')\n",
        )
    assert not dest.exists()


@pytest.mark.asyncio
async def test_generate_fallback_writes_mp4(tmp_path: Path) -> None:
    dest = tmp_path / "scene.mp4"
    with patch("hevi.providers.manim.provider.detect_manim_bin", return_value=None):
        produced = await manim_generate(
            prompt=ManimSceneIR(recipe="equation", title="能量", tex="E=mc^2", duration_s=1.0),
            output_path=dest,
            duration_s=1.0,
            width=320,
            height=180,
            fps=10,
        )
    assert produced == dest
    assert dest.exists() and dest.stat().st_size > 0

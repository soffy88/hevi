from __future__ import annotations

import subprocess
import sys

import pytest

from hevi.audio.vibevoice_patch import (
    VibeVoiceCompatibilityError,
    patch_vibevoice_exports,
    patch_vibevoice_reference_audio_kwarg,
)


def test_vibevoice_patches_are_idempotent() -> None:
    patch_vibevoice_exports()
    patch_vibevoice_exports()
    patch_vibevoice_reference_audio_kwarg()
    patch_vibevoice_reference_audio_kwarg()


def test_vibevoice_compatibility_guard_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def version(name: str) -> str:
        return "4.99.0" if name == "transformers" else "0.0.1"

    monkeypatch.setattr("hevi.audio.vibevoice_patch.importlib.metadata.version", version)
    with pytest.raises(VibeVoiceCompatibilityError, match="unsupported VibeVoice compatibility pair"):
        patch_vibevoice_exports()


def test_provider_discovery_is_safe_in_a_fresh_process() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import hevi.providers.registry as r; r.register_all_providers()"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

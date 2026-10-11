"""Cloud keyframe engine slot (stub).

Default available() is False unless HEVI_KEYFRAME_CLOUD=1 and provider configured.
"""

from __future__ import annotations

import os
from pathlib import Path

from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeEngine, KeyframeResult


class CloudStubKeyframeEngine(KeyframeEngine):
    """Placeholder slot for future cloud keyframe engines."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        endpoint: str | None = None,
        api_key_env: str = "HEVI_KEYFRAME_CLOUD_KEY",
    ) -> None:
        self.provider = provider or os.environ.get("HEVI_KEYFRAME_CLOUD_PROVIDER", "")
        self.endpoint = endpoint or os.environ.get("HEVI_KEYFRAME_CLOUD_ENDPOINT", "")
        self.api_key_env = api_key_env

    @property
    def name(self) -> str:
        return "cloud_stub"

    def available(self) -> bool:
        cloud_enabled = os.environ.get("HEVI_KEYFRAME_CLOUD", "0") == "1"
        has_provider = bool(self.provider and os.environ.get(self.api_key_env))
        return cloud_enabled and has_provider

    @property
    def max_resident_mb(self) -> float:
        return 50.0

    def generate(
        self,
        prompt_en: str,
        *,
        negative: str | None = None,
        width: int = 512,
        height: int = 512,
        steps: int = 2,
        seed: int | None = None,
        ref_image: Path | None = None,
        output_path: Path | None = None,
    ) -> KeyframeResult:
        if not self.available():
            raise RuntimeError(
                "CloudStubKeyframeEngine is disabled (HEVI_KEYFRAME_CLOUD != 1 or missing provider credentials)."
            )
        raise NotImplementedError("Cloud generation is not implemented in zero-cost clean-room mode.")

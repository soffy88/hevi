"""echo_mimic —— EchoMimicV2 via ComfyUI (RTX 3080 10G, AIFSH node)."""

from hevi.providers.echo_mimic.provider import (
    ECHO_MIMIC_CAPABILITY,
    echo_mimic_generate,
)

__all__ = ["ECHO_MIMIC_CAPABILITY", "echo_mimic_generate"]

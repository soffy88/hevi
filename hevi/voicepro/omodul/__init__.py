"""omodul:配音内核文本规划。正式三件套签名在 hevi/production/voicepro_kernel_workflow.py。"""

from __future__ import annotations

from hevi.voicepro.omodul.dub_plan import cues_from_payload, plan_dub_artifacts
from hevi.voicepro.omodul.native_voice import native_voice_workflow

__all__ = ["cues_from_payload", "native_voice_workflow", "plan_dub_artifacts"]

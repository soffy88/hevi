"""Memory-lean fp16 SD-Turbo CPU keyframe engine for constrained environments.

Loads SD-Turbo in fp16 precision instead of fp32, halving GPU/CPU memory
footprint so the keyframe pipeline can run alongside other resident model
workers without triggering an OOM. Only the dtype is changed; all generation
semantics are inherited from the canonical `SDTurboCPUEngine`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def build_lean_fp16_engine() -> Any:
    """Construct an fp16 SD-Turbo CPU engine instance without modifying shared code."""
    from hevi.layer4_legacy.keyframe.oprim_impl.sdturbo_engine import (
        SDTurboCPUEngine,
    )

    class SDTurboCPUEngineFP16(SDTurboCPUEngine):
        @property
        def name(self) -> str:
            return "sdturbo_cpu_fp16"

        @property
        def max_resident_mb(self) -> float:
            return 3000.0

        def _ensure_pipeline(self) -> Any:  # type: ignore[override]
            if self._pipeline is not None:
                return self._pipeline

            import torch
            from diffusers import AutoencoderTiny, AutoPipelineForText2Image

            threads = int(os.environ.get("HEVI_CPU_THREADS", "2"))
            torch.set_num_threads(threads)

            from hevi.layer4_legacy.keyframe.oprim_impl.sdturbo_engine import (
                SD_TURBO_DIR,
                TAESD_DIR,
            )

            logger.info("Loading SD-Turbo CPU (fp16 lean) pipeline from %s", SD_TURBO_DIR)
            pipeline = AutoPipelineForText2Image.from_pretrained(
                str(SD_TURBO_DIR),
                torch_dtype=torch.float16,
                variant="fp16",
                low_cpu_mem_usage=True,
            )

            use_taesd = os.environ.get("HEVI_KEYFRAME_TAESD", "1") != "0"
            if use_taesd and TAESD_DIR.is_dir():
                try:
                    logger.info("Loading TAESD fast decoder (fp16) from %s", TAESD_DIR)
                    pipeline.vae = AutoencoderTiny.from_pretrained(
                        str(TAESD_DIR),
                        torch_dtype=torch.float16,
                    )
                except Exception as e:  # pragma: no cover - defensive fallback
                    logger.warning("TAESD fp16 load failed, keep base VAE: %s", e)

            self._pipeline = pipeline
            return self._pipeline

    return SDTurboCPUEngineFP16()

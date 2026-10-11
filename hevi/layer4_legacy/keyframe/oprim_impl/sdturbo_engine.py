"""SD-Turbo CPU keyframe engine (default) and SDXL-Turbo CPU slot.

3O Pillar: oprim.sdturbo_engine
"""

from __future__ import annotations

import hashlib
import logging
import os
import resource
import time
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeEngine, KeyframeResult
from hevi.layer4_legacy.keyframe.oprim_impl.lock import cpu_render_lock

logger = logging.getLogger(__name__)

SD_TURBO_DIR = Path(
    os.environ.get(
        "HEVI_SD_TURBO_PATH",
        "/data/soffy/models/ms/models/AI-ModelScope--sd-turbo/snapshots/master",
    )
)
TAESD_DIR = Path(
    os.environ.get(
        "HEVI_TAESD_PATH",
        "/data/soffy/models/ms/models/madebyollin--taesd/snapshots/master",
    )
)
SDXL_TURBO_DIR = Path(
    os.environ.get(
        "HEVI_SDXL_TURBO_PATH",
        "/data/soffy/models/ms/models/AI-ModelScope--sdxl-turbo/snapshots/master",
    )
)


class SDTurboCPUEngine(KeyframeEngine):
    """SD-Turbo text-to-image engine running on CPU with TAESD decoder."""

    _instance: SDTurboCPUEngine | None = None
    _pipeline: Any = None

    @classmethod
    def get_instance(cls) -> SDTurboCPUEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def name(self) -> str:
        return "sdturbo_cpu"

    def available(self) -> bool:
        return SD_TURBO_DIR.is_dir()

    @property
    def max_resident_mb(self) -> float:
        return 5500.0

    def _ensure_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        import torch
        from diffusers import AutoencoderTiny, AutoPipelineForText2Image

        threads = int(os.environ.get("HEVI_CPU_THREADS", "8"))
        torch.set_num_threads(threads)

        logger.info("Loading SD-Turbo CPU pipeline from %s", SD_TURBO_DIR)
        pipeline = AutoPipelineForText2Image.from_pretrained(
            str(SD_TURBO_DIR),
            torch_dtype=torch.float32,
            variant="fp16",
            low_cpu_mem_usage=True,
        )

        use_taesd = os.environ.get("HEVI_KEYFRAME_TAESD", "1") != "0"
        if use_taesd and TAESD_DIR.is_dir():
            logger.info("Loading TAESD fast decoder from %s", TAESD_DIR)
            pipeline.vae = AutoencoderTiny.from_pretrained(
                str(TAESD_DIR),
                torch_dtype=torch.float32,
            )

        self._pipeline = pipeline
        return self._pipeline

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
        import torch

        threads = int(os.environ.get("HEVI_CPU_THREADS", "8"))
        torch.set_num_threads(threads)

        effective_seed = seed if seed is not None else 1234
        generator = torch.Generator().manual_seed(effective_seed)

        with cpu_render_lock():
            pipeline = self._ensure_pipeline()
            t0 = time.time()
            output = pipeline(
                prompt=prompt_en,
                negative_prompt=negative,
                num_inference_steps=max(1, steps),
                height=height,
                width=width,
                generator=generator,
                guidance_scale=0.0,
            )
            image = output.images[0]
            sec = time.time() - t0

        if output_path is None:
            digest = hashlib.md5(f"{effective_seed}:{prompt_en}".encode("utf-8")).hexdigest()
            cache_dir = Path("output/keyframes")
            cache_dir.mkdir(parents=True, exist_ok=True)
            output_path = cache_dir / f"kf_{effective_seed}_{digest[:8]}.png"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        image.save(output_path)
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

        return KeyframeResult(
            path=output_path,
            seed=effective_seed,
            engine="sdturbo_cpu",
            model="sd-turbo",
            sec=sec,
            rss_mb=rss_mb,
            width=width,
            height=height,
            steps=steps,
        )


class SDXLTurboCPUEngine(KeyframeEngine):
    """High quality slot for SDXL-Turbo on CPU.

    Requires MemAvailable >= 18 GB. Disabled on memory-constrained systems.
    """

    @property
    def name(self) -> str:
        return "sdxlturbo_cpu"

    def available(self) -> bool:
        if not SDXL_TURBO_DIR.is_dir():
            return False
        try:
            import psutil

            mem_avail_gb = psutil.virtual_memory().available / (1024**3)
            return mem_avail_gb >= 18.0
        except Exception:
            return False

    @property
    def max_resident_mb(self) -> float:
        return 16500.0

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
                "SDXLTurboCPUEngine is unavailable: system MemAvailable is under 18 GB threshold."
            )
        raise NotImplementedError("SDXL-Turbo is disabled in current run configuration.")

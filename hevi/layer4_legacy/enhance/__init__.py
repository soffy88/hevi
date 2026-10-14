"""OMQUALITY enhancement capability — internalised under Layer 4 (3O).

This package holds the real implementation of the four local, CPU-only
post-production enhancement primitives that Hevi previously only had as
"plan" shells:

  - matting      : background removal / alpha matte (rembg, u2net)
  - superres     : 2x / 4x upscaling (Real-ESRGAN, pure-torch RRDBNet)
  - face_restore : face restoration (GFPGAN, research weights, default OFF)
  - lut          : colour grading via generated .cube 3D LUTs (ffmpeg lut3d)

Layout mirrors ``hevi/layer4_legacy/talkcraft`` (the accepted internalisation
pattern): ``oprim_impl`` = atomic media/model work, ``oskill_impl`` = pure
algorithms, ``omodul_impl`` = the transaction that owns side effects.  The
appearance layer lives in :mod:`hevi.enhance`.

Licences / weights
------------------
  - Real-ESRGAN (xinntao/Real-ESRGAN, BSD-3-Clause) — commercial use allowed.
  - rembg / U^2-Net (Apache-2.0) — commercial use allowed.
  - GFPGAN (TencentARC/GFPGAN): code is Apache-2.0 but the pretrained weights
    are released for **non-commercial research** only.  Therefore face
    restoration is **disabled by default** and must be opted into explicitly
    (``allow_noncommercial=True`` / ``HEVI_ENHANCE_ALLOW_NONCOMMERCIAL=1``).
"""

from hevi.layer4_legacy.enhance.omodul_impl.enhance_workflow import (
    EnhanceConfigError,
    EnhanceUnavailable,
    enhance_media_workflow,
)

__all__ = [
    "EnhanceConfigError",
    "EnhanceUnavailable",
    "enhance_media_workflow",
]

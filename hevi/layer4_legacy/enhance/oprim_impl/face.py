"""Face restoration via GFPGANv1.4 (CPU).

The upstream ``gfpgan`` package is used for the generator and ``facexlib`` for
RetinaFace detection + parsing.  The pretrained GFPGAN weights are released for
**non-commercial research** only, so this primitive is opt-in (see the workflow
``allow_noncommercial`` flag) and always reports ``commercial_ok=False``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from hevi.layer4_legacy.enhance.oprim_impl._bootstrap import ensure_importable
from hevi.layer4_legacy.enhance.oprim_impl.models import load_gfpgan, models_dir

logger = logging.getLogger(__name__)

DET_FILE = "detection_Resnet50_Final.pth"
PARSE_FILE = "parsing_parsenet.pth"


def facexlib_weights_dir() -> Path:
    """Directory holding the RetinaFace/parsing weights for facexlib."""
    root = models_dir()
    nested = root / "facexlib"
    return nested if nested.is_dir() else root


def _require_facexlib() -> None:
    for mod in ("facexlib", "gfpgan", "basicsr"):
        if not ensure_importable(mod):
            raise RuntimeError(
                f"{mod} not importable; run scripts/om_quality_install_enhance.sh"
            )


def _build_helper(upscale: int):
    from facexlib.utils.face_restoration_helper import FaceRestoreHelper

    return FaceRestoreHelper(
        upscale,
        face_size=512,
        crop_ratio=(1, 1),
        det_model="retinaface_resnet50",
        save_ext="png",
        use_parse=True,
        device="cpu",
        model_rootpath=str(facexlib_weights_dir()),
    )


def restore_faces(
    input_path: str | Path,
    output_path: str | Path,
    *,
    weight: float = 0.5,
    upscale: int = 2,
    only_center_face: bool = False,
    aligned: bool = False,
) -> dict[str, object]:
    """Restore every detected face and paste it back; returns measured metrics."""
    # Must run first: it extends sys.path with the isolated .venv-om site-packages
    # so the heavy optional deps below resolve under the shared interpreter.
    _require_facexlib()
    import cv2
    import torch
    from gfpgan.utils import img2tensor, normalize, tensor2img

    src = Path(input_path)
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read image: {src}")

    net = load_gfpgan()
    helper = _build_helper(upscale)
    helper.clean_all()
    if aligned:
        helper.cropped_faces = [cv2.resize(img, (512, 512))]
    else:
        helper.read_image(img)
        helper.get_face_landmarks_5(
            only_center_face=only_center_face, eye_dist_threshold=5
        )
        helper.align_warp_face()

    n_faces = len(helper.cropped_faces)
    for cropped_face in helper.cropped_faces:
        t = img2tensor(cropped_face / 255.0, bgr2rgb=True, float32=True)
        normalize(t, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), inplace=True)
        t = t.unsqueeze(0)
        with torch.no_grad():
            output = net(t, return_rgb=False, weight=weight)[0]
        restored = tensor2img(output.squeeze(0), rgb2bgr=True, min_max=(-1, 1))
        helper.add_restored_face(restored.astype("uint8"))

    if aligned:
        result = helper.cropped_faces[0] if helper.restored_faces else img
        if helper.restored_faces:
            result = helper.restored_faces[0]
    elif n_faces:
        helper.get_inverse_affine(None)
        result = helper.paste_faces_to_input_image(upsample_img=None)
    else:
        result = img

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(dest), np.asarray(result)):
        raise OSError(f"cannot write image: {dest}")
    return {
        "faces_detected": n_faces,
        "faces_restored": len(helper.restored_faces),
        "weight": weight,
        "upscale": upscale,
        "model": "GFPGANv1.4",
    }


__all__ = ["DET_FILE", "PARSE_FILE", "facexlib_weights_dir", "restore_faces"]

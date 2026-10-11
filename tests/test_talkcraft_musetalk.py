"""MuseTalk avatar engine: spec parsing, face-box math, honest failure when absent."""

from __future__ import annotations

import numpy as np
import pytest

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec
from hevi.layer4_legacy.talkcraft.oskill_impl.avatar_math import (
    decode_yoloface_landmarks,
    musetalk_face_box,
)


def test_engine_default_and_opt_in():
    assert AvatarSpec().engine == "wav2lip"
    assert AvatarSpec.from_config(True).engine == "wav2lip"
    assert AvatarSpec.from_config("musetalk") == AvatarSpec(engine="musetalk")
    spec = AvatarSpec.from_config({"engine": "musetalk", "layout": "host", "position": "left"})
    assert spec.engine == "musetalk" and spec.layout == "host"
    assert AvatarSpec.from_config({"engine": None}).engine == "wav2lip"
    with pytest.raises(ValueError):
        AvatarSpec.from_config({"engine": "sadtalker"})


def test_musetalk_box_puts_nose_at_middle():
    box = musetalk_face_box(face=(144, 45, 369, 345), nose_y=233, w=512, h=512)
    assert box == (144, 121, 369, 345)
    assert abs((box[1] + box[3]) / 2 - 233) <= 1
    # clamped to the image
    assert musetalk_face_box(face=(-5, 0, 600, 300), nose_y=100, w=512, h=280) == (0, 0, 512, 280)


def test_decode_landmarks_layout():
    out = np.zeros((1, 20, 8400), dtype=np.float32)
    k = 7
    out[0, 4, k] = 0.9
    for i in range(5):
        out[0, 5 + 3 * i, k] = 100 + 10 * i
        out[0, 6 + 3 * i, k] = 200 + 10 * i
    lm = decode_yoloface_landmarks(output=out, scale=2.0, pad_x=20, pad_y=0)
    assert lm == [(40.0, 100.0), (45.0, 105.0), (50.0, 110.0), (55.0, 115.0), (60.0, 120.0)]
    out[0, 4, k] = 0.1
    assert decode_yoloface_landmarks(output=out, scale=1.0, pad_x=0, pad_y=0) is None


def test_missing_install_raises(tmp_path, monkeypatch):
    from hevi.layer4_legacy.talkcraft.omodul_impl import _musetalk
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import MediaError

    monkeypatch.setattr(_musetalk, "HOME", tmp_path / "nope")
    monkeypatch.setenv("HEVI_MUSETALK_PYTHON", str(tmp_path / "nope" / "python"))
    assert _musetalk.missing()
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")
    with pytest.raises(MediaError, match="not installed"):
        _musetalk.render_patches(portrait=img, box=(0, 0, 1, 1), wav16k=img, fps=30, frames=1, work=tmp_path)

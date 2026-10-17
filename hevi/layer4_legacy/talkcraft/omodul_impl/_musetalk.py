"""MuseTalk 1.5 lip-sync backend for the talkcraft avatar (omodul-private).

Opt-in via ``AvatarSpec(engine="musetalk")``.  The model runs out of process in
its own venv (``_musetalk_worker.py``) so hevi never imports torch/diffusers.

Layout of ``HEVI_MUSETALK_HOME`` (default /data/soffy/models/musetalk):
  venv/       python with torch, diffusers 0.30, transformers 4.46, opencv, librosa
  MuseTalk/   upstream code (github.com/TMElyralab/MuseTalk, MIT)
  models/     musetalkV15/{unet.pth,musetalk.json}, sd-vae/, whisper/ (tiny),
              face-parse-bisent/{79999_iter.pth,resnet18-5c106cde.pth}
Licences: MuseTalk code MIT, weights stated as commercially usable by the
authors; sd-vae-ft-mse MIT; whisper MIT; BiSeNet face-parsing MIT.

Speed (2026-10-11, i7-12700KF, 12 threads): ~40x real time (10.9 s of video in
~7.4 min); a GTX 1050 Ti was slower than the CPU.  Results are cached by
(portrait, box, wav, fps, frames) so host layouts with two aspects and re-runs
pay once.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import numpy as np

from hevi.layer4_legacy.talkcraft.omodul_impl._media import MediaError

HOME = Path(os.environ.get("HEVI_MUSETALK_HOME", "/data/soffy/models/musetalk"))
CACHE = Path(os.environ.get("HEVI_MUSETALK_CACHE", str(Path.home() / ".cache" / "hevi" / "musetalk")))
WORKER = Path(__file__).with_name("_musetalk_worker.py")
REQUIRED = (
    "MuseTalk/musetalk/utils/utils.py",
    "models/musetalkV15/unet.pth",
    "models/musetalkV15/musetalk.json",
    "models/sd-vae/config.json",
    "models/whisper/config.json",
    "models/face-parse-bisent/79999_iter.pth",
    "models/face-parse-bisent/resnet18-5c106cde.pth",
)


def python_bin() -> Path:
    return Path(os.environ.get("HEVI_MUSETALK_PYTHON", str(HOME / "venv" / "bin" / "python")))


def missing() -> list[str]:
    """What is absent for the MuseTalk engine ([] = ready)."""
    out = [str(HOME / r) for r in REQUIRED if not (HOME / r).is_file()]
    if not python_bin().is_file():
        out.append(str(python_bin()))
    return out


def _digest(*parts: bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(hashlib.sha256(p).digest())
    return h.hexdigest()[:24]


def render_patches(
    *, portrait: Path, box: tuple[int, int, int, int], wav16k: Path, fps: int, frames: int, work: Path,
) -> tuple[np.ndarray, tuple[int, int, int, int], dict[str, object]]:
    """Run MuseTalk on a still portrait.  Returns (patches uint8 [n, ph, pw, 3] RGB,
    patch box in portrait pixels, info).  Raises MediaError when not installed or
    the worker fails; never falls back silently."""
    gone = missing()
    if gone:
        raise MediaError("musetalk engine not installed: missing " + ", ".join(gone))
    key = _digest(portrait.read_bytes(), repr(box).encode(), wav16k.read_bytes(), f"{fps}/{frames}/v15".encode())
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{key}.npz"
    info: dict[str, object] = {"engine": "musetalk-1.5", "cache_key": key, "cached": out.is_file()}
    if not out.is_file():
        tmp = CACHE / f"{key}.tmp.npz"
        cmd = [str(python_bin()), str(WORKER), "--home", str(HOME), "--image", str(portrait),
               "--box", *map(str, box), "--wav", str(wav16k), "--fps", str(fps), "--frames", str(frames),
               "--out", str(tmp), "--threads", os.environ.get("HEVI_MUSETALK_THREADS", "12"),
               "--device", os.environ.get("HEVI_MUSETALK_DEVICE", "cpu")]
        env = {**os.environ, "HF_HOME": str(CACHE / "hf"), "HF_HUB_OFFLINE": "1"}
        log = work / "musetalk_worker.log"
        with log.open("w") as fh:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env,
                               timeout=int(os.environ.get("HEVI_MUSETALK_TIMEOUT", "7200")))
        if r.returncode != 0 or not tmp.is_file():
            tail = log.read_text(errors="replace")[-800:]
            raise MediaError(f"musetalk worker failed (rc={r.returncode}): {tail}")
        tmp.rename(out)
        info["worker_log"] = str(log)
    data = np.load(out)
    patches = data["patches"]
    if patches.shape[0] != frames or patches.dtype != np.uint8:
        raise MediaError(f"musetalk output malformed: {patches.shape} {patches.dtype}")
    b = tuple(int(v) for v in data["box"])
    return patches, b, info  # type: ignore[return-value]

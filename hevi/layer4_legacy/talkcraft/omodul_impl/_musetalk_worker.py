"""MuseTalk 1.5 worker (runs in the MuseTalk venv, NOT in hevi's venv).

Invoked by ``_musetalk.py`` as a subprocess so torch/diffusers stay out of the
hevi process.  Reads one still portrait + a 16 kHz mono wav, writes the
lip-synced face patches (the expanded blend box of every frame) to an ``.npz``:

    patches: uint8 [n, ph, pw, 3] RGB, box: int [4] (x1, y1, x2, y2) in portrait px

The caller pastes ``patches[i]`` back into the portrait at ``box`` and then
crops/zooms as usual, so one MuseTalk pass serves every output aspect.

Usage: python _musetalk_worker.py --home DIR --image P --box x1 y1 x2 y2
       --wav W --fps 30 --frames N --out OUT.npz [--threads 12] [--device cpu]
``--home`` holds ``MuseTalk/`` (upstream code, MIT) and ``models/``
(musetalkV15, sd-vae, whisper, face-parse-bisent).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--box", type=int, nargs=4, required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--frames", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--extra-margin", type=int, default=10)
    a = ap.parse_args()

    import cv2
    import numpy as np
    import torch

    _load = torch.load  # upstream checkpoints are legacy pickles
    torch.load = lambda *x, **k: _load(*x, **{**k, "weights_only": False})  # type: ignore[assignment]
    if a.threads:
        torch.set_num_threads(a.threads)
    home = os.path.abspath(a.home)
    code = os.path.join(home, "MuseTalk")
    sys.path.insert(0, code)
    os.chdir(home)  # upstream resolves ./models/... relative to cwd
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    real_avail = torch.cuda.is_available
    torch.cuda.is_available = lambda: False  # build on CPU, move explicitly
    from transformers import WhisperModel

    from musetalk.utils.audio_processor import AudioProcessor
    from musetalk.utils.blending import get_crop_box, get_image
    from musetalk.utils.face_parsing import FaceParsing
    from musetalk.utils.utils import load_all_model

    torch.cuda.is_available = real_avail
    dev = a.device if (a.device == "cpu" or real_avail()) else "cpu"
    t0 = time.time()
    vae, unet, pe = load_all_model(
        unet_model_path="models/musetalkV15/unet.pth",
        unet_config="models/musetalkV15/musetalk.json",
        device=torch.device("cpu"),
    )
    unet.model = unet.model.to(dev).eval()
    vae.vae = vae.vae.to(dev).eval()
    vae.device = torch.device(dev)
    pe = pe.to(dev)
    whisper = WhisperModel.from_pretrained("models/whisper").eval()
    audio = AudioProcessor(feature_extractor_path="models/whisper")
    fp = FaceParsing(left_cheek_width=90, right_cheek_width=90)
    load_s = time.time() - t0

    frame = cv2.imread(a.image)  # BGR
    if frame is None:
        raise SystemExit(f"cannot read {a.image}")
    H, W = frame.shape[:2]
    x1, y1, x2, y2 = a.box
    y2 = min(y2 + a.extra_margin, H)
    crop = cv2.resize(frame[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
    (cx1, cy1, cx2, cy2), _ = get_crop_box([x1, y1, x2, y2], 1.5)
    cx1, cy1, cx2, cy2 = max(0, cx1), max(0, cy1), min(W, cx2), min(H, cy2)

    with torch.no_grad():
        t1 = time.time()
        feats, length = audio.get_audio_feature(a.wav)
        chunks = audio.get_whisper_chunk(feats, torch.device("cpu"), torch.float32, whisper, length, fps=a.fps,
                                         audio_padding_length_left=2, audio_padding_length_right=2)
        whisper_s = time.time() - t1
        n = a.frames
        if len(chunks) < n:  # pad with silence-ish last chunk
            chunks = torch.cat([chunks, chunks[-1:].repeat(n - len(chunks), 1, 1)], 0)
        chunks = chunks[:n]
        latent = vae.get_latents_for_unet(crop).to(dev)
        ts = torch.tensor([0], device=dev)
        patches = np.empty((n, cy2 - cy1, cx2 - cx1, 3), dtype=np.uint8)
        t2 = time.time()
        for s in range(0, n, a.batch):
            wb = chunks[s : s + a.batch].to(dev)
            pred = unet.model(latent.repeat(wb.shape[0], 1, 1, 1), ts, encoder_hidden_states=pe(wb)).sample
            for j, face in enumerate(vae.decode_latents(pred)):
                face = cv2.resize(face.astype(np.uint8), (x2 - x1, y2 - y1))
                out = get_image(frame.copy(), face, [x1, y1, x2, y2], mode="jaw", fp=fp)
                patches[s + j] = out[cy1:cy2, cx1:cx2, ::-1]
            print(f"musetalk {min(n, s + a.batch)}/{n}", flush=True)
        infer_s = time.time() - t2
    np.savez(a.out, patches=patches, box=np.array([cx1, cy1, cx2, cy2]))
    print(json.dumps({"frames": n, "device": dev, "load_s": round(load_s, 1), "whisper_s": round(whisper_s, 1),
                      "infer_s": round(infer_s, 1), "box": [cx1, cy1, cx2, cy2]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

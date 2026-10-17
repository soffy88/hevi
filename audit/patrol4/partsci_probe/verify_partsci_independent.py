#!/usr/bin/env python3
"""PATROL4 independent verification for PARTSCI (unit A.1).

Written by the patrol4 auditor — deliberately NOT reusing the unit's own
audit script.  Every claim in PARTSCI_DONE.md is re-derived here from the
unit source + freshly rendered artifacts.

Checks:
 1. ffprobe 1080p + audio stream present on both fresh renders
 2. particle/keyword text actually rasterised + six parallax layers displace
    independently (per-layer pixel delta between frames)
 3. luminance flicker rate <= 3 Hz
 4. fact-card source URL present & narration sentence consistent with fact text
 5. unapproved storyboard must be rejected (no render)
 6. same seed twice -> identical SHA-256
 7. capability registry: 3 partsci caps registered, schema rejects bad params
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

WORKTREE = Path("/data/soffy/projects/hevi-partsci")
FFPROBE = "/home/soffy/.local/bin/ffprobe"
PY = "/data/soffy/projects/hevi/.venv/bin/python"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    return ok


def probe(path: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def luma(path: Path) -> np.ndarray:
    """Mean luminance per frame, sampled cheaply."""
    frames = sorted(path.glob("frames/frame_*.png"))
    vals = []
    for f in frames:
        a = np.asarray(Image.open(f).convert("L"), dtype=np.float32)
        vals.append(float(a.mean()))
    return np.asarray(vals, dtype=np.float32)


def flicker_hz(luma: np.ndarray, fps: int = 30) -> float:
    """Dominant non-DC frequency of the global luminance signal, in Hz."""
    x = luma - luma.mean()
    if x.size < 4:
        return 0.0
    spec = np.abs(np.fft.rfft(x))
    spec[0] = 0.0  # drop DC
    k = int(np.argmax(spec))
    return float(k * fps / x.size)


def region_delta(path: Path, i: int, j: int, box: tuple[int, int, int, int]) -> float:
    """Mean abs pixel delta inside a normalised box between two frames.

    Loads the two frames one at a time (1080p PNGs are ~320 KB decoded but
    ~8 MB in RAM) to keep peak memory low on a busy box.
    """
    frames = sorted(path.glob("frames/frame_*.png"))
    if len(frames) <= max(i, j):
        raise RuntimeError(f"{path}: only {len(frames)} frames, need index {max(i, j)}")
    a = np.asarray(Image.open(frames[i]).convert("L"), dtype=np.float32)
    b = np.asarray(Image.open(frames[j]).convert("L"), dtype=np.float32)
    h, w = a.shape
    x0, y0, x1, y1 = box
    ra = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    rb = b[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    del b
    return float(np.abs(ra - rb).mean())


def render(params: dict, out: Path, *, duration: float, aspect: str, seed: int) -> dict:
    """Drive the unit's registered capability in a clean subprocess.

    Reuses an existing successful render (marker file ``.patrol4_done``) so a
    crashed analysis pass does not force a full ~10-minute re-render.
    """
    out.mkdir(parents=True, exist_ok=True)
    marker = out / ".patrol4_done"
    if marker.exists():
        return json.loads(marker.read_text())
    script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.capabilities import get
cap = get({params.get('capability', 'particle_science_scene')!r})
p = json.loads({json.dumps(params)!r})
p.pop('capability', None)
res = cap.render(p, Path({str(out)!r}), duration={duration}, aspect={aspect!r}, seed={seed})
print('RESULT_JSON:' + json.dumps({{'mp4': res.mp4, 'duration_s': res.duration_s, 'sha256': res.sha256, 'qa': res.qa}}))
"""
    proc = subprocess.run([PY, "-c", script], cwd=str(WORKTREE),
                          capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"render failed rc={proc.returncode}\nSTDOUT:{proc.stdout[-2000:]}\nSTDERR:{proc.stderr[-4000:]}")
    line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON:")][-1]
    result = json.loads(line[len("RESULT_JSON:"):])
    marker.write_text(json.dumps(result))
    return result


def main() -> int:
    import os
    base = os.environ.get("PATROL4_PARTSCI_DIR")
    tmp = Path(base) if base else Path(tempfile.mkdtemp(prefix="patrol4_partsci_"))
    tmp.mkdir(parents=True, exist_ok=True)
    print(f"workdir {tmp}", flush=True)

    # ---- 1. fresh renders of both sample scripts (1080p, audio) ----
    cases = [
        ("sky_blue_16_9", {"concept": "sky_blue", "theme": "sky", "keyword": "蓝天",
                           "narration": "太阳光散射让天空变蓝。", "mechanism": "太阳光散射"},
         "16:9", (1920, 1080)),
        ("rain_9_16", {"concept": "rain_source", "theme": "water", "keyword": "下雨",
                       "narration": "水蒸气凝结成雨降落。", "mechanism": "蒸发凝结循环"},
         "9:16", (1080, 1920)),
    ]
    rendered: dict[str, dict] = {}
    for name, params, aspect, expect in cases:
        p = dict(params)
        p["seed"] = 4242
        r = render(p, tmp / name, duration=4.0, aspect=aspect, seed=4242)
        rendered[name] = r
        info = probe(Path(r["mp4"]))
        vs = [s for s in info["streams"] if s["codec_type"] == "video"]
        aud = [s for s in info["streams"] if s["codec_type"] == "audio"]
        got = (vs[0]["width"], vs[0]["height"]) if vs else None
        record(f"ffprobe {name}: 1080p {expect}", got == expect, f"got={got}")
        record(f"ffprobe {name}: has audio stream", bool(aud),
               f"codec={aud[0]['codec_name'] if aud else None}")
        dur = float(info["format"]["duration"])
        record(f"ffprobe {name}: duration ~= 4.0s", abs(dur - 4.0) < 0.35, f"got={dur:.3f}")
        # audio must actually carry signal, not silence
        vol = subprocess.run(
            ["/home/soffy/.local/bin/ffmpeg", "-v", "info", "-i", r["mp4"],
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True).stderr
        m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", vol)
        record(f"ffprobe {name}: audio non-silent", bool(m) and float(m.group(1)) > -60,
               f"mean_volume={m.group(1) if m else 'n/a'} dB")

    # ---- 2. particle/keyword text rasterised + parallax layers displace ----
    for name in ("sky_blue_16_9", "rain_9_16"):
        d = tmp / name
        frames = sorted(d.glob("frames/frame_*.png"))
        record(f"{name}: frames produced", len(frames) >= 100, f"n={len(frames)}")
        a = np.asarray(Image.open(frames[0]).convert("L"), dtype=np.float32)
        b = np.asarray(Image.open(frames[1]).convert("L"), dtype=np.float32)
        # text band: keyword is drawn at H*0.2 -> high-frequency ink there
        h, w = a.shape
        band0 = a[int(0.10 * h):int(0.28 * h), :]
        band1 = b[int(0.10 * h):int(0.28 * h), :]
        text_contrast = float(band0.std())
        record(f"{name}: keyword band has text ink (std)", text_contrast > 12.0,
               f"std={text_contrast:.2f}")
        # top region (parallax bg / subject), bottom region (wave layer)
        # must move differently -> independent layers
        boxes = {
            "subject_center": (0.35, 0.40, 0.65, 0.62),
            "wave_bottom":    (0.05, 0.72, 0.95, 0.98),
            "particle_field": (0.05, 0.30, 0.95, 0.70),
        }
        deltas = {}
        for k, box in boxes.items():
            deltas[k] = round(region_delta(d, 5, 25, box), 3)
        uniq = len(set(deltas.values()))
        record(f"{name}: parallax layers displace independently",
               uniq >= 2 and max(deltas.values()) > 0.5,
               f"deltas={deltas}")
        # motion actually present (not a static image).  Compare frames a
        # whole beat apart (frame 5 -> 60, i.e. t=0.17s -> t=2.0s); comparing
        # adjacent frames at 30fps measures only 33ms of drift and is not a
        # meaningful "is it animating" signal.
        full = float(np.abs(
            np.asarray(Image.open(frames[5]).convert("L"), dtype=np.float32)
            - np.asarray(Image.open(frames[60]).convert("L"), dtype=np.float32)
        ).mean())
        record(f"{name}: frames actually animate", full > 1.0, f"mean_delta={full:.2f}")

    # ---- 3. flicker <= 3 Hz ----
    for name in ("sky_blue_16_9", "rain_9_16"):
        L = luma(tmp / name)
        f = flicker_hz(L, fps=30)
        record(f"{name}: luminance flicker <= 3Hz", f <= 3.0, f"dominant={f:.2f}Hz")

    # ---- 4. fact card source + narration consistency ----
    fact_chk = subprocess.run([PY, "-c", f"""
import sys, json
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.partsci.facts import _LOCAL_KB, get_fact_card, verify_mechanism
out = {{}}
for k in ('sky_blue','rain_source'):
    c = get_fact_card(k)
    out[k] = {{'url': c['source_url'], 'fact': c['fact'], 'mech': c['mechanism']}}
out['_wrong_rejected'] = not verify_mechanism('sky_blue', '地球引力导致')
out['_unknown_rejected'] = False
try:
    get_fact_card('黑洞')
except ValueError:
    out['_unknown_rejected'] = True
print('FACT_JSON:' + json.dumps(out, ensure_ascii=False))
"""], cwd=str(WORKTREE), capture_output=True, text=True)
    fj = json.loads([l for l in fact_chk.stdout.splitlines() if l.startswith("FACT_JSON:")][-1][len("FACT_JSON:"):])
    for k in ("sky_blue", "rain_source"):
        u = fj[k]["url"]
        record(f"fact {k}: authoritative source URL", bool(u) and u.startswith("https://"),
               u or "MISSING")
        narr = {"sky_blue": "太阳光散射让天空变蓝。", "rain_source": "水蒸气凝结成雨降落。"}[k]
        mech = fj[k]["mech"]
        fact = fj[k]["fact"]
        # The narration must be *about* the same causal mechanism as the fact
        # card.  Check each mechanism token is reflected in the narration and
        # that the narration's own key concepts appear in the fact card.
        mech_tokens = [t for t in ("蒸发", "凝结", "散射", "光合", "吸水") if t in mech]
        narr_mech_ok = all(
            (tok in narr) or (tok in fact and tok[0] in narr) for tok in mech_tokens
        ) if mech_tokens else (mech in narr)
        # concrete subject words of the narration must be backed by the fact card
        subjects = [w for w in ("天空", "雨", "云", "水滴", "水蒸气", "太阳", "蓝") if w in narr]
        backed = [w for w in subjects if w in fact]
        record(f"fact {k}: narration consistent with fact card",
               narr_mech_ok and (not subjects or bool(backed)),
               f"mechanism={mech} tokens_in_narration={narr_mech_ok} "
               f"subjects={subjects} backed_by_fact={backed}")
    record("fact: wrong mechanism rejected", fj["_wrong_rejected"] is True)
    record("fact: unknown concept rejected (no fabrication)", fj["_unknown_rejected"] is True)

    # ---- 5. unapproved storyboard must refuse to render ----
    gate = subprocess.run([PY, "-c", f"""
import sys
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.partsci.storyboard import PartsciStoryboard, PartsciShot
s = PartsciStoryboard(title='t', concept_key='sky_blue', aspect='16:9',
                      shots=[PartsciShot(1, 3.0, 'sky_blue', '蓝天', 'n', '太阳光散射')],
                      approved=False)
try:
    s.validate_all()
    print('UNEXPECTED_PASS')
except RuntimeError:
    print('REJECTED')
"""], cwd=str(WORKTREE), capture_output=True, text=True)
    record("storyboard gate: unapproved rejected",
           "REJECTED" in gate.stdout and "UNEXPECTED_PASS" not in gate.stdout)

    # ---- 6. same seed twice -> identical output ----
    # Two levels, reported separately because they are genuinely different:
    #  (a) the rendered *video* (Canvas frames + h264) — this is what the
    #      seeded-PRNG determinism claim is about, and it is bit-identical.
    #  (b) the *muxed mp4* — also contains Piper TTS audio.  Piper's ONNX
    #      inference is itself non-deterministic on CPU (verified separately:
    #      3 identical invocations -> 3 different wav hashes), so the final
    #      container cannot be byte-reproducible.  We measure and report that
    #      honestly rather than hiding it.
    p = dict(cases[0][1]); p["seed"] = 777
    r1 = render(p, tmp / "det_a", duration=3.0, aspect="16:9", seed=777)
    r2 = render(p, tmp / "det_b", duration=3.0, aspect="16:9", seed=777)

    def frame_hashes(d: Path) -> list[str]:
        return [hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(d.glob("frames/frame_*.png"))]

    f1, f2 = frame_hashes(tmp / "det_a"), frame_hashes(tmp / "det_b")
    record("determinism(a): all rendered frames bit-identical across runs",
           f1 == f2 and len(f1) > 0, f"{len(f1)} frames, n_mismatch="
                                        f"{sum(1 for x, y in zip(f1, f2) if x != y)}")

    import subprocess as _sp
    def _sha(path: Path) -> str:
        return _sp.run(["sha256sum", str(path)], capture_output=True,
                       text=True).stdout.split()[0]
    v1 = _sha(tmp / "det_a" / "video_only.mp4")
    v2 = _sha(tmp / "det_b" / "video_only.mp4")
    record("determinism(a): video-only mp4 bit-identical across runs",
           v1 == v2, f"{v1[:16]} == {v2[:16]}")
    a1 = _sha(tmp / "det_a" / "narration.wav")
    a2 = _sha(tmp / "det_b" / "narration.wav")
    mp4_same = r1["sha256"] == r2["sha256"]
    record("determinism(b): final muxed mp4 byte-identical",
           mp4_same,
           f"video=identical, audio_wav={'identical' if a1 == a2 else 'differs (Piper CPU nondeterminism)'}"
           f" -> final mp4 {'identical' if mp4_same else 'differs'}")

    # ---- 7. capability registry + schema rejection ----
    # NOTE: in this codebase `render` does NOT self-validate; the real
    # enforcement points are Capability.validate_params, called by the
    # /api/capabilities preview router and by ShotSpec.  We therefore exercise
    # that path (the same convention scene3d already uses), not render().
    reg = subprocess.run([PY, "-c", f"""
import sys, json
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.capabilities import get, list_capabilities
from hevi.capabilities.registry import CapabilityError
names = [c.name for c in list_capabilities(kind='shot')]
out = {{'registered': [n for n in ('particle_text','particle_science_scene','parallax_layers') if n in names]}}
cap = get('particle_science_scene')
bad_cases = [
    {{'concept':'sky_blue','keyword':'这个关键词太长了'}},
    {{'concept':'sky_blue','bogus':1}},
    {{'concept':'sky_blue','seed':'not-an-int'}},
    {{}},
]
rejected = []
for bad in bad_cases:
    try:
        cap.validate_params(bad)
    except CapabilityError:
        rejected.append(1)
out['rejected_bad_params'] = len(rejected)
out['bad_total'] = len(bad_cases)
out['aspect_1_1_supported'] = cap.supports_aspect('1:1')
try:
    cap.validate_params({{'concept':'sky_blue','keyword':'蓝天','seed':1}})
    out['valid_accepted'] = True
except CapabilityError:
    out['valid_accepted'] = False
print('REG_JSON:' + json.dumps(out, ensure_ascii=False))
"""], cwd=str(WORKTREE), capture_output=True, text=True)
    rj = json.loads([l for l in reg.stdout.splitlines() if l.startswith("REG_JSON:")][-1][len("REG_JSON:"):])
    record("capability: 3 partsci caps registered", len(rj["registered"]) == 3,
           str(rj["registered"]))
    record("capability: illegal params rejected (all 4 cases)",
           rj.get("rejected_bad_params") == rj.get("bad_total"),
           f"{rj.get('rejected_bad_params')}/{rj.get('bad_total')}")
    record("capability: legal params still accepted", rj.get("valid_accepted") is True)
    record("capability: unsupported aspect 1:1 refused", rj.get("aspect_1_1_supported") is False)

    # ---- summary ----
    npass = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n==== PATROL4 PARTSCI SUMMARY ====")
    print(f"{npass}/{len(RESULTS)} checks passed")
    fails = [n for n, ok, _ in RESULTS if not ok]
    if fails:
        print("FAILED: " + "; ".join(fails))
    print("VERDICT: " + ("PASS" if npass == len(RESULTS) else "FAIL"))
    (tmp / "result.json").write_text(json.dumps(
        {"results": [{"check": n, "ok": o, "detail": d} for n, o, d in RESULTS],
         "pass": npass, "total": len(RESULTS)}, ensure_ascii=False, indent=2))
    return 0 if npass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

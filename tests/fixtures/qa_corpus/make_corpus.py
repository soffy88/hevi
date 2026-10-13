#!/usr/bin/env python3
"""Generate the Q2 bad-clip regression corpus (SFXBAD_TASK.md section B).

Produces >=17 deliberately-broken clips plus one clean clip and writes a
``manifest.json`` describing every defect (with its expected failure tags and
time window) so the tests can verify each defect physically exists.

The clips are *not* committed (they live under ``$HEVI_QA_CORPUS_DIR``); only
this generator and the manifest are.

Everything is deterministic: a fixed lavfi base, ``-threads 1``, x264 with
fixed params (no scene cut, fixed keyframe interval) and the ``+bitexact``
flags, so two runs produce byte-identical files (verified per clip and recorded
as ``sha_stable`` in the manifest).

Usage::

    python3 tests/fixtures/qa_corpus/make_corpus.py [--out DIR] [--base FILE]
                                                    [--no-determinism-check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXDIR = Path(__file__).resolve().parent
MANIFEST = FIXDIR / "manifest.json"

W, H, FPS, DUR = 1280, 720, 24, 14
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DEFAULT_DIR = os.environ.get("HEVI_QA_CORPUS_DIR", "/tmp/hevi_qa_corpus")

# Deterministic encoding. threads=1 + fixed keyint + no scenecut keeps x264
# byte-stable; the bitexact flags stop ffmpeg from stamping encoder version /
# timestamp metadata into the container.
VENC = [
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "20",
    "-pix_fmt",
    "yuv420p",
    "-threads",
    "1",
    "-x264-params",
    "threads=1:sliced-threads=0:rc-lookahead=0:keyint=48:min-keyint=48:scenecut=0",
    "-fflags",
    "+bitexact",
    "-flags:v",
    "+bitexact",
    "-flags:a",
    "+bitexact",
]
AENC = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-800:]}"
        )


def ffmpeg(*args: str) -> None:
    _run(["ffmpeg", "-nostdin", "-hide_banner", "-y", "-loglevel", "error", *args])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_png(text: str, font_px: int, x: int, y: int, path: Path) -> None:
    """Render ``text`` to a transparent full-frame PNG at (x, y)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, font_px)
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)


def _text_width(text: str, font_px: int) -> int:
    from PIL import ImageFont

    font = ImageFont.truetype(FONT, font_px)
    return int(font.getlength(text))


# ---------------------------------------------------------------------------
# base clip
# ---------------------------------------------------------------------------


def build_base(out: Path, real_base: Path | None) -> Path:
    """Deterministic 14 s 1280x720 24fps base with a real audio bed."""
    dst = out / "base.mp4"
    if real_base is not None:
        ffmpeg(
            "-i",
            str(real_base),
            "-t",
            str(DUR),
            "-vf",
            f"scale={W}:{H},fps={FPS}",
            *VENC,
            *AENC,
            str(dst),
        )
        return dst
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={W}x{H}:rate={FPS}:duration={DUR}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=44100:duration={DUR}",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=pink:sample_rate=44100:duration={DUR}:seed=1234:amplitude=0.03",
        "-filter_complex",
        "[1:a][2:a]amix=inputs=2:normalize=0[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(dst),
    )
    return dst


# ---------------------------------------------------------------------------
# clip builders: each returns (path, expected_failures, defect_window, recipe)
# ---------------------------------------------------------------------------

NOISE_VF = "geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'"


def _enc(
    base: Path,
    dst: Path,
    vf: str | None = None,
    extra_in: list[str] | None = None,
    extra_out: list[str] | None = None,
    venc: list[str] | None = None,
    aenc: list[str] | None = None,
    complex_fc: str | None = None,
    maps: list[str] | None = None,
) -> None:
    """Encode one variant of ``base`` into ``dst`` with the deterministic settings.

    ``base`` is always input 0 and ``extra_in`` inputs follow, so filter-graph
    stream indices are stable: ``[0:v]``/``0:a`` are the base picture/audio and
    ``[1:...]`` is the first extra input.
    """
    venc = venc if venc is not None else VENC
    aenc = aenc if aenc is not None else AENC
    args: list[str] = ["-i", str(base)]
    if extra_in:
        args += extra_in
    if complex_fc:
        args += ["-filter_complex", complex_fc]
        # ``maps`` is the complete list of stream specifiers to emit
        for m in maps if maps is not None else ["[v]", "0:a"]:
            args += ["-map", m]
    else:
        if vf:
            args += ["-vf", vf]
        args += ["-map", "0:v", "-map", "0:a"]
    if extra_out:
        args += extra_out
    args += ["-t", str(DUR), *venc, *aenc, str(dst)]
    ffmpeg(*args)


def build_clips(base: Path, out: Path) -> list[dict]:
    clips: list[dict] = []

    def add(cid, recipe, expected, window, extra=None):
        rec = {
            "id": cid,
            "recipe": recipe,
            "expected_failures": expected,
            "defect_window_s": window,
        }
        if extra:
            rec.update(extra)
        clips.append(rec)

    # --- r4 originals ---------------------------------------------------
    _enc(base, out / "bad01_noise_full.mp4", vf=NOISE_VF)
    add(
        "bad01_noise_full",
        "full-frame random noise video, base audio kept",
        ["visual.noise"],
        [0.0, DUR],
    )

    _enc(
        base,
        out / "bad02_glitch_local.mp4",
        complex_fc=(f"[1:v]{NOISE_VF}[n];[0:v][n]overlay=enable='between(t,4,7)'[v]"),
        extra_in=["-f", "lavfi", "-i", f"nullsrc=s={W}x{H}:r={FPS}:d={DUR}"],
    )
    add(
        "bad02_glitch_local",
        "random-noise overlay only during 4-7 s",
        ["visual.noise@4-7s"],
        [4.0, 7.0],
    )

    ffmpeg(
        "-i",
        str(base),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-qp",
        "51",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "1",
        "-c:a",
        "copy",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        str(out / "bad03_macroblock_qp51.mp4"),
    )
    add(
        "bad03_macroblock_qp51",
        "re-encode at QP 51 (extreme macroblocking)",
        ["visual.macroblock"],
        [0.0, DUR],
    )

    tmp_m2v = out / "_tmp_lq.m2v"
    ffmpeg(
        "-i",
        str(base),
        "-vf",
        "scale=320:180",
        "-c:v",
        "mpeg2video",
        "-qscale:v",
        "31",
        "-an",
        "-f",
        "mpeg2video",
        str(tmp_m2v),
    )
    _enc(
        base,
        out / "bad04_macroblock_mpeg2.mp4",
        # input 0 is the base, input 1 is the low-res mpeg2; upscale the *mpeg2*
        complex_fc="[1:v]scale=1280:720:flags=neighbor[v]",
        extra_in=["-i", str(tmp_m2v)],
    )
    tmp_m2v.unlink(missing_ok=True)
    add(
        "bad04_macroblock_mpeg2",
        "320x180 mpeg2 q31 upscaled with nearest-neighbour",
        ["visual.macroblock"],
        [0.0, DUR],
    )

    _enc(base, out / "bad05_green_full.mp4", vf="geq=lum=0:cb=0:cr=0")
    add(
        "bad05_green_full",
        "decoder-failure green (Y=0,U=0,V=0) whole clip",
        ["visual.green"],
        [0.0, DUR],
    )

    _enc(
        base,
        out / "bad06_green_local.mp4",
        vf="drawbox=x=0:y=0:w=iw:h=ih:color=0x00FF00:t=fill:enable='between(t,6,9)'",
    )
    add(
        "bad06_green_local",
        "full-frame green flash during 6-9 s",
        ["visual.green@6-9s"],
        [6.0, 9.0],
    )

    _enc(
        base,
        out / "bad07_halfgray_bottom.mp4",
        vf="drawbox=x=0:y=ih/2:w=iw:h=ih/2:color=0x808080:t=fill",
    )
    add(
        "bad07_halfgray_bottom",
        "bottom half replaced with flat gray",
        ["visual.half_gray"],
        [7.0, DUR],
    )

    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={W}x{H}:r={FPS}:d={DUR}",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(out / "bad08_black_silent.mp4"),
    )
    add(
        "bad08_black_silent",
        "black video + silent audio for the whole clip",
        ["visual.black", "audio.silence"],
        [0.0, DUR],
    )

    _enc(
        base,
        out / "bad09_audio_silence_gap.mp4",
        venc=["-c:v", "copy"],
        extra_out=["-af", "volume=enable='between(t,3,11)':volume=0"],
    )
    add(
        "bad09_audio_silence_gap",
        "audio muted during 3-11 s",
        ["audio.silence_gap@3-11s"],
        [3.0, 11.0],
    )

    _enc(
        base,
        out / "bad10_audio_clip.mp4",
        venc=["-c:v", "copy"],
        extra_out=[
            "-af",
            "volume=enable='between(t,5,8)':volume=40dB,alimiter=limit=1:level=false",
        ],
    )
    add(
        "bad10_audio_clip",
        "+40 dB and hard limiter during 5-8 s (clipping)",
        ["audio.clipping@5-8s"],
        [5.0, 8.0],
    )

    _enc(
        base,
        out / "bad11_audio_pops.mp4",
        venc=["-c:v", "copy"],
        complex_fc="[0:a][1:a]amix=inputs=2:normalize=0[a]",
        extra_in=[
            "-f",
            "lavfi",
            "-t",
            str(DUR),
            "-i",
            "aevalsrc='if(lt(mod(t,0.5),0.004),0.99*sgn(sin(2*PI*900*t)),0)':s=44100:c=stereo",
        ],
        maps=["0:v", "[a]"],
    )
    add(
        "bad11_audio_pops",
        "periodic 900 Hz clicks every 0.5 s (pops/clicks)",
        ["audio.clicks"],
        [0.0, DUR],
    )

    # --- new defects ----------------------------------------------------
    _build_subtitle_clips(base, out, add)
    _build_freeze_clip(base, out, add)
    _build_desync_clip(base, out, add)
    _build_letterbox_clip(base, out, add)
    return clips


def _subtitle_base(out: Path, name: str) -> Path:
    """Dark solid background with a slowly moving bar (so it is not 'frozen')."""
    dst = out / name
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x606870:s={W}x{H}:r={FPS}:d={DUR}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=330:sample_rate=44100:duration={DUR}",
        "-vf",
        "drawbox=x='mod(t*80\\,1200)':y=690:w=60:h=8:color=red@0.9:t=fill",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(dst),
    )
    return dst


def _build_subtitle_clips(base: Path, out: Path, add) -> None:
    sub_base = _subtitle_base(out, "sub_base.mp4")

    # out of frame: a long line whose glyphs run off the right edge
    text = "SUBTITLE THAT OVERFLOWS THE FRAME EDGE"
    px = 44
    x = W - _text_width(text, px) + 70  # 70 px pushed past the right border
    png = out / "_sub12.png"
    _text_png(text, px, x, 560, png)
    ffmpeg(
        "-i",
        str(sub_base),
        "-i",
        str(png),
        "-filter_complex",
        "[0:v][1:v]overlay=0:0[v]",
        "-map",
        "[v]",
        "-map",
        "0:a",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(out / "bad12_subtitle_out_of_frame.mp4"),
    )
    png.unlink(missing_ok=True)
    add(
        "bad12_subtitle_out_of_frame",
        "burned subtitle runs past the right frame edge",
        ["subtitle.out_of_frame"],
        [0.0, DUR],
    )

    # font too small: 10 px glyphs on a 720 px frame (< 2% of height)
    png = out / "_sub13.png"
    _text_png("small caption text", 10, 60, 650, png)
    ffmpeg(
        "-i",
        str(sub_base),
        "-i",
        str(png),
        "-filter_complex",
        "[0:v][1:v]overlay=0:0[v]",
        "-map",
        "[v]",
        "-map",
        "0:a",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(out / "bad13_font_too_small.mp4"),
    )
    png.unlink(missing_ok=True)
    add(
        "bad13_font_too_small",
        "burned subtitle font 10 px (< 2% of 720 px frame height)",
        ["subtitle.font_too_small"],
        [0.0, DUR],
    )

    # ASR mismatch: the spoken audio and the burned caption disagree.
    spoken = "the quick brown fox jumps over the lazy dog"
    caption = "please remember to water the plants tomorrow morning"
    tts = out / "_sub14_tts.wav"
    _run(["espeak", "-w", str(tts), spoken])
    png = out / "_sub14.png"
    _text_png(caption, 40, 80, 620, png)
    ffmpeg(
        "-i",
        str(sub_base),
        "-i",
        str(png),
        "-i",
        str(tts),
        "-filter_complex",
        "[0:v][1:v]overlay=0:0[v];[2:a]apad[a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(out / "bad14_asr_mismatch.mp4"),
    )
    png.unlink(missing_ok=True)
    tts.unlink(missing_ok=True)
    add(
        "bad14_asr_mismatch",
        "burned caption text differs from the espeak TTS audio track",
        ["subtitle.asr_mismatch"],
        [0.0, DUR],
        # no ASR engine is assumed present, so the two transcripts are recorded
        # here: the audio really says ``audio_text`` (espeak TTS) and the burned
        # caption really reads ``caption_text``.
        extra={"caption_text": caption, "audio_text": spoken, "audio_text_source": "espeak"},
    )


def _build_freeze_clip(base: Path, out: Path, add) -> None:
    f0, f1 = 6 * FPS, 9 * FPS  # 6.0 s .. 9.0 s
    # freezeframes is a 2-input filter: input 0 is the source, input 1 supplies
    # the frames to copy.  Feeding the same clip twice replaces frames f0..f1
    # with an identical copy, i.e. a frozen segment.
    ffmpeg(
        "-i",
        str(base),
        "-i",
        str(base),
        "-filter_complex",
        f"[0:v][1:v]freezeframes=first={f0}:last={f1}:replace={f0}[v]",
        "-map",
        "[v]",
        "-map",
        "0:a",
        *VENC,
        *AENC,
        str(out / "bad15_frozen_mid.mp4"),
    )
    add(
        "bad15_frozen_mid",
        f"video frozen between 6.0 s and 9.0 s (frames {f0}-{f1})",
        ["visual.freeze@6-9s"],
        [6.0, 9.0],
    )


def _build_desync_clip(base: Path, out: Path, add) -> None:
    # A/V desync: shift the audio track 200 ms later than the video with
    # -itsoffset.  ``adelay`` pads leading silence but ffmpeg then trims it back
    # to zero, so it does not produce a measurable offset; -itsoffset keeps the
    # stream start_time after the video's, which ffprobe reports.
    ffmpeg(
        "-i",
        str(base),
        "-itsoffset",
        "0.2",
        "-i",
        str(base),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(out / "bad16_av_desync.mp4"),
    )
    add(
        "bad16_av_desync",
        "audio track offset 200 ms later than video (-itsoffset 0.2)",
        ["av.desync>120ms"],
        [0.0, DUR],
    )


def _build_letterbox_clip(base: Path, out: Path, add) -> None:
    # scale the picture to 504 px tall and pad top+bottom with 108 px black bars
    _enc(base, out / "bad17_letterbox_excess.mp4", vf="scale=1280:504,pad=1280:720:0:108:black")
    add(
        "bad17_letterbox_excess",
        "letterbox bars of 108 px top and bottom (>15% each)",
        ["visual.letterbox_excess"],
        [0.0, DUR],
    )


def build_good(base: Path, out: Path) -> dict:
    """A clean clip: base video with an in-frame, adequately-sized subtitle."""
    png = out / "_good.png"
    _text_png("a normal subtitle line", 34, 120, 640, png)
    ffmpeg(
        "-i",
        str(base),
        "-i",
        str(png),
        "-filter_complex",
        "[0:v][1:v]overlay=0:0[v]",
        "-map",
        "[v]",
        "-map",
        "0:a",
        "-t",
        str(DUR),
        *VENC,
        *AENC,
        str(out / "good_clean.mp4"),
    )
    png.unlink(missing_ok=True)
    return {
        "id": "good_clean",
        "recipe": "clean base clip with an in-frame subtitle",
        "expected_failures": [],
        "defect_window_s": None,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Q2 bad-clip regression corpus")
    ap.add_argument("--out", default=DEFAULT_DIR, help="output directory")
    ap.add_argument("--base", default=None, help="optional real base mp4")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--no-determinism-check", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    real_base = Path(args.base).resolve() if args.base else None

    print(f"base: {'real ' + str(real_base) if real_base else 'lavfi testsrc2'}")
    base = build_base(out, real_base)

    clips = build_clips(base, out)
    good = build_good(base, out)

    entries = [good, *clips]
    # determinism check: re-encode every clip once more and compare bytes
    for e in entries:
        p = out / f"{e['id']}.mp4"
        e["sha256"] = sha256(p)
        e["duration_s"] = round(_duration(p), 3)
        e["sha_stable"] = True
        e["sha_note"] = None

    if not args.no_determinism_check:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base2 = build_base(tmp, real_base)
            clips2 = build_clips(base2, tmp)
            good2 = build_good(base2, tmp)
            by_id = {c["id"]: c for c in [good2, *clips2]}
            for e in entries:
                if sha256(tmp / f"{e['id']}.mp4") != e["sha256"]:
                    e["sha_stable"] = False
                    e["sha_note"] = "re-encode differed (non-deterministic encoder path)"

    stable = sum(1 for e in entries if e["sha_stable"])
    manifest = {
        "corpus_version": "1.0",
        "generator": "tests/fixtures/qa_corpus/make_corpus.py",
        "base": {
            "kind": "real" if real_base else "lavfi",
            "source": str(real_base) if real_base else "testsrc2 + sine/pink-noise mix",
            "width": W,
            "height": H,
            "fps": FPS,
            "duration_s": DUR,
        },
        "encode": {
            "vcodec": "libx264",
            "crf": 20,
            "preset": "veryfast",
            "acodec": "aac",
            "threads": 1,
            "bitexact": True,
            "x264_params": "threads=1:sliced-threads=0:rc-lookahead=0:"
            "keyint=48:min-keyint=48:scenecut=0",
        },
        "clip_count": len(entries),
        "bad_clip_count": len(clips),
        "sha_stable_count": stable,
        "clips": entries,
    }
    mp = Path(args.manifest)
    mp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} clips ({len(clips)} bad) -> {out}")
    print(f"manifest: {mp}  (sha_stable {stable}/{len(entries)})")
    for e in entries:
        print(
            f"  {e['id']:<34} {e['duration_s']:>6.2f}s "
            f"{'stable' if e['sha_stable'] else 'UNSTABLE'} {e['sha256'][:12]}"
        )
    return 0


def _duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


if __name__ == "__main__":
    raise SystemExit(main())

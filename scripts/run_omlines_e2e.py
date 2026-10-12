#!/usr/bin/env python3
"""Zero-cost E2E for the 13 canonical production lines.

Every line is produced through the real product entry point
(``hevi.studio.veya:produce``) with the free-tier fallback, **twice**: once
with input set ``a`` and once with input set ``b``.  Set ``b`` uses a different
topic and different source media / presenter photo, so a slot-blind producer
would produce identical output for both runs and be caught here.

Nothing is mocked: acceptance is measured with ffprobe + frame statistics
(``zl.qa``), the topic keyword must be verifiably present in the burned-in
subtitle source, and for the photo-driven lines the supplied ``image_path``
must actually be on screen (pixel comparison against the source photo).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Required binaries on PATH; downloads must bypass the small Gemini SSH tunnel.
os.environ["PATH"] = f"/home/soffy/.local/bin:/home/soffy/.nvm/versions/node/v26.4.0/bin:{os.environ.get('PATH', '')}"
for _k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from hevi.layer4_legacy.omlines.oprim_impl import zl  # noqa: E402
from hevi.studio.production_catalog import CANONICAL_LINES  # noqa: E402
from hevi.studio.veya import produce  # noqa: E402
from scripts.qualify_autonomous_production import _slots  # noqa: E402

logging.basicConfig(level=logging.INFO)

VARIANTS = ("a", "b")


def _grab(video: str, index: int, shape: tuple[int, int]) -> np.ndarray:
    """Decode frame ``index`` at native resolution."""
    raw = zl.sh([zl.FF, "-v", "error", "-i", video, "-vf", f"select=eq(n\\,{index})", "-vsync", "0",
                  "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture=True)
    return np.frombuffer(raw, np.uint8).reshape(shape[0], shape[1], 3)


def _frame_shape(video: str) -> tuple[int, int]:
    info = json.loads(zl.sh([zl.FP, "-v", "error", "-show_entries", "stream=width,height",
                             "-of", "json", video], capture=True).decode())
    st = next(s for s in info["streams"] if "width" in s)
    return int(st["width"]), int(st["height"])


def _presenter_rect(out_dir: Path, artifact: str) -> dict | None:
    """Locate the renderer's own record of where the presenter photo was placed.

    Two renderers are accepted, both of which publish frame-space rectangles:
    the free tier (``presenter_rect`` sidecar) and the talkcraft host layout
    (``provenance.avatar.host_boxes``).  Returns ``None`` if neither is present,
    in which case the photo-on-screen check cannot be proven and must fail.
    """
    rec_path = out_dir / "record.json"
    if not rec_path.is_file():
        return None
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if isinstance(rec.get("presenter_rect"), dict):
        return rec["presenter_rect"]
    for r in rec.get("records") or []:
        boxes = ((r.get("provenance") or {}).get("avatar") or {}).get("host_boxes") or {}
        if boxes:
            key = "portrait" if str(r.get("width", 0)) < str(r.get("height", 0)) else "landscape"
            key = "portrait" if (r.get("height") or 0) > (r.get("width") or 0) else "landscape"
            if str(r.get("video_path")) == str(artifact) and key in boxes:
                hx, hy, hw, hh = boxes[key]["host"]
                return {"talkcraft": True, "rect": [int(hx), int(hy), int(hw), int(hh)]}
    return None


def _photo_on_screen(video: str, image_path: str, rect_meta: dict) -> tuple[bool, float]:
    """Prove the caller-supplied ``image_path`` is literally in the picture.

    The renderer records the exact pixel rectangle where the supplied photo was
    composited.  We crop that rectangle out of the *rendered* video, resize it
    back to the photo's own size and measure normalised cross-correlation
    against the source photo.  A line that ignored the slot and rendered a
    generic cartoon scores ~0 here; the real photo scores > 0.75.
    """
    cv2 = _cv2()
    photo = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if photo is None:
        raise RuntimeError(f"cannot read supplied image_path: {image_path}")
    ph, pw = photo.shape[:2]
    vw, vh = _frame_shape(video)
    nframes = _frame_count(video)
    if rect_meta.get("talkcraft"):
        # fixed panel: one rectangle, resampled for every probed frame
        x, y, w, h = (int(v) for v in rect_meta["rect"])
        probes = [(i, (x, y, w, h)) for i in sorted({max(0, nframes - 1), nframes // 3, 2 * nframes // 3})]
        circular = False
    else:
        meta = json.loads(Path(str(rect_meta["video"])).read_text(encoding="utf-8"))
        if meta.get("kind") == "pip":
            scale_x = scale_y = 1.0  # PiP stream is overlaid unscaled
            off_x, off_y = (rect_meta.get("offset") or [0, 0])
        else:
            scale_x, scale_y = vw / meta["frame_w"], vh / meta["frame_h"]
            off_x = off_y = 0
        cand = sorted({int(meta["fps"] * k) for k in (0.25, 0.4, 0.55, 0.7, 0.85)})
        cand = [i for i in cand if i < len(meta["rects"])]
        probes = [(i, (int(meta["rects"][i][0] * scale_x) + off_x, int(meta["rects"][i][1] * scale_y) + off_y,
                       int(meta["rects"][i][2] * scale_x), int(meta["rects"][i][3] * scale_y))) for i in cand]
        circular = meta.get("kind") == "pip"
    best = 0.0
    for i, (x, y, w, h) in probes:
        crop = _grab(video, i, (vh, vw))[y:y + h, x:x + w]
        if crop.size == 0 or crop.shape[0] < 16 or crop.shape[1] < 16:
            continue
        patch = cv2.resize(crop, (pw, ph), interpolation=cv2.INTER_AREA)
        a_img, b_img = patch, photo
        if circular:  # the PiP is masked to a circle by the compositor
            m = np.zeros((ph, pw), np.uint8)
            cv2.circle(m, (pw // 2, ph // 2), max(4, min(ph, pw) // 2 - 4), 255, -1)
            sel = m > 0
            # boolean indexing flattens to (N, 3): keep an image shape for cvtColor
            a_img, b_img = patch[sel].reshape(-1, 1, 3), photo[sel].reshape(-1, 1, 3)
        a = cv2.cvtColor(a_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(b_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        a -= a.mean(); b -= b.mean()
        den = float(np.linalg.norm(a) * np.linalg.norm(b))
        best = max(best, float((a * b).sum() / den) if den else 0.0)
    return best > 0.60, round(best, 3)


def _frame_count(video: str) -> int:
    out = zl.sh([zl.FP, "-v", "error", "-count_frames", "-select_streams", "v:0",
                  "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", video], capture=True)
    return int(out.decode().strip() or 0)


def _cv2():
    import cv2  # local import: only the E2E verifier needs OpenCV

    return cv2


def _topic_evidence(out_dir: Path) -> str:
    """Everything the run wrote that carries the topic: burned-in subtitle source
    plus the record / shotbook the renderer persisted."""
    blob = []
    for p in sorted(out_dir.rglob("*.ass")):
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("Dialogue:"):
                blob.append(line.split(",", 9)[-1])
    for name in ("record.json", "shotbook.json"):
        f = out_dir / name
        if f.is_file():
            blob.append(f.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(blob)


async def process_run(sem, line: str, variant: str, root: Path) -> dict:
    async with sem:
        out_dir = root / f"{line}__{variant}"
        slots = _slots(line, variant)
        # this E2E qualifies the omlines zero-cost tier: do not route host lines to the
        # separate talkcraft renderer (its own acceptance lives in the talkcraft suite)
        slots.pop("renderer", None)
        topic = str(slots["topic"])
        print(f"[{line}/{variant}] topic={topic!r} ...", flush=True)
        row: dict = {"line": line, "variant": variant, "inputs": {
            k: v for k, v in slots.items() if k in {"topic", "source", "media_path", "image_path", "lang", "variant"}}}
        try:
            job = await produce(line_id=line, slots=slots, output_dir=str(out_dir),
                                execute=True, publish=False)
            art = job.artifact
            row["job_status"] = job.status
            row["product"] = job.product
            row["fulfill_quality_pass"] = bool(((job.fulfill or {}).get("quality") or {}).get("pass"))
            if not art or not Path(art).is_file():
                row.update(status="FAIL", reason=f"no artifact, job_status={job.status}, reason={job.reason}")
                return row

            q = zl.qa(str(art))
            checks = dict(q.get("checks") or {})
            zl.contact_sheet(str(art), str(out_dir / "contact_sheet.jpg"))

            # measured gate: every physical check must hold (thresholds are not relaxed)
            if not all(checks.values()):
                row.update(status="FAIL", reason="measured QA checks failed: " +
                           ",".join(k for k, v in checks.items() if not v),
                           qa_checks=checks, metrics=_metrics(q), path=str(art))
                return row

            # input relevance 1: the topic keyword must be burned into the subtitle track
            # (or persisted verbatim in the renderer's own record/shotbook)
            evidence = _topic_evidence(out_dir)
            topic_hit = topic in evidence
            checks["topic_in_subtitles"] = bool(topic_hit)
            src = str(slots.get("media_path") or slots.get("source") or "")
            rep = out_dir / "shorts_generation_report.json"
            if not topic_hit and line == "shorts_clip" and rep.is_file():
                # the production shorts renderer cuts the supplied footage and takes no topic:
                # relevance = the report proves which real source was cut
                used = (json.loads(rep.read_text(encoding="utf-8")).get("inputs") or {}).get("source_video_path")
                checks["source_in_report"] = bool(src) and str(used) == src
                topic_hit = checks["source_in_report"]
            if not topic_hit:
                row.update(status="FAIL", reason=f"topic keyword {topic!r} not present in subtitles/record",
                           qa_checks=checks, path=str(art))
                return row

            # input relevance 2: for photo-driven lines the supplied photo must be on screen
            rect_meta = _presenter_rect(out_dir, str(art))
            if slots.get("image_path"):
                if not rect_meta:
                    row.update(status="FAIL", reason="renderer published no presenter rectangle; "
                                                    "cannot prove the supplied photo is on screen")
                    return row
                ok, score = _photo_on_screen(str(art), str(slots["image_path"]), rect_meta)
                checks["supplied_photo_on_screen"] = ok
                row["photo_match_score"] = score
                if not ok:
                    row.update(status="FAIL", reason=f"supplied image_path not on screen (ncc={score})",
                               qa_checks=checks, path=str(art))
                    return row

            row.update(
                status="SUCCESS",
                duration=q["duration"], resolution=q["resolution"],
                audio=checks.get("has_audio", False),
                motion_ratio=q["motion_ratio"], motion_mean=q["motion_mean"],
                mean_volume_db=q["mean_volume_db"],
                tier=job.production_order.get("fallback") or job.render_runtime,
                sha256=q["sha256"], path=str(art),
                contact_sheet=str(out_dir / "contact_sheet.jpg"),
                qa_checks=checks, metrics=_metrics(q),
            )
            return row
        except Exception as exc:  # noqa: BLE001 - honest failure reporting
            row.update(status="FAIL", reason=f"{type(exc).__name__}: {exc}")
            return row


def _metrics(q: dict) -> dict:
    return {k: q.get(k) for k in ("motion_mean", "motion_ratio", "static_ratio", "black_ratio",
                                  "dark_textcard_ratio", "mean_volume_db")}


async def main() -> int:
    root = Path("output/om_lines_e2e")
    root.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(2)  # bounded CPU: 2 lines at a time
    # OMLINES_E2E_ONLY=a,b re-runs just those lines and merges them into the existing results
    only = [x for x in os.environ.get("OMLINES_E2E_ONLY", "").split(",") if x]
    lines = [ln for ln in CANONICAL_LINES if not only or ln in only]
    tasks = [process_run(sem, line, v, root) for line in lines for v in VARIANTS]
    results = list(await asyncio.gather(*tasks))
    prev_path = root / "e2e_results.json"
    if only and prev_path.is_file():
        prev = json.loads(prev_path.read_text(encoding="utf-8")).get("runs") or []
        results = [r for r in prev if r.get("line") not in only] + results
        results.sort(key=lambda r: (list(CANONICAL_LINES).index(r["line"]), r["variant"]))

    by_line: dict[str, dict] = {}
    for r in results:
        by_line.setdefault(r["line"], {})[r["variant"]] = r
    summary = []
    for line, vs in by_line.items():
        a, b = vs.get("a", {}), vs.get("b", {})
        # Only check input-blind if BOTH variants produced successful artifacts
        if a.get("status") == "SUCCESS" and b.get("status") == "SUCCESS":
            distinct = bool(a.get("sha256")) and bool(b.get("sha256")) and a["sha256"] != b["sha256"]
            if not distinct:
                a["status"] = b["status"] = "FAIL"
                for r in (a, b):
                    r["reason"] = (r.get("reason", "") + " | " if r.get("reason") else "") + \
                        "input-blind: both variants produced the same sha256"
        else:
            # One or both variants failed before artifact production
            distinct = False
        summary.append({
            "line": line,
            "variant_a": {"status": a.get("status"), "sha256": a.get("sha256"), "duration": a.get("duration")},
            "variant_b": {"status": b.get("status"), "sha256": b.get("sha256"), "duration": b.get("duration")},
            "outputs_distinct": distinct,
        })

    ok = all(r["status"] == "SUCCESS" for r in results)
    payload = {"all_passed": ok, "runs": results, "per_line": summary}
    path = root / "e2e_results.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nE2E complete -> {path}  all_passed={ok}")
    for s in summary:
        print(f"  {s['line']:<24} a={s['variant_a']['status']:<8} b={s['variant_b']['status']:<8} distinct={s['outputs_distinct']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
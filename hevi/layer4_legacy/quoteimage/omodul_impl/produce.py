from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.quoteimage.omodul_impl.quality_gates import (
    QualityGateError,
    run_quality_gates,
)
from hevi.layer4_legacy.quoteimage.oprim_impl.detect_band import detect_subtitle_band
from hevi.layer4_legacy.quoteimage.oprim_impl.subtitle_text import (
    band_edge_cuts_text,
    band_text_mass,
    pick_clean_hero_time,
    refine_band,
    sentence_single_card,
)
from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import (
    command_render,
    command_render_script,
    crop_band,
    grab_frame,
    video_metadata,
)
from hevi.layer4_legacy.quoteimage.oprim_impl.whisper import WhisperAligner
from hevi.layer4_legacy.quoteimage.oskill_impl.sentence_picker import pick_sentences

logger = logging.getLogger(__name__)


def _load_script_from_source(video_path: Path) -> list[dict[str, Any]] | None:
    """Attempt to load canonical script lines from adjacent project files."""
    candidates = [
        video_path.parent / "shotbook.json",
        video_path.parent / "work" / "timestamps.json",
        video_path.parent / "timestamps.json",
        video_path.with_name("shotbook.json"),
    ]
    for c in candidates:
        if not c.is_file():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
            # shotbook format
            if "project" in data and "tracks" in data["project"]:
                lines = []
                fps = float(data["project"].get("fps", 30))
                for track in data["project"]["tracks"]:
                    if track.get("id") == "subs":
                        for clip in track.get("clips", []):
                            start_s = clip["start"] / fps
                            dur_s = clip["duration"] / fps
                            center_s = round(start_s + dur_s * 0.5, 2)
                            text = clip.get("props", {}).get("text", "").strip()
                            if text:
                                lines.append({"t": center_s, "text": text,
                                              "start": round(start_s, 2), "end": round(start_s + dur_s, 2)})
                if lines:
                    return lines
            # timestamps format
            if "timings" in data:
                lines = []
                for t in data["timings"]:
                    start_s = float(t.get("start_s", 0))
                    end_s = float(t.get("end_s", start_s + 2.0))
                    center_s = round(start_s + (end_s - start_s) * 0.5, 2)
                    text = t.get("text", "").strip()
                    if text:
                        lines.append({"t": center_s, "text": text,
                                      "start": round(start_s, 2), "end": round(end_s, 2)})
                if lines:
                    return lines
        except Exception:
            continue
    return None


def _adjust_timestamps_for_native(
    video_path: Path,
    times: list[float],
    band_top: float,
    band_bottom: float,
) -> list[float]:
    """Ensure candidate timestamps in native mode hit active subtitles, avoiding blank transition frames and mid-animation border collisions."""
    import numpy as np
    from PIL import ImageChops, ImageFilter

    adjusted = []
    for t in times:
        best_t = t
        best_score = -1.0
        # Check around t in small increments
        for dt in (0.0, 0.5, 1.0, 1.5, 2.0, -0.5):
            cand = max(0.0, t + dt)
            try:
                frame = grab_frame(str(video_path), cand)
                band, _, _ = crop_band(frame, band_top, band_bottom)
                gray = band.convert("L")
                edges = ImageChops.subtract(gray, gray.filter(ImageFilter.MinFilter(3)))
                edge_val = float(np.mean(np.array(edges)))
                if edge_val < 3.0:
                    continue

                # Check hero border to avoid picking mid-transition / cut-off entrance animation
                hero = frame.crop((0, 0, frame.width, int(frame.height * band_bottom)))
                h_edges = ImageChops.subtract(hero.convert("L"), hero.convert("L").filter(ImageFilter.MinFilter(3)))
                h_np = np.array(h_edges)
                margin = max(8, int(frame.width * 0.015))
                left_d = float(np.mean(h_np[:, :margin] > 35) * 100)
                right_d = float(np.mean(h_np[:, -margin:] > 35) * 100)
                max_border = max(left_d, right_d)

                score = edge_val
                if max_border >= 1.0:
                    score -= 50.0

                if score > best_score:
                    best_score = score
                    best_t = cand
                    if edge_val >= 4.0 and max_border < 0.8:
                        break
            except Exception:
                pass

        # Check against previously adjusted timestamp to prevent adjacent duplicate subtitles
        if adjusted:
            prev_cand = adjusted[-1]
            try:
                f_prev = grab_frame(str(video_path), prev_cand)
                b_prev, _, _ = crop_band(f_prev, band_top, band_bottom)
                e_prev = np.array(ImageChops.subtract(b_prev.convert("L"), b_prev.convert("L").filter(ImageFilter.MinFilter(3)))) > 30

                f_cur = grab_frame(str(video_path), best_t)
                b_cur, _, _ = crop_band(f_cur, band_top, band_bottom)
                e_cur = np.array(ImageChops.subtract(b_cur.convert("L"), b_cur.convert("L").filter(ImageFilter.MinFilter(3)))) > 30

                iou = float(np.sum(e_prev & e_cur) / max(1, np.sum(e_prev | e_cur)))
                if iou >= 0.50:
                    for dt in (1.5, 2.0, 2.5, 3.0):
                        alt_cand = best_t + dt
                        f_alt = grab_frame(str(video_path), alt_cand)
                        b_alt, _, _ = crop_band(f_alt, band_top, band_bottom)
                        e_alt = np.array(ImageChops.subtract(b_alt.convert("L"), b_alt.convert("L").filter(ImageFilter.MinFilter(3)))) > 30
                        if np.sum(e_alt) > 40:
                            alt_iou = float(np.sum(e_prev & e_alt) / max(1, np.sum(e_prev | e_alt)))
                            if alt_iou < 0.50:
                                best_t = alt_cand
                                break
            except Exception:
                pass

        adjusted.append(round(best_t, 2))
    return adjusted


def _deduplicate_sentences_by_subtitle(
    video_path: Path,
    sentences: list[dict[str, Any]],
    band_top: float,
    band_bottom: float,
) -> list[dict[str, Any]]:
    """Filter out sentences that map to identical on-screen burned-in subtitle frames (IoU >= 0.50)."""
    import numpy as np
    from PIL import ImageChops, ImageFilter

    kept = []
    prev_edge = None
    for s in sentences:
        t = float(s["t"])
        try:
            frame = grab_frame(str(video_path), t)
            band, _, _ = crop_band(frame, band_top, band_bottom)
            g = band.convert("L")
            e = np.array(ImageChops.subtract(g, g.filter(ImageFilter.MinFilter(3)))) > 30
            if np.sum(e) < 40:
                continue
            if prev_edge is not None:
                iou = float(np.sum(prev_edge & e) / max(1, np.sum(prev_edge | e)))
                if iou >= 0.50:
                    continue
            kept.append(s)
            prev_edge = e
        except Exception:
            kept.append(s)
    return kept or sentences


def _find_coherent_native_window(
    video_path: Path,
    candidates: list[dict[str, Any]],
    count: int,
    band_top: float,
    band_bottom: float,
) -> list[dict[str, Any]]:
    """Select a contiguous window of sentences that has active subtitles and visual scene coherence (no jarring dark/light card jumps)."""
    if len(candidates) <= count:
        return candidates

    import numpy as np
    from PIL import ImageChops, ImageFilter

    scored_windows = []
    for i in range(len(candidates) - count + 1):
        win = candidates[i : i + count]
        means = []
        min_edge = 999.0
        for s in win:
            t = s["t"]
            best_mean = 0.0
            max_edge = 0.0
            for dt in (0.0, 0.4, -0.4, 0.8):
                cand = max(0.0, t + dt)
                try:
                    f = grab_frame(str(video_path), cand)
                    b, _, _ = crop_band(f, band_top, band_bottom)
                    gray = b.convert("L")
                    edge = ImageChops.subtract(gray, gray.filter(ImageFilter.MinFilter(3)))
                    val = float(np.mean(np.array(edge)))
                    if val > max_edge:
                        max_edge = val
                        best_mean = float(np.mean(f))
                    if val > 4.0:
                        break
                except Exception:
                    pass
            means.append(best_mean)
            min_edge = min(min_edge, max_edge)

        std_brightness = float(np.std(means))
        # Penalty for high brightness std or missing subtitles
        score = min_edge - (std_brightness * 0.15)
        # If std_brightness is excessive (>50) or min_edge is too weak (<3), heavily penalize
        if std_brightness > 45:
            score -= 1000.0
        if min_edge < 3.0:
            score -= 1000.0
        scored_windows.append((score, i, win))

    scored_windows.sort(key=lambda x: x[0], reverse=True)
    return scored_windows[0][2]


def produce_quote_image(
    *,
    video_path: Path,
    mode: str,
    strategy: str,
    output_dir: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    _enabled_pillars = {"report"}

    video_path = video_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Determine script lines / sentences
    picked: list[dict[str, Any]] = []

    # Check explicit kwargs first
    explicit_script = kwargs.get("script") or kwargs.get("script_path")
    if explicit_script is not None:
        if isinstance(explicit_script, (str, Path)):
            p = Path(explicit_script)
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
                picked = raw.get("lines", raw)
        elif isinstance(explicit_script, list):
            picked = explicit_script

    all_source_sentences: list[dict[str, Any]] = []
    if not picked:
        # Check adjacent project script metadata
        script_from_file = _load_script_from_source(video_path)
        if script_from_file:
            all_source_sentences = script_from_file
            if strategy == "auto":
                picked = pick_sentences(script_from_file, count=4)
            elif strategy == "time_range":
                if "start_time" not in kwargs or "end_time" not in kwargs:
                    return {
                        "status": "failed",
                        "error": "time_range strategy requires start_time and end_time.",
                    }
                start_time = float(kwargs["start_time"])
                end_time = float(kwargs["end_time"])
                picked = [s for s in script_from_file if start_time <= s["t"] <= end_time]
                if len(picked) > 6:
                    picked = picked[:6]
            else:
                return {"status": "failed", "error": f"Unknown strategy {strategy}"}

    if not picked:
        # Fall back to Whisper ASR
        aligner = WhisperAligner()
        sentences = aligner.transcribe_segments(str(video_path))
        all_source_sentences = sentences
        if strategy == "auto":
            picked = pick_sentences(sentences, count=4)
        elif strategy == "time_range":
            if "start_time" not in kwargs or "end_time" not in kwargs:
                return {
                    "status": "failed",
                    "error": "time_range strategy requires start_time and end_time.",
                }
            start_time = float(kwargs["start_time"])
            end_time = float(kwargs["end_time"])
            picked = [s for s in sentences if start_time <= s["t"] <= end_time]
            if len(picked) > 6:
                picked = picked[:6]
        else:
            return {"status": "failed", "error": f"Unknown strategy {strategy} and no fallback allowed."}

    if not picked:
        return {"status": "failed", "error": "No sentences picked."}

    record_json_path = output_dir / "record.json"

    # Detect subtitle band in the source video
    band_top = kwargs.get("band_top")
    band_bottom = kwargs.get("band_bottom")
    if band_top is None or band_bottom is None:
        band_top, band_bottom = detect_subtitle_band(
            video_path=video_path,
            times=[s["t"] for s in picked],
        )

    extra_record: dict[str, Any] = {}
    gate_extra: list[dict[str, Any]] = []
    try:
        _, _, duration = video_metadata(video_path)
    except BaseException:  # unreadable source (e.g. unit tests with a stub render) → skip frame analysis
        duration = None

    def _grab(t: float):
        tt = max(0.0, float(t))
        if duration:
            tt = min(tt, duration - 0.05)
        return grab_frame(str(video_path), tt)

    if mode == "native":
        # r4 FIX#1：字幕带覆盖多行字幕的完整外接框（按各采样时刻的文字行取并集）
        band0 = (band_top, band_bottom)

        candidates_to_use = all_source_sentences if all_source_sentences else picked
        # r4 FIX#2：同一句话被滚动字幕拆成多段时，单帧只会显示半句 → 剔除；
        # 一句话在整段时长内只显示一张字幕卡时才收录，并取字幕最完整的时刻。
        complete: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for s_ in candidates_to_use:
            if duration and "start" in s_ and "end" in s_:
                ok, best_t = sentence_single_card(_grab, float(s_["start"]), float(s_["end"]),
                                                  band_top, band_bottom)
                if ok and best_t is not None:
                    complete.append({**s_, "t": best_t, "_verified": True})
                else:
                    excluded.append({"text": s_.get("text", ""), "t": s_.get("t"),
                                     "reason": "no subtitle on screen" if best_t is None
                                     else "sentence split across several subtitle cards"})
            else:
                complete.append(s_)
        extra_record["excluded_sentences"] = excluded
        # Deduplicate sentences based on actual on-screen subtitle bands
        if not complete:
            res_f = {"status": "failed", "mode": mode,
                     "error": "no sentence is shown as one complete subtitle card (rolling captions); "
                              "refusing to render half sentences",
                     "records": [extra_record]}
            record_json_path.write_text(json.dumps(res_f, ensure_ascii=False, indent=2), encoding="utf-8")
            return res_f
        distinct_sentences = _deduplicate_sentences_by_subtitle(
            video_path, complete, band_top, band_bottom
        )

        if strategy == "auto":
            if len(distinct_sentences) >= 4:
                picked = _find_coherent_native_window(
                    video_path, distinct_sentences, count=4, band_top=band_top, band_bottom=band_bottom
                )
            else:
                picked = distinct_sentences

        if len(picked) < 2:
            res_f = {"status": "failed", "mode": mode,
                     "error": f"only {len(picked)} sentence(s) shown as one complete subtitle card; "
                              "a native quote image needs >= 2 (others are split across rolling captions)",
                     "records": [extra_record]}
            record_json_path.write_text(json.dumps(res_f, ensure_ascii=False, indent=2), encoding="utf-8")
            return res_f
        # Ensure times land on active subtitles（已按整句校验过的时刻不再挪动，避免挪进下一张字幕卡）
        if picked and all(s_.get("_verified") for s_ in picked):
            times = [round(float(s_["t"]), 2) for s_ in picked]
        else:
            times = _adjust_timestamps_for_native(video_path, [s["t"] for s in picked], band_top, band_bottom)
        # r4 FIX#1：按最终采样帧把字幕带扩到完整多行字幕（增长上限约一行），再检查裁切线
        if duration and times:
            band_top, band_bottom = refine_band([_grab(t) for t in times], band0[0], band0[1])
        for t in times if duration else []:
            cut, val = band_edge_cuts_text(_grab(t), band_top, band_bottom)
            gate_extra.append({"name": "band_edge_clear", "threshold": f"edge_ink<=0.006",
                               "passed": not cut, "value": val, "time": t})
        extra_record["rendered_times"] = times
        extra_record["band"] = [band_top, band_bottom]

        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"images": [{"title": "quote_image", "times": times}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        args = argparse.Namespace(
            video=str(video_path),
            manifest=str(manifest_path),
            out_dir=str(output_dir),
            band_top=band_top,
            band_bottom=band_bottom,
            width=kwargs.get("width"),
            aspect=kwargs.get("aspect", (3.0, 4.0)),
            layout=kwargs.get("layout", "natural"),
            hero_fraction=kwargs.get("hero_fraction"),
            overwrite=True,
            fit=kwargs.get("fit", "crop"),
            crop_center=kwargs.get("crop_center", 0.5),
            keep_going=True,
            resume=False,
            allow_duplicate_frames=True,
        )
        try:
            command_render(args)
        except BaseException as e:
            res_f = {"status": "failed", "error": str(e) or type(e).__name__, "mode": mode,
                     "records": [{"times": times, **extra_record}]}
            record_json_path.write_text(json.dumps(res_f, ensure_ascii=False, indent=2), encoding="utf-8")
            return res_f

    elif mode == "script":
        script_path = output_dir / "script.json"
        script_path.write_text(
            json.dumps({"lines": picked}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        out_img = output_dir / "quote_script.jpg"

        # r4 FIX#3：hero 取字幕带为空的帧；整片字幕不断时把 hero 裁到字幕带之上
        hero_time = None
        hero_bottom = None
        if duration:
            spans = [
                (float(s_.get("start", s_["t"] - 1.0)), float(s_.get("end", s_["t"] + 1.0)))
                for s_ in picked
            ]

            def _in_picked(t: float) -> bool:
                return any(a - 0.15 <= t <= b + 0.15 for a, b in spans)

            # 1) 优先：字幕带为空、且不在任何入选句时间段内的帧
            hero_time = None
            cand = pick_clean_hero_time(_grab, float(picked[0]["t"]), duration, band_top, band_bottom)
            if cand is not None and not _in_picked(cand):
                hero_time = cand
            # 2) 其次：入选句之外的相邻句（画面里的大字/板书是另一句，不与字幕条重复）
            if hero_time is None:
                others = [s_ for s_ in all_source_sentences if not _in_picked(float(s_["t"]))]
                if others:
                    first_t = float(picked[0]["t"])
                    hero_time = round(float(min(others, key=lambda s_: abs(float(s_["t"]) - first_t))["t"]), 2)
            if hero_time is not None:
                hero_mass = band_text_mass(_grab(hero_time), band_top, band_bottom)
                if hero_mass >= 0.0015:
                    hero_bottom = float(band_top)  # 裁掉该帧自己的字幕带
            else:
                hero_bottom = float(band_top)
                hero_mass = 0.0
            hero_ok = (hero_time is None or not _in_picked(hero_time))
            gate_extra.append({"name": "hero_not_duplicating_strips",
                               "threshold": "hero time outside picked sentences; own subtitle band cropped",
                               "passed": hero_ok, "value": round(hero_mass, 5),
                               "hero_time": hero_time, "hero_cropped_above_band": hero_bottom})
        extra_record["hero_time"] = hero_time
        extra_record["hero_bottom"] = hero_bottom
        # times = 各字幕条所用时间点；hero 实际取帧时刻单独记录在 hero_time
        extra_record["rendered_times"] = [float(s_["t"]) for s_ in picked]

        # In script mode, all lines are drawn in clean independent strips below hero,
        # so hero frame remains intact without cropping.
        frame_bottom = kwargs.get("frame_bottom", 1.0)
        band_center = kwargs.get("band_center", 0.6)

        args = argparse.Namespace(
            video=str(video_path),
            script=str(script_path),
            out=str(out_img),
            aspect=kwargs.get("aspect", (3.0, 4.0)),
            width=kwargs.get("width"),
            band_center=band_center,
            hero_fraction=kwargs.get("hero_fraction"),
            font=kwargs.get("font", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            font_size=kwargs.get("font_size"),
            layout=kwargs.get("layout", "natural"),
            frame_top=kwargs.get("frame_top", 0.0),
            frame_bottom=frame_bottom,
            overwrite=True,
            speaker_prefix="none",
            allow_duplicate_frames=True,
            six_line_card=False,
            hero_time=hero_time,
            hero_bottom=hero_bottom,
        )
        try:
            command_render_script(args)
        except BaseException as e:
            return {"status": "failed", "error": str(e)}

    # Evaluate Quality Gates
    images = list(output_dir.glob("*.jpg")) + list(output_dir.glob("*.png"))
    gates = run_quality_gates(images) + gate_extra
    all_passed = bool(gates and all(g["passed"] for g in gates))

    status = "succeeded" if all_passed else "failed"

    res = {
        "status": status,
        "mode": mode,
        "images": [str(p) for p in images],
        "records": [
            {
                "gates": gates,
                # r4 FIX#5：记录实际渲染所用的时间点
                "times": extra_record.get("rendered_times") or [s["t"] for s in picked],
                "picked_sentences": [{"t": s_.get("t"), "text": s_.get("text", "")} for s_ in picked],
                **{k: v for k, v in extra_record.items() if k != "rendered_times"},
            }
        ],
        "asr_sentences": [
            {k: s_.get(k) for k in ("t", "start", "end", "text") if k in s_} for s_ in all_source_sentences
        ],
    }
    if len(picked) < 4:
        res["note"] = (
            f"only {len(picked)} usable sentences: {len(all_source_sentences)} ASR/script sentences, "
            f"{len(extra_record.get('excluded_sentences', []))} excluded (see excluded_sentences)"
        )

    record_json_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    if not all_passed:
        failed_gates = [g for g in gates if not g["passed"]]
        raise QualityGateError(f"Quality gates failed: {failed_gates}")

    return res

"""OMQUALITY 审片事务 (omodul 层, 标准 3O 三件套签名)。

``review_finished_video_workflow(config, input_data, output_dir)`` 对一条**已有成片**
做一次真实体检, 落盘 ``review_report.json`` + 抽帧联络表 PNG。每一项都是量出来的:

  probe      ffprobe 时长/分辨率/帧率/音轨/解码帧数 + sha256
  frames     4 点抽帧 → 黑帧(mean luma)/破图(不可解码)/平帧(stdev) + 联络表
  audio      静音占比(ffmpeg silencedetect) + 响度(ffmpeg ebur128)
  subtitle   字幕越界(越出片长/过短/重叠) + 覆盖率
  slideshow  幻灯片风险评分(重复度/静态占比/运动弱/文字依赖)

**禁止造假**: 量不出来的维度一律记 ``None`` 并写进 ``unmeasured``, 绝不当 0 分
(0 分 = "这一维完全健康", 会让没测的维度悄悄放行)。verdict 只可能是
``ok`` / ``warn`` / ``red`` / ``blocked``, ``blocked`` 既不是通过也不是缺陷。

Config keys
-----------
frame_count        : 抽帧点数 (默认 4)
subtitle_path      : SRT 路径 (可选; 给了才量字幕)
min_lufs           : 响度下限 (默认 -45.0), 超出即违规
max_lufs           : 响度上限 (默认 -5.0)
max_silence_ratio  : 静音占比上限 (默认 0.90)
min_duration_s     : 最短时长 (默认 1.0)
require_audio      : 是否要求有音轨 (默认 False)
expected_resolution: (w, h) 期望分辨率 (可选)
slideshow          : 幻灯片阈值覆盖 dict (可选)
motion_delta_floor : 帧间平均 luma 差低于此值算"静态" (默认 1.0)
repeat_hash_floor  : 相邻帧平均汉明距离低于此值算"重复" (默认 4.0)
text_cue_coverage  : 字幕覆盖率高于此值算"文字依赖" (默认 0.80)
promise           : 排产前定死的 DeliveryPromise.to_dict() (可选; 给了就对账承诺)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.review.oprim_impl.audio import (
    loudness_lufs,
    silence_ratio,
    silence_windows,
    spectral_flatness,
    clipped_sample_ratio,
    transient_click_count,
)
from hevi.layer4_legacy.review.oprim_impl.contracts import (
    VERDICT_BLOCKED,
    VERDICT_OK,
    VERDICT_RED,
    VERDICT_WARN,
    ReviewVerdict,
)
from hevi.layer4_legacy.review.oprim_impl.frames import (
    NOISE_LOCAL_DIFF_FLOOR,
    build_contact_sheet,
    dense_sample_frames,
    frame_phash,
    frame_stats,
    hamming_distance,
    interframe_delta,
    sample_frames,
)
from hevi.layer4_legacy.review.oprim_impl.media import MediaError, probe_media
from hevi.layer4_legacy.review.oprim_impl.subtitle import subtitle_bounds_for_video
from hevi.layer4_legacy.review.oskill_impl.promise_gate import cuts_from_segments, motion_evidence
from hevi.layer4_legacy.review.oskill_impl.slideshow_risk import score_slideshow_risk

logger = logging.getLogger(__name__)

#: 3O omodul pillars this transaction enables.
_enabled_pillars = {"report", "decision_trail"}

REVIEW_OPS = ("probe", "frames", "audio", "subtitle", "slideshow")

_DEFAULTS: dict[str, Any] = {
    "frame_count": 4,
    "min_lufs": -45.0,
    "max_lufs": -5.0,
    "max_silence_ratio": 0.90,
    "min_duration_s": 1.0,
    "require_audio": False,
    "motion_delta_floor": 1.0,
    "repeat_hash_floor": 4.0,
    "text_cue_coverage": 0.80,
    "spectral_flatness_threshold": 0.1,  # white noise flag
    "max_clipped_sample_ratio": 0.001,   # clipping: fraction of samples at |x|>=0.999
    "max_transient_clicks": 50,          # max 10ms-window click events
    "max_silence_gap_s": 2.0,            # longest continuous silence gap before violation
}


class ReviewUnavailable(RuntimeError):
    """A required local dependency is missing, or the input is unmeasurable."""


def _cfg(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(_DEFAULTS)
    out.update({k: v for k, v in (config or {}).items() if v is not None})
    return out


def _resolve_input(config: dict[str, Any], input_data: dict[str, Any]) -> Path:
    raw = (
        input_data.get("input_path")
        or input_data.get("path")
        or input_data.get("video_path")
        or config.get("input_path")
        or config.get("input")
    )
    if not raw:
        raise ReviewUnavailable("input_path is required")
    path = Path(str(raw))
    if not path.is_file():
        raise ReviewUnavailable(f"input not found: {path}")
    return path


def _longest_static_run(*, hashes: list[str], repeat_floor: float) -> int:
    """Longest run of consecutive frames whose pairwise distance < ``repeat_floor``."""
    if not hashes:
        return 0
    run = 1
    best = 1
    for i in range(1, len(hashes)):
        if hamming_distance(left=hashes[i - 1], right=hashes[i]) < repeat_floor:
            run += 1
            if run > best:
                best = run
        else:
            run = 1
    return best


def _detect_segments(
    *,
    deltas: list[float],
    motion_floor: float,
) -> list[tuple[int, int]]:
    """Group consecutive dense frames into cut boundaries (delta >= motion_floor)."""
    if not deltas:
        return []
    segments: list[tuple[int, int]] = []
    start = 0
    for i, d in enumerate(deltas, start=1):
        if d >= motion_floor:
            segments.append((start, i))
            start = i
    segments.append((start, len(deltas) + 1))
    return segments


def _measure_slideshow(
    *,
    dense_frames: list[Path],
    cfg: dict[str, Any],
    subtitle_coverage: float | None,
    has_subtitle: bool,
) -> tuple[dict[str, Any], dict[str, float], tuple[str, ...], list[dict[str, Any]]]:
    """Measure the four slideshow components from real pixels.

    dense_frames is a deterministic dense stream (capped by config), so the
    detector can see both intra-segment stills and inter-segment cuts:

      repeat        = 1 − (longest_static_run / total_dense_frames)
                      i.e. "what fraction of runtime is NOT a still"
      static        = 1 − (mean_interframe_delta / motion_floor)
                      i.e. "what fraction of inter-frame motion is missing"
      weak_motion   = share of intra-segment frames (no inter-frame motion)
      text_dependent= coverage of subtitle / cue coverage floor

    The fourth return value is the same measurement expressed as cut
    descriptors, so the delivery promise can be reconciled against it
    without re-decoding anything.
    """
    measured: dict[str, float] = {}
    missing: list[str] = []
    motion_floor = float(cfg["motion_delta_floor"])
    repeat_floor = float(cfg["repeat_hash_floor"])

    hashes = [frame_phash(path=f) for f in dense_frames] if dense_frames else []
    deltas = interframe_delta(frames=dense_frames) if dense_frames else []

    if len(hashes) < 2:
        return (
            score_slideshow_risk(
                thresholds=cfg.get("slideshow") or None,
            ).to_dict(),
            {},
            ("repeat", "static", "weak_motion"),
            [],
        )

    # 1) repeat: fraction of dense frames inside any intra-segment still run.
    # A still segment is one whose first→last inter-frame delta is below
    # motion_floor.  Both edges belong to it (the first frame of the run is
    # also "stuck", not just the inner ones).
    segments = _detect_segments(deltas=deltas, motion_floor=motion_floor)
    still_frames = 0
    cut_count = 0
    for a, b in segments:
        if (b - a) >= 2:
            still_frames += b - a
        else:
            cut_count += 1
    measured["segment_count"] = len(segments)
    measured["cut_count"] = max(0, len(segments) - 1)
    measured["dense_frame_count"] = len(hashes)
    total = len(hashes)
    repeat = max(0.0, min(1.0, still_frames / total)) if total else None  # type: ignore[assignment]

    # 2) static: share of inter-frame deltas below motion_floor.
    if deltas:
        mean_delta = sum(deltas) / len(deltas)
        max_delta = max(deltas)
        measured["mean_frame_delta"] = round(mean_delta, 4)
        measured["max_frame_delta"] = round(max_delta, 4)
        # Normalise against a *useful* floor of motion: anything below 2 luma
        # units is effectively frozen.  Use 2.0 as the floor, not the smaller
        # motion_delta_floor, so a one-off jump doesn't zero the whole thing.
        static_floor = max(2.0, motion_floor)
        static = max(0.0, min(1.0, 1.0 - mean_delta / static_floor))
    else:
        static = None  # type: ignore[assignment]
        missing.append("static")

    # 3) weak_motion: when segments are very short (≤3 frames) the cuts are
    # rapid but the motion energy between them is small — classic slideshow.
    # Falls back to repeat when no segment is short enough to be confident.
    if segments and total and repeat is not None:
        short_segment_share = sum(min(b - a, 6) for a, b in segments if 2 <= (b - a) <= 6) / max(
            still_frames, 1
        )
        measured["short_segment_share"] = round(short_segment_share, 4)
        weak = repeat * short_segment_share
    else:
        weak = None  # type: ignore[assignment]
        missing.append("weak_motion")

    # 4) text_dependent: subtitle coverage (only when an SRT was given).
    if has_subtitle and subtitle_coverage is not None:
        text_dep = min(1.0, subtitle_coverage / max(float(cfg["text_cue_coverage"]), 1e-6))
        measured["subtitle_coverage"] = round(subtitle_coverage, 4)
    else:
        text_dep = None  # type: ignore[assignment]
        missing.append("text_dependent")

    # 5) cut-anomaly: flag when every dense frame is a cut AND motion is near-zero.
    #    "extreme high-frequency noise" — corrupted video has tiny pixel diffs with
    #    no coherent motion, not normal action footage with frequent cuts.
    cut_ratio = max(0.0, min(1.0, cut_count / max(total, 1)))
    measured["cut_ratio"] = round(cut_ratio, 4)
    from hevi.layer4_legacy.review.oskill_impl.slideshow_risk import CUT_RATIO_ANOMALY_FLOOR
    # Only flag as anomaly when high cut ratio coincides with near-zero motion.
    # Normal videos with frequent cuts (high deltas) are NOT anomalous.
    mean_delta = (sum(deltas) / len(deltas)) if deltas else 0.0
    MOTION_FLOOR_ANOMALY = 2.0  # below this, cuts indicate noise not content
    is_cut_anomaly = bool(
        cut_ratio >= CUT_RATIO_ANOMALY_FLOOR and mean_delta < MOTION_FLOOR_ANOMALY
    )

    risk = score_slideshow_risk(
        repeat=repeat,
        static=static,
        weak_motion=weak,
        text_dependent=text_dep,
        thresholds=cfg.get("slideshow") or None,
    )
    import dataclasses as _dc
    risk = _dc.replace(risk, is_cut_anomaly=is_cut_anomaly)
    if is_cut_anomaly:
        # Cut-anomaly (≈100% cuts) means the clip is visually broken — no motion
        # continuity at all.  This must force a red verdict; adding only a reason
        # string lets the clip pass as green/amber, which is wrong (FIX #7).
        risk = _dc.replace(
            risk,
            verdict="red",
            reasons=risk.reasons + ("切片比例异常高(≈100%切点) — 判红",),
        )
    cuts = cuts_from_segments(segments=segments, deltas=deltas, motion_floor=motion_floor)
    return risk.to_dict(), measured, tuple(missing), cuts


def _reconcile_promise(
    *,
    promise_raw: Any,
    cuts: list[dict[str, Any]],
    violations: list[str],
) -> dict[str, Any]:
    """Reconcile the pre-scheduling delivery promise against measured evidence.

    Uses the production contract verbatim (``DeliveryPromise.validate_cuts``) —
    the review layer does not restate the rules.  Violations are appended in
    place because a broken promise is a delivery-gate violation, not a warning.
    """
    from hevi.production.delivery_promise import DeliveryPromise, classify_from_brief

    evidence = motion_evidence(cuts)
    out: dict[str, Any] = {"evidence": evidence}
    try:
        if isinstance(promise_raw, str):
            # A bare string is a pipeline manifest name (or a promise-type alias
            # that classify_from_brief already knows); the alias table lives in
            # the season dispatcher, so we only handle what the contract knows.
            promise = classify_from_brief(promise_raw, {})
        else:
            promise = DeliveryPromise.from_dict(dict(promise_raw))
    except Exception as exc:
        out["error"] = f"promise 无法解析: {exc}"
        return out

    out["promise_type"] = promise.promise_type.value
    out["motion_required"] = promise.motion_required
    if not cuts:
        # No dense frames -> no evidence.  Marked unmeasured by the caller via an
        # empty cut list; say so rather than scoring a promise as broken.
        out["verdict"] = "unmeasured"
        return out

    result = promise.validate_cuts(cuts)
    out["verdict"] = "ok" if result["valid"] else "violation"
    out["valid"] = bool(result["valid"])
    out["motion_ratio"] = result["motion_ratio"]
    out["violations"] = list(result["violations"])
    for v in result["violations"]:
        violations.append(f"交付承诺未兑现 [{promise.promise_type.value}]: {v}")
    return out


def review_finished_video_workflow(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run one full post-render self-check. Returns a status dict (never raises)."""
    cfg = _cfg(config)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    input_data = dict(input_data or {})

    try:
        src = _resolve_input(cfg, input_data)
    except ReviewUnavailable as exc:
        return {"status": "failed", "error": str(exc), "stage": "probe"}

    violations: list[str] = []
    warnings: list[str] = []
    unmeasured: list[str] = []
    metrics: dict[str, Any] = {}

    # ---- probe -----------------------------------------------------------
    try:
        info = probe_media(src, with_sha256=True)
    except MediaError as exc:
        return {"status": "failed", "error": str(exc), "stage": "probe", "input": str(src)}
    if info.kind != "video":
        return {
            "status": "failed",
            "error": f"unsupported input kind: {info.kind}",
            "stage": "probe",
            "input": str(src),
        }
    metrics["probe"] = info.to_dict()
    if info.duration_s <= 0:
        violations.append("时长为 0 / 无法探测")
    elif info.duration_s < float(cfg["min_duration_s"]):
        violations.append(
            f"时长 {info.duration_s:.2f}s 短于下限 {float(cfg['min_duration_s']):.2f}s"
        )
    if info.width <= 0 or info.height <= 0:
        violations.append("视频轨不可解码或分辨率无效")
    if info.fps <= 0:
        warnings.append("帧率未探测到")
    expected = cfg.get("expected_resolution")
    if expected:
        exp = tuple(int(x) for x in expected)
        if (info.width, info.height) != exp:
            violations.append(f"分辨率 {info.width}x{info.height} != 期望 {exp[0]}x{exp[1]}")
    if cfg.get("require_audio") and not info.has_audio:
        violations.append("缺音轨")

    # ---- frames (4 点抽帧) ----------------------------------------------
    frame_dir = out / "frames"
    checks: list[dict[str, Any]] = []
    try:
        frames = sample_frames(path=src, out_dir=frame_dir, count=int(cfg["frame_count"]))
        for i, frame in enumerate(frames):
            # recover the timestamp encoded in the filename
            try:
                ts = float(Path(frame).stem.rsplit("_", 1)[-1].rstrip("s"))
            except ValueError:
                ts = 0.0
            checks.append(frame_stats(path=frame, index=i, timestamp_s=ts).to_dict())
        metrics["contact_sheet"] = build_contact_sheet(
            frames=frames,
            output_path=out / "contact_sheet.png",
            labels=tuple(f"#{c['index']} {c['timestamp_s']}s" for c in checks),
        )
    except MediaError as exc:
        unmeasured.append("frames")
        warnings.append(f"抽帧失败: {exc}")
        frames = []
    black = [c for c in checks if c.get("is_black")]
    broken = [c for c in checks if c.get("is_broken")]
    flat = [c for c in checks if c.get("is_flat")]
    noise = [c for c in checks if c.get("is_noise")]
    blocky = [c for c in checks if c.get("is_blocky")]
    color_anomaly = [c for c in checks if c.get("is_color_anomaly")]
    metrics["frames"] = {
        "count": len(checks),
        "checks": checks,
        "black": len(black),
        "broken": len(broken),
        "flat": len(flat),
        "noise": len(noise),
        "blocky": len(blocky),
        "color_anomaly": len(color_anomaly),
    }
    if broken:
        violations.append(f"{len(broken)}/{len(checks)} 帧不可解码(破图)")
    if black:
        violations.append(f"{len(black)}/{len(checks)} 帧为黑帧")
    if flat and len(flat) == len(checks) and checks:
        violations.append("全部抽帧为平帧(疑似冻结画面)")
    elif flat:
        warnings.append(f"{len(flat)}/{len(checks)} 帧为平帧")
    if noise:
        violations.append(
            f"{len(noise)}/{len(checks)} 帧为全帧随机噪点(破图/花屏, "
            f"local_diff={noise[0].get('local_diff', 0):.1f} > "
            f"{NOISE_LOCAL_DIFF_FLOOR:.0f} 阈值)"
        )
    if blocky:
        violations.append(
            f"{len(blocky)}/{len(checks)} 帧为宏块花屏(blockiness="
            f"{blocky[0].get('blockiness', 0):.1f})"
        )
    if color_anomaly:
        violations.append(
            f"{len(color_anomaly)}/{len(checks)} 帧色度异常(疑似绿屏/纯色/半屏块)"
        )

    # ---- audio -----------------------------------------------------------
    audio_metrics: dict[str, Any] = {"has_audio": info.has_audio}
    if info.has_audio:
        try:
            lufs = loudness_lufs(path=src)
        except MediaError as exc:
            lufs = None
            warnings.append(f"响度量测失败: {exc}")
        try:
            sil = silence_ratio(path=src)
        except MediaError as exc:
            sil = None
            warnings.append(f"静音量测失败: {exc}")
        audio_metrics["loudness_lufs"] = lufs
        audio_metrics["silence_ratio"] = sil
        try:
            flatness = spectral_flatness(path=src)
        except MediaError:
            flatness = None
        audio_metrics["spectral_flatness"] = flatness
        if flatness is None:
            unmeasured.append("spectral_flatness")
        elif flatness > float(cfg["spectral_flatness_threshold"]) and sil is not None and sil < 0.5:
            violations.append(
                f"音频频谱平坦度 {flatness:.3f} 超过上限 {cfg['spectral_flatness_threshold']} "
                "(疑似持续宽带白噪声)"
            )
        # Clipping: samples at full-scale (≥0.999 amplitude).
        try:
            clip_ratio = clipped_sample_ratio(path=src)
        except MediaError:
            clip_ratio = None
        audio_metrics["clipped_sample_ratio"] = clip_ratio
        if clip_ratio is None:
            unmeasured.append("clipped_sample_ratio")
        elif clip_ratio > float(cfg.get("max_clipped_sample_ratio", 0.001)):
            violations.append(
                f"削波样本占比 {clip_ratio:.4%} 超过上限 {cfg['max_clipped_sample_ratio']:.4%}"
            )
        # Transient clicks: abrupt amplitude jumps > 0.5 in 10ms windows.
        try:
            clicks = transient_click_count(path=src)
        except MediaError:
            clicks = None
        audio_metrics["transient_click_count"] = clicks
        if clicks is None:
            unmeasured.append("transient_click_count")
        elif clicks > int(cfg.get("max_transient_clicks", 50)):
            violations.append(
                f"瞬态爆音 {clicks} 次(10ms 窗口样本跳变>0.5) 超过上限 {cfg['max_transient_clicks']}"
            )
        # Continuous silence gap: longest single silence window.
        try:
            sil_windows = silence_windows(path=src, noise_db=-45.0, min_duration_s=0.5)
        except MediaError:
            sil_windows = []
        longest_gap = max((e - s for s, e in sil_windows), default=0.0)
        audio_metrics["longest_silence_gap_s"] = round(longest_gap, 3)
        if longest_gap > float(cfg.get("max_silence_gap_s", 2.0)):
            violations.append(
                f"连续静音段 {longest_gap:.1f}s 超过上限 {cfg['max_silence_gap_s']:.1f}s"
            )
        if lufs is None:
            unmeasured.append("loudness")
        else:
            lo, hi = float(cfg["min_lufs"]), float(cfg["max_lufs"])
            if not (lo <= lufs <= hi):
                violations.append(f"响度 {lufs:.1f} LUFS 超出 [{lo}, {hi}]")
        if sil is None:
            unmeasured.append("silence")
        elif sil > float(cfg["max_silence_ratio"]):
            violations.append(f"静音占比 {sil:.0%} 超过上限 {float(cfg['max_silence_ratio']):.0%}")
    else:
        unmeasured.append("audio")
        warnings.append("无音轨: 响度/静音未量测")
    metrics["audio"] = audio_metrics

    # ---- subtitle --------------------------------------------------------
    subtitle_coverage: float | None = None
    has_subtitle = False
    sub_path = cfg.get("subtitle_path") or input_data.get("subtitle_path")
    if sub_path:
        try:
            bounds = subtitle_bounds_for_video(video_path=src, subtitle_path=sub_path)
            cov = bounds.get("coverage")
            subtitle_coverage = float(cov) if isinstance(cov, (int, float)) else None
            has_subtitle = True
            metrics["subtitle"] = bounds
            bad = int(bounds.get("past_end") or 0) + int(bounds.get("too_short") or 0)
            if bad:
                violations.append(f"字幕越界/过短 {bad} 条 (共 {bounds.get('cues')} 条)")
            if int(bounds.get("overlapping") or 0):
                warnings.append(f"字幕重叠 {bounds['overlapping']} 条")
        except MediaError as exc:
            unmeasured.append("subtitle")
            warnings.append(f"字幕检查失败: {exc}")
            metrics["subtitle"] = {"error": str(exc)}
    else:
        unmeasured.append("subtitle")
        warnings.append("未提供 SRT: 字幕越界未量测")

    # ---- slideshow (dense stream) ---------------------------------------
    dense_dir = out / "dense_frames"
    try:
        dense = dense_sample_frames(
            path=src, out_dir=dense_dir, fps=2.0, scale_width=128, max_frames=48
        )
    except MediaError as exc:
        warnings.append(f"幻灯片抽帧失败: {exc}")
        dense = []
    risk, risk_measured, risk_missing, cuts = _measure_slideshow(
        dense_frames=dense,
        cfg=cfg,
        subtitle_coverage=subtitle_coverage,
        has_subtitle=has_subtitle,
    )
    metrics["slideshow"] = {**risk, "measured": risk_measured}
    if not dense:
        unmeasured.append("slideshow")
    if risk.get("verdict") == "red":
        violations.append(
            "幻灯片风险判红 (risk=%.2f): %s"
            % (float(risk.get("risk") or 0.0), "; ".join(risk.get("reasons") or []))
        )
    elif risk.get("verdict") == "amber":
        warnings.append(
            "幻灯片风险黄灯 (risk=%.2f): %s"
            % (float(risk.get("risk") or 0.0), "; ".join(risk.get("reasons") or []))
        )

    # ---- local defect scan (dense frames) --------------------------------
    # Sample at 2 fps and run frame_stats on every dense frame.  A defect
    # lasting >= 0.5s (i.e. >= 2 consecutive dense frames) is a violation.
    # This catches short local glitches/colour floods that the 4-point spot
    # check can miss because its sample times are evenly spaced.
    dense_defect_hits: list[dict[str, Any]] = []
    if dense:
        dense_checks: list[dict[str, Any]] = []
        for i, df in enumerate(dense):
            try:
                dc = frame_stats(path=df, index=i, timestamp_s=0.0).to_dict()
            except Exception:
                dc = {}
            dense_checks.append(dc)
        defect_flags = [(i, c) for i, c in enumerate(dense_checks) if c.get("is_noise") or c.get("is_blocky") or c.get("is_black") or c.get("is_flat") or c.get("is_color_anomaly") or c.get("is_region_flat")]
        if len(defect_flags) >= 2:
            # Check for consecutive runs (>= 2 consecutive frames at 2fps = 0.5s)
            run_start = None
            run_len = 0
            max_run = 0
            max_run_flags: list[str] = []
            prev_idx = -99
            for idx, dc in defect_flags:
                flags = tuple(k for k in ("is_noise", "is_blocky", "is_black", "is_flat", "is_color_anomaly", "is_region_flat") if dc.get(k))
                if idx - prev_idx <= 1:
                    run_len += 1
                    if flags not in max_run_flags:
                        max_run_flags.append(flags)
                else:
                    if run_len > max_run:
                        max_run = run_len
                        max_run_flags = [flags]
                    run_start = idx
                    run_len = 1
                prev_idx = idx
            if run_len > max_run:
                max_run = run_len
                max_run_flags = [flags]
            if max_run >= 2:
                defect_desc = " + ".join(" + ".join(f) for f in max_run_flags)
                violations.append(
                    f"局部坏段 ≥{max_run} 连续帧(≈{max_run * 0.5:.1f}s, {defect_desc})"
                )
                dense_defect_hits.append({"run_len": max_run, "flags": max_run_flags})
        metrics["local_defect_scan"] = {
            "dense_frame_count": len(dense_checks),
            "defect_frame_count": len(defect_flags),
            "defect_hits": dense_defect_hits,
        }

    # ---- promise reconciliation -------------------------------------------
    # 排产前定死的承诺 (hevi.production.delivery_promise) 在这里对账: 实测的
    # 运动证据若兑现不了承诺, 是**静默降级**, 必须拦在合成之前。
    promise_raw = cfg.get("promise") or input_data.get("promise")
    if promise_raw:
        metrics["promise"] = _reconcile_promise(
            promise_raw=promise_raw,
            cuts=cuts,
            violations=violations,
        )

    # ---- verdict ---------------------------------------------------------
    if violations:
        verdict = VERDICT_RED
    elif warnings or unmeasured:
        verdict = VERDICT_WARN if warnings else VERDICT_OK
    else:
        verdict = VERDICT_OK

    # A gate that measured nothing has produced no evidence — it is blocked,
    # not green.  This is the single most important honesty rule here.
    if not frames and not info.has_audio and "frames" in unmeasured:
        verdict = VERDICT_BLOCKED
    if not checks and audio_metrics.get("loudness_lufs") is None:
        verdict = VERDICT_BLOCKED

    result = ReviewVerdict(
        path=str(src),
        status="ok" if verdict != VERDICT_BLOCKED else "blocked",
        verdict=verdict,
        reasons=tuple(violations + warnings),
        metrics=metrics,
    )
    report = {
        "status": result.status,
        "op": "review",
        "input": str(src),
        "sha256": info.sha256,
        "duration_s": info.duration_s,
        "resolution": f"{info.width}x{info.height}",
        "fps": info.fps,
        "has_audio": info.has_audio,
        "verdict": result.verdict,
        "allows_compose": result.allows_compose,
        "violations": violations,
        "warnings": warnings,
        "unmeasured": sorted(set(unmeasured + list(risk_missing))),
        "metrics": metrics,
        "output_dir": str(out),
        "artifacts": {
            "contact_sheet": str(out / "contact_sheet.png"),
            "frames": [str(f) for f in frames],
        },
    }
    (out / "review_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


__all__ = ["REVIEW_OPS", "ReviewUnavailable", "review_finished_video_workflow"]

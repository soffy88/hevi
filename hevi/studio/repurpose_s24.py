"""S24 —— 吸收 threerocks/article2media 的成片审片、字级同步与一稿多发方法。

六个能力都写成「计划 + 可执行检查 + 真实产物」，不抄上游代码与文案：

1. ``review_delivery`` / ``render_review_overview``：口播/讲解类成片的硬指标审片，
   输出 ``review.json`` 与审片总览图；失败项附重做节点。
2. ``word_sync_plan``：用 whisper 实测字级时间戳，让数字滚动、清单、对比、金句
   在说到的字出现；生成图里不放字，文字全部由 HTML/CSS 叠加。
3. ``export_text_pack``：同一支成片可额外导出小红书 3:4 卡片 + 发帖文案、
   公众号内联样式 HTML（base64 内嵌图、一键复制）、长图；主题用 CSS 变量文件，
   与视频字幕样式共用同一套变量。
4. ``ingest_article`` / ``verify_article_render``：网页/公众号/Markdown → article.md；
   原文块用 SHA-256 锁定，渲染后逐块读回比对。视频链接转逐字稿只接受用户本人
   或已声明授权的内容，署名原作者，不批量抓取，不读浏览器 cookie。
5. ``check_localization``：块数、漏译、数字丢失；并入 localization_dub。
6. ``check_voice_tier`` / ``stamp_aigc`` / ``font_licenses``：音色分层、首帧与 MP4
   元数据 AIGC 标识、字体许可逐个列出。

所有测量都来自真实文件；拿不到测量时明确 ``pending``，不估算、不编造。
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "hevi.s24.repurpose.v1"
REVIEW_SCHEMA = "hevi.s24.delivery_review.v1"
LEDGER_SCHEMA = "hevi.s24.article_ledger.v1"
EXPORT_SCHEMA = "hevi.s24.text_pack.v1"
AIGC_LABEL = "AI生成"

LUFS_TARGET = -14.0
LUFS_TOLERANCE = 1.0
SPEECH_TARGET_CPS = 4.5
SPEECH_MAX_CPS = 5.2
SPEECH_SLOWDOWN_MAX = 0.15
FIRST_SENTENCE_MAX_S = 5.0
FIRST_SENTENCE_MAX_CHARS = 19
FIRST_VISUAL_MAX_S = 2.5
STATIC_MAX_S = 5.0
SUBTITLE_MAX_LINE_CHARS = 13
SUBTITLE_MIN_DWELL_S = 0.55
SUBTITLE_PAUSE_HOLD_S = 1.4
SUBTITLE_BLINK_S = 0.6
SAFE_AREA = {"x0": 0.05, "y0": 0.08, "x1": 0.95, "y1": 0.86}

_FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
_FFPROBE = shutil.which("ffprobe") or "ffprobe"
_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*(?:\s*(?:%|％|万|亿|千|百|元|美元|年|月|日|岁|人|次|倍))?")
_TRAIL_PUNCT_RE = re.compile(r"[\s。．.、,，;；:：!！?？\"'“”‘’()（）\[\]【】]+$")

# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _semantic_chars(text: str) -> int:
    return len(re.sub(r"[\s\W_]+", "", text or "", flags=re.UNICODE))


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = list(_FONT_CANDIDATES)
    if bold:
        candidates.insert(0, "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _check(
    check_id: str,
    label: str,
    status: str,
    *,
    measured: Any = None,
    limit: Any = None,
    detail: str = "",
    fix: str = "",
    node: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "measured": measured,
        "limit": limit,
        "detail": detail,
        "fix": fix,
        "node": node,
    }

# ---------------------------------------------------------------------------
# 媒体测量
# ---------------------------------------------------------------------------


def probe_media(path: str | Path) -> dict[str, Any]:
    proc = _run([
        _FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    if proc.returncode != 0:
        raise ValueError(f"ffprobe failed: {proc.stderr[-300:]}")
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = _num(payload.get("format", {}).get("duration"))
    if duration is None and video is not None:
        duration = _num(video.get("duration"))
    return {
        "duration_s": round(duration or 0.0, 3),
        "width": int(video.get("width") or 0) if video else 0,
        "height": int(video.get("height") or 0) if video else 0,
        "fps": _fps(video),
        "has_audio": audio is not None,
        "format": payload.get("format", {}),
    }


def _fps(stream: dict[str, Any] | None) -> float:
    if not stream:
        return 0.0
    raw = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    try:
        num, den = raw.split("/")
        return round(float(num) / float(den or 1), 3)
    except Exception:
        return 0.0


def measure_loudness(path: str | Path) -> dict[str, Any]:
    proc = _run([
        _FFMPEG, "-nostats", "-hide_banner", "-i", str(path),
        "-af", "ebur128=peak=true", "-f", "null", "-",
    ], timeout=180)
    text = proc.stderr or ""
    integrated = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", text)
    peak = re.findall(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", text)
    if not integrated:
        return {"status": "pending", "reason": "ebur128 produced no integrated loudness"}
    return {
        "status": "measured",
        "lufs": round(float(integrated[-1]), 2),
        "true_peak_dbfs": round(float(peak[-1]), 2) if peak else None,
        "target": LUFS_TARGET,
        "tolerance": LUFS_TOLERANCE,
    }


def _sample_luma(path: str | Path, *, fps: float, width: int = 64, height: int = 64) -> Any:
    import numpy as np

    proc = subprocess.run(
        [
            _FFMPEG, "-v", "error", "-i", str(path),
            "-vf", f"fps={fps},scale={width}:{height},format=gray",
            "-f", "rawvideo", "-",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"frame sampling failed: {proc.stderr[-300:]}")
    data = np.frombuffer(proc.stdout, dtype="uint8")
    if data.size == 0:
        return np.zeros((0, height, width), dtype="uint8")
    return data.reshape((-1, height, width))


def _motion_and_static(frames: Any, *, sample_fps: float) -> dict[str, Any]:
    import numpy as np

    if len(frames) < 2:
        return {"status": "pending", "reason": "not enough frames"}
    diffs = np.abs(np.diff(frames.astype("int16"), axis=0)).mean(axis=(1, 2))
    threshold = 1.5
    moving = diffs >= threshold
    longest = 0
    run = 0
    for flag in moving:
        if not flag:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    longest = max(longest, run)
    static_s = round(longest / max(sample_fps, 1e-6), 2)
    return {
        "status": "measured",
        "sample_fps": sample_fps,
        "mean_delta": round(float(diffs.mean()), 3),
        "longest_static_s": static_s,
        "moving_ratio": round(float(moving.mean()), 3),
    }


def _first_visual(path: str | Path, *, scan_s: float = 3.0, fps: float = 10.0) -> dict[str, Any]:
    frames = _sample_luma(path, fps=fps)
    limit = int(scan_s * fps)
    for index, frame in enumerate(frames[:limit]):
        std = float(frame.std())
        mean = float(frame.mean())
        if std >= 6.0 and mean >= 8.0:
            return {"status": "measured", "first_visual_s": round(index / fps, 2), "frame_std": round(std, 2)}
    return {"status": "measured", "first_visual_s": None, "frame_std": 0.0}


def _subtitle_band_presence(path: str | Path, cue: dict[str, Any], *, fps_box: dict[str, float] | None = None) -> bool:
    import numpy as np

    box = fps_box or {"x0": 0.05, "y0": 0.68, "x1": 0.95, "y1": 0.90}
    start = float(cue.get("start") or 0.0)
    end = float(cue.get("end") or start)
    times = [start + 0.12, max(start, (start + end) / 2), max(start, end - 0.12)]
    found = False
    for moment in times:
        proc = subprocess.run(
            [
                _FFMPEG, "-v", "error", "-ss", f"{max(0.0, moment):.3f}", "-i", str(path),
                "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            continue
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(proc.stdout)).convert("L")
        width, height = img.size
        crop = img.crop((int(width * box["x0"]), int(height * box["y0"]),
                         int(width * box["x1"]), int(height * box["y1"])))
        arr = np.asarray(crop, dtype="uint8")
        if arr.size == 0:
            continue
        white = float((arr >= 200).mean())
        contrast = float(arr.std())
        if white >= 0.004 or (contrast >= 38.0 and white >= 0.001):
            found = True
            break
    return found

# ---------------------------------------------------------------------------
# 1. 成片审片硬指标
# ---------------------------------------------------------------------------


def _cue_issues(cues: list[dict[str, Any]], *, plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    plan = plan or {}
    issues: list[dict[str, Any]] = []
    max_chars = int(plan.get("max_line_chars") or SUBTITLE_MAX_LINE_CHARS)
    min_dwell = float(plan.get("min_dwell_s") or SUBTITLE_MIN_DWELL_S)
    hold = float(plan.get("pause_hold_s") or SUBTITLE_PAUSE_HOLD_S)
    blink = float(plan.get("blink_s") or SUBTITLE_BLINK_S)
    previous: dict[str, Any] | None = None
    for index, cue in enumerate(cues):
        text = str(cue.get("text") or "")
        start = float(cue.get("start") or 0.0)
        end = float(cue.get("end") or start)
        if len(text.splitlines()) > 1:
            issues.append(_check(
                "subtitle_single_line", "字幕单行", "fail",
                measured=len(text.splitlines()), limit=1,
                detail=f"第 {index + 1} 条字幕换行", node="subtitle",
                fix="合并为一行；同句短语合并后仍超长时按语义拆成两条。",
            ))
        if _char_count(text) > max_chars:
            issues.append(_check(
                "subtitle_line_length", "单行 ≤13 字", "fail",
                measured=_char_count(text), limit=max_chars,
                detail=f"第 {index + 1} 条 {_char_count(text)} 字：{text[:24]}", node="subtitle",
                fix="同句短语合并 ≤13 字；不许换行。",
            ))
        dwell = round(end - start, 3)
        if dwell < min_dwell:
            issues.append(_check(
                "subtitle_dwell", "停留 ≥0.55 秒", "fail",
                measured=dwell, limit=min_dwell,
                detail=f"第 {index + 1} 条只停 {dwell}s", node="subtitle",
                fix="延长到 ≥0.55 秒；与相邻条合并。",
            ))
        if previous is not None:
            gap = round(start - float(previous.get("end") or 0.0), 3)
            if 0 < gap < hold:
                issues.append(_check(
                    "subtitle_pause_hold", "1.4 秒内停顿不撤字幕", "fail",
                    measured=gap, limit=f"0 或 ≥{hold}",
                    detail=f"第 {index} 与 {index + 1} 条之间空档 {gap}s", node="subtitle",
                    fix="把上一条延到下一句开始，或合并两句。",
                ))
            if 0 < gap < blink:
                issues.append(_check(
                    "subtitle_blink", "闪断（<0.6 秒空档）0 处", "fail",
                    measured=gap, limit=blink,
                    detail=f"第 {index} 与 {index + 1} 条之间 {gap}s 闪断", node="subtitle",
                    fix="消除空档，保持字幕连续。",
                ))
        previous = cue
    if plan.get("hard_cut") is False:
        issues.append(_check(
            "subtitle_hard_cut", "字幕硬切", "fail",
            measured="fade", limit="hard_cut", detail="字幕带淡入淡出", node="subtitle",
            fix="改为硬切（无 fade）。",
        ))
    return issues


def _safe_area_issues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index, cue in enumerate(cues):
        box = cue.get("box")
        if not isinstance(box, dict):
            continue
        x0 = float(box.get("x0", 0))
        y0 = float(box.get("y0", 0))
        x1 = float(box.get("x1", 1))
        y1 = float(box.get("y1", 1))
        if x0 < SAFE_AREA["x0"] or y0 < SAFE_AREA["y0"] or x1 > SAFE_AREA["x1"] or y1 > SAFE_AREA["y1"]:
            issues.append(_check(
                "subtitle_safe_area", "字幕安全区", "fail",
                measured={"x0": x0, "y0": y0, "x1": x1, "y1": y1}, limit=SAFE_AREA,
                detail=f"第 {index + 1} 条出安全区", node="subtitle",
                fix="移回 x 5%–95%、y 8%–86%。",
            ))
    return issues


def review_delivery(
    media_path: str | Path,
    *,
    narration: list[dict[str, Any]] | None = None,
    cues: list[dict[str, Any]] | None = None,
    subtitle_plan: dict[str, Any] | None = None,
    sample_fps: float = 8.0,
    loudness_target: float = LUFS_TARGET,
    frame_check: bool = True,
) -> dict[str, Any]:
    """审一条口播/讲解成片，返回 review.json 结构。"""
    path = Path(media_path)
    if not path.is_file():
        raise FileNotFoundError(f"成片不存在：{path}")
    media = probe_media(path)
    duration = float(media["duration_s"])
    checks: list[dict[str, Any]] = []
    retry: list[dict[str, Any]] = []

    narration = [dict(item) for item in (narration or []) if str(item.get("text") or "").strip()]
    cues = [dict(item) for item in (cues or []) if str(item.get("text") or "").strip()]
    plan = dict(subtitle_plan or {})

    if narration:
        first = narration[0]
        first_text = str(first.get("text") or "")
        first_end = _num(first.get("end"))
        if first_end is not None:
            ok = first_end <= FIRST_SENTENCE_MAX_S
            checks.append(_check(
                "first_sentence_time", "首句 ≤5 秒", "pass" if ok else "fail",
                measured=round(first_end, 2), limit=FIRST_SENTENCE_MAX_S,
                detail=first_text[:30], node="script",
                fix="把首句压缩到 5 秒内。" if not ok else "",
            ))
            if not ok:
                retry.append({"node": "script", "reason": "首句超过 5 秒", "action": "重写首句后重做本节点。"})
        chars = _semantic_chars(first_text)
        ok = chars <= FIRST_SENTENCE_MAX_CHARS
        checks.append(_check(
            "first_sentence_chars", "首句 ≤19 字", "pass" if ok else "fail",
            measured=chars, limit=FIRST_SENTENCE_MAX_CHARS,
            detail=first_text[:30], node="script",
            fix="删修饰词，只留主谓宾。" if not ok else "",
        ))
        if not ok:
            retry.append({"node": "script", "reason": "首句超过 19 字", "action": "删到 19 字内后重做本节点。"})

        rates = []
        for index, item in enumerate(narration):
            start = _num(item.get("start")) or 0.0
            end = _num(item.get("end")) or 0.0
            span = max(0.0, end - start)
            text = str(item.get("text") or "")
            if span <= 0:
                continue
            cps = round(_semantic_chars(text) / span, 2)
            rates.append({"index": index + 1, "cps": cps, "text": text[:30], "start": start, "end": end})
        if rates:
            fastest = max(rates, key=lambda row: row["cps"])
            overall_chars = sum(_semantic_chars(str(item.get("text") or "")) for item in narration)
            span_total = max(1e-6, (float(narration[-1].get("end") or 0)) - float(narration[0].get("start") or 0))
            overall = round(overall_chars / span_total, 2)
            too_fast = [row for row in rates if row["cps"] > SPEECH_MAX_CPS]
            checks.append(_check(
                "speech_rate_max", "单句 ≤5.2 字/秒", "pass" if not too_fast else "fail",
                measured=fastest["cps"], limit=SPEECH_MAX_CPS,
                detail=f"最快第 {fastest['index']} 句：{fastest['text']}", node="narration",
                fix="换种子重生成；仍快则保音高放慢 ≤15%。" if too_fast else "",
            ))
            if too_fast:
                retry.append({
                    "node": "narration",
                    "reason": f"{len(too_fast)} 句超过 5.2 字/秒",
                    "action": f"换种子重生成；仍快则保音高放慢 ≤{int(SPEECH_SLOWDOWN_MAX * 100)}%，再重做本节点。",
                })
            in_band = 3.8 <= overall <= SPEECH_MAX_CPS
            checks.append(_check(
                "speech_rate_target", "旁白约 4.5 字/秒", "pass" if in_band else "warn",
                measured=overall, limit=f"{SPEECH_TARGET_CPS}±0.7",
                detail="整体语速", node="narration",
                fix="" if in_band else "调整句子长度或停顿，向 4.5 字/秒靠拢。",
            ))

    first_visual = _first_visual(path)
    if first_visual.get("first_visual_s") is not None:
        value = float(first_visual["first_visual_s"])
        ok = value <= FIRST_VISUAL_MAX_S
        checks.append(_check(
            "first_visual_info", "首个画面信息 ≤2.5 秒", "pass" if ok else "fail",
            measured=value, limit=FIRST_VISUAL_MAX_S,
            detail="从黑场/纯色到第一处可读画面", node="opening",
            fix="把首个图形/画面提到 2.5 秒内。",
        ))
        if not ok:
            retry.append({"node": "opening", "reason": "前 2.5 秒没有画面信息", "action": "重排开场后重做本节点。"})
    else:
        checks.append(_check(
            "first_visual_info", "首个画面信息 ≤2.5 秒", "fail",
            measured=None, limit=FIRST_VISUAL_MAX_S,
            detail="前 3 秒没有测到可读画面", node="opening", fix="补首个画面后重做。",
        ))
        retry.append({"node": "opening", "reason": "前 3 秒无可读画面", "action": "补画面后重做本节点。"})

    motion = _motion_and_static(_sample_luma(path, fps=sample_fps), sample_fps=sample_fps)
    if motion.get("status") == "measured":
        static_s = float(motion["longest_static_s"])
        ok = static_s <= STATIC_MAX_S
        checks.append(_check(
            "static_max", "画面静止 ≤5 秒", "pass" if ok else "fail",
            measured=static_s, limit=STATIC_MAX_S,
            detail=f"平均帧差 {motion['mean_delta']}", node="motion",
            fix="在静止段加轻推/图表生长/字幕动效后重做。",
        ))
        if not ok:
            retry.append({"node": "motion", "reason": f"静止 {static_s}s", "action": "加运动后重做本节点。"})
    else:
        checks.append(_check("static_max", "画面静止 ≤5 秒", "pending", detail="帧数不足"))

    subtitle_issues: list[dict[str, Any]] = []
    if cues:
        subtitle_issues.extend(_cue_issues(cues, plan=plan))
        subtitle_issues.extend(_safe_area_issues(cues))
        dropouts = 0
        if frame_check:
            for cue in cues:
                if not _subtitle_band_presence(path, cue, fps_box=plan.get("band")):
                    dropouts += 1
                    if dropouts >= 6:
                        break
        checks.append(_check(
            "subtitle_dropout", "逐帧抽查字幕丢帧", "pass" if dropouts == 0 else "fail",
            measured=dropouts, limit=0,
            detail=f"抽查 {len(cues)} 条 × 3 帧", node="subtitle",
            fix="重烧字幕，保证每条覆盖整段。" if dropouts else "",
        ))
        if dropouts:
            retry.append({"node": "subtitle", "reason": f"{dropouts} 条字幕疑似丢帧", "action": "重烧字幕后重做本节点。"})
        merged_gap = [issue for issue in subtitle_issues if issue["id"] in {"subtitle_pause_hold", "subtitle_blink"}]
        checks.append(_check(
            "subtitle_continuity", "1.4 秒内不撤字幕 / 闪断 0 处",
            "pass" if not merged_gap else "fail",
            measured=len(merged_gap), limit=0,
            detail="空档规则合并检查", node="subtitle",
            fix="" if not merged_gap else "合并相邻字幕或延长停留。",
        ))
        subtitle_fail = [issue for issue in subtitle_issues if issue["status"] == "fail"]
        if subtitle_fail and not any(item["node"] == "subtitle" for item in retry):
            retry.append({
                "node": "subtitle",
                "reason": f"{len(subtitle_fail)} 项字幕规则未过",
                "action": "重排行宽/停留/空档后重烧字幕，再重做本节点。",
            })
    else:
        checks.append(_check("subtitle_dropout", "逐帧抽查字幕丢帧", "pending", detail="没有提供字幕条"))

    loudness = measure_loudness(path)
    if loudness.get("status") == "measured":
        value = float(loudness["lufs"])
        ok = abs(value - loudness_target) <= LUFS_TOLERANCE
        checks.append(_check(
            "loudness", "-14 LUFS", "pass" if ok else "fail",
            measured=value, limit=f"{loudness_target}±{LUFS_TOLERANCE}",
            detail=f"true peak {loudness.get('true_peak_dbfs')} dBFS", node="mix",
            fix="重混到 -14 LUFS（±1）。" if not ok else "",
        ))
        if not ok:
            retry.append({"node": "mix", "reason": f"响度 {value} LUFS", "action": "重混到 -14 LUFS 后重做本节点。"})
    else:
        checks.append(_check("loudness", "-14 LUFS", "pending", detail=loudness.get("reason", "")))

    checks.extend(subtitle_issues)
    counts = {"pass": 0, "warn": 0, "fail": 0, "pending": 0}
    for item in checks:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    passed = counts["fail"] == 0
    summary = (
        f"{counts['pass']} 项通过 / {counts['warn']} 项提醒 / {counts['fail']} 项失败"
        f"（{media['width']}×{media['height']} · {duration:.2f}s）"
    )
    return {
        "schema": REVIEW_SCHEMA,
        "media": str(path),
        "media_sha256": _sha256_file(path),
        "duration_s": duration,
        "width": media["width"],
        "height": media["height"],
        "counts": counts,
        "pass": passed,
        "checks": checks,
        "retry": retry,
        "motion": motion,
        "loudness": loudness,
        "subtitles": {"cues": len(cues), "plan": plan},
        "summary": summary,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_review_overview(review: dict[str, Any], out_path: str | Path) -> Path:
    """把 review.json 画成一张审片总览图（4:5，1080×1350）。"""
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    bg = (248, 245, 238)
    ink = (26, 28, 32)
    muted = (104, 108, 116)
    ok_color = (28, 132, 92)
    warn_color = (196, 142, 20)
    fail_color = (196, 54, 42)
    pending_color = (120, 124, 132)
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 190], fill=(20, 24, 32))
    draw.text((64, 54), "成片审片 · 硬指标", font=_font(44, bold=True), fill=(255, 255, 255))
    draw.text((64, 118), review.get("summary", ""), font=_font(26), fill=(196, 204, 214))
    badge = "通过" if review.get("pass") else "需重做"
    color = ok_color if review.get("pass") else fail_color
    draw.rounded_rectangle([width - 230, 60, width - 64, 136], radius=18, fill=color)
    draw.text((width - 190, 78), badge, font=_font(32, bold=True), fill=(255, 255, 255))

    y = 228
    colors = {"pass": ok_color, "warn": warn_color, "fail": fail_color, "pending": pending_color}
    marks = {"pass": "通过", "warn": "提醒", "fail": "失败", "pending": "待测"}
    for item in review.get("checks", [])[:16]:
        status = item.get("status", "pending")
        draw.ellipse([64, y + 8, 86, y + 30], fill=colors.get(status, pending_color))
        draw.text((104, y), str(item.get("label", "")), font=_font(28, bold=True), fill=ink)
        measured = item.get("measured")
        detail = f"{marks.get(status, status)}"
        if measured is not None:
            detail += f" · 实测 {measured} · 限 {item.get('limit')}"
        draw.text((104, y + 46), detail[:52], font=_font(21), fill=muted)
        y += 66

    if review.get("retry"):
        y += 8
        draw.text((64, y), "失败就重做这些节点", font=_font(26, bold=True), fill=fail_color)
        y += 46
        for action in review["retry"][:5]:
            draw.text((64, y), f"· {action.get('node')}：{action.get('action')}"[:60], font=_font(20), fill=ink)
            y += 34

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG")
    return out

# ---------------------------------------------------------------------------
# 2. 字级同步（whisper 实测）
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|[A-Za-z]+(?:'[A-Za-z]+)?|[\u3400-\u9fff]|[^\s]")


def _whisper_model_candidates() -> list[str]:
    candidates = []
    env = os.environ.get("HEVI_WHISPER_ALIGN_MODEL", "").strip()
    if env:
        candidates.append(env)
    candidates.extend([
        "/models/faster-whisper-large-v3-turbo",
        "/home/soffy/models/faster-whisper-large-v3-turbo",
        "/models/faster-whisper-base",
        "/home/soffy/models/faster-whisper-base",
    ])
    return [path for path in candidates if Path(path).is_dir()]


def _docker_align(audio_path: Path, *, container: str) -> list[dict[str, Any]]:
    output_root = Path(os.environ.get("HEVI_S24_OUTPUT_ROOT", "/home/soffy/projects/hevi/output"))
    output_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_root / ".s24_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    if audio_path.is_relative_to(output_root):
        container_path = "/app/output/" + str(audio_path.relative_to(output_root))
    else:
        target = tmp_dir / f"{uuid_hex()}{audio_path.suffix or '.wav'}"
        shutil.copy2(audio_path, target)
        container_path = "/app/output/.s24_tmp/" + target.name
    model_candidates = ["/models/faster-whisper-large-v3-turbo", "/models/faster-whisper-base"]
    script = (
        "import json,sys\n"
        "from faster_whisper import WhisperModel\n"
        "path=sys.argv[1]\n"
        "models=sys.argv[2:]\n"
        "last=None\n"
        "for m in models:\n"
        "    try:\n"
        "        model=WhisperModel(m,device='cpu',compute_type='int8')\n"
        "        break\n"
        "    except Exception as exc:\n"
        "        last=exc\n"
        "else:\n"
        "    raise SystemExit(str(last))\n"
        "segs,_=model.transcribe(path,word_timestamps=True,vad_filter=True)\n"
        "out=[]\n"
        "for s in segs:\n"
        "    out.append({'start':s.start,'end':s.end,'text':s.text.strip(),'words':[{'text':w.word,'start':w.start,'end':w.end} for w in (s.words or [])]})\n"
        "print(json.dumps(out,ensure_ascii=False))\n"
    )
    proc = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-", container_path, *model_candidates],
        input=script,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker whisper failed: {(proc.stderr or proc.stdout)[-400:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex


def align_words(audio_path: str | Path, *, container: str | None = None) -> dict[str, Any]:
    """用 whisper 实测字级时间戳；本机没有 faster-whisper 时走同一容器。"""
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"音频不存在：{path}")
    try:
        from faster_whisper import WhisperModel

        model_path = _whisper_model_candidates()
        if not model_path:
            raise RuntimeError("no local faster-whisper model")
        model = WhisperModel(model_path[0], device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
        raw = [
            {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": (seg.text or "").strip(),
                "words": [
                    {"text": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
                    for w in (seg.words or [])
                ],
            }
            for seg in segments
        ]
        return {"status": "measured", "source": "whisper_local", "segments": raw}
    except Exception as exc:
        container = container or os.environ.get("HEVI_S24_WHISPER_CONTAINER", "hevi-cftunnel-hevi-api-1")
        try:
            raw = _docker_align(path, container=container)
        except Exception as docker_exc:
            return {
                "status": "pending",
                "source": "whisper_local",
                "reason": f"{type(exc).__name__}: {exc}; docker: {type(docker_exc).__name__}: {docker_exc}",
                "segments": [],
            }
        return {"status": "measured", "source": "whisper_local_docker", "segments": raw}


def _flatten_asr(raw: list[dict[str, Any]]) -> list[tuple[str, float, float]]:
    chars: list[tuple[str, float, float]] = []
    for segment in raw:
        for word in segment.get("words") or []:
            text = str(word.get("text") or "")
            start = float(word.get("start") or 0)
            end = float(word.get("end") or start)
            clean = [ch for ch in text if not ch.isspace() and not _TRAIL_PUNCT_RE.match(ch)]
            if not clean:
                continue
            span = max(1e-3, end - start)
            for index, ch in enumerate(clean):
                chars.append((ch.lower(), start + span * index / len(clean), start + span * (index + 1) / len(clean)))
    return chars


def map_words_to_transcript(raw: list[dict[str, Any]], transcript: str) -> list[dict[str, Any]]:
    """把 ASR 字流对齐到已知逐字稿；文字用逐字稿，时间用 ASR 实测。"""
    from difflib import SequenceMatcher

    tokens = [token for token in _TOKEN_RE.findall(transcript) if not _TRAIL_PUNCT_RE.match(token)]
    known = [ch.lower() for token in tokens for ch in token if ch.isalnum() or _CJK_RE.match(ch)]
    asr = _flatten_asr(raw)
    asr_chars = [item[0] for item in asr]
    times: list[tuple[float, float] | None] = [None] * len(known)
    matcher = SequenceMatcher(None, known, asr_chars, autojunk=False)
    for tag, i1, i2, j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                times[i1 + offset] = (asr[j1 + offset][1], asr[j1 + offset][2])
    known_times: list[float] = []
    for index, value in enumerate(times):
        if value is not None:
            known_times.append((index, value[0], value[1]))
    if not known_times:
        return [
            {"text": token, "start": None, "end": None, "source": "pending_alignment"}
            for token in tokens
        ]
    filled: list[tuple[float, float]] = []
    for index in range(len(times)):
        if times[index] is not None:
            filled.append(times[index])  # type: ignore[arg-type]
        else:
            previous = next(((i, v[0], v[1]) for i, v in reversed(list(enumerate(times[:index]))) if v), None)
            following = next(((i, v[0], v[1]) for i, v in enumerate(times[index + 1:], start=index + 1) if v), None)
            if previous and following:
                frac = (index - previous[0]) / max(1, following[0] - previous[0])
                moment = previous[1] + (following[1] - previous[1]) * frac
                filled.append((moment, moment))
            elif previous:
                filled.append((previous[2], previous[2]))
            else:
                filled.append((following[1], following[1]))  # type: ignore[index]
    words: list[dict[str, Any]] = []
    cursor = 0
    for token in tokens:
        count = sum(1 for ch in token if ch.isalnum() or _CJK_RE.match(ch))
        if count == 0:
            continue
        start = filled[cursor][0]
        end = filled[min(len(filled) - 1, cursor + count - 1)][1]
        words.append({
            "text": token,
            "start": round(start, 3),
            "end": round(end, 3),
            "source": "whisper_asr_mapped",
        })
        cursor += count
        if cursor >= len(filled):
            break
    return words


def _find_word_index(words: list[dict[str, Any]], needle: str) -> int | None:
    if not needle:
        return None
    target = _clean_text(needle).lower()
    if not target:
        return None
    joined = "".join(str(word.get("text") or "") for word in words).lower()
    index = joined.find(target)
    if index < 0:
        return None
    cursor = 0
    for word_index, word in enumerate(words):
        text = str(word.get("text") or "").lower()
        if cursor + len(text) > index:
            return word_index
        cursor += len(text)
    return None


def _overlay_base_css(theme: dict[str, Any]) -> str:
    return (
        ":root{"
        f"--s24-bg:{theme['bg']};--s24-fg:{theme['fg']};--s24-accent:{theme['accent']};"
        f"--s24-muted:{theme['muted']};--s24-panel:{theme['panel']};"
        f"--s24-font:{theme['font']};--s24-subtitle-size:{theme['subtitle_size']}px;"
        f"--s24-subtitle-bottom:{theme['subtitle_bottom']}%;"
        "}"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{width:1080px;height:1920px;overflow:hidden;background:var(--s24-bg);"
        "font-family:var(--s24-font),'Noto Sans CJK SC',sans-serif}"
        ".s24-overlay{position:absolute;inset:0}"
        ".s24-bgfx{position:absolute;inset:0;overflow:hidden}"
        ".s24-bgfx i{position:absolute;display:block;border-radius:48px}"
        ".s24-bgfx .b1{width:720px;height:720px;left:-160px;top:380px;background:var(--s24-panel);opacity:.55}"
        ".s24-bgfx .b2{width:560px;height:560px;left:520px;top:760px;border:14px solid var(--s24-accent);opacity:.5}"
        ".s24-number{position:absolute;right:8%;top:22%;font-size:180px;font-weight:800;"
        "color:var(--s24-accent);font-variant-numeric:tabular-nums;letter-spacing:-4px;opacity:0}"
        ".s24-label{position:absolute;right:8%;top:52%;font-size:36px;color:var(--s24-fg);opacity:0}"
        ".s24-list{position:absolute;left:8%;top:30%;width:84%}"
        ".s24-item{font-size:46px;line-height:1.5;color:var(--s24-fg);opacity:0;"
        "border-left:6px solid var(--s24-accent);padding-left:22px;margin-bottom:20px}"
        ".s24-compare{position:absolute;left:8%;right:8%;top:30%;display:flex;gap:28px}"
        ".s24-side{flex:1;padding:34px;border-radius:20px;background:var(--s24-panel);"
        "font-size:44px;line-height:1.4;color:var(--s24-fg);opacity:0}"
        ".s24-quote{position:absolute;left:8%;right:8%;top:34%;font-size:68px;line-height:1.35;"
        "font-weight:800;color:var(--s24-accent);opacity:0}"
        ".s24-subtitle{position:absolute;left:5%;right:5%;bottom:var(--s24-subtitle-bottom);"
        "text-align:center;font-size:var(--s24-subtitle-size);line-height:1.35;color:#fff;"
        "background:rgba(0,0,0,.42);padding:14px 18px;border-radius:8px;opacity:0}"
    )


def _overlay_html(theme: dict[str, Any], shots: list[dict[str, Any]], cues: list[dict[str, Any]] | None = None) -> str:
    parts = []
    for shot in shots:
        kind = shot["kind"]
        appear = shot.get("appear_at")
        style = f"animation-delay:{appear}s" if appear is not None else "display:none"
        if kind == "number_roll":
            parts.append(
                f'<div class="s24-number" id="shot-{shot["id"]}" data-at="{appear}" '
                f'data-value="{html.escape(str(shot.get("value", "")))}" style="{style}">'
                f'{html.escape(str(shot.get("value", "")))}</div>'
                f'<div class="s24-label" data-at="{appear}" style="{style}">{html.escape(shot.get("label", ""))}</div>'
            )
        elif kind == "checklist":
            items = "".join(
                f'<div class="s24-item" data-at="{item["appear_at"]}" '
                f'style="animation-delay:{item["appear_at"]}s">{html.escape(item["text"])}</div>'
                for item in shot.get("items", []) if item.get("appear_at") is not None
            )
            parts.append(f'<div class="s24-list" id="shot-{shot["id"]}">{items}</div>')
        elif kind == "compare":
            sides = "".join(
                f'<div class="s24-side" data-at="{side["appear_at"]}" '
                f'style="animation-delay:{side["appear_at"]}s">{html.escape(side["text"])}</div>'
                for side in shot.get("sides", []) if side.get("appear_at") is not None
            )
            parts.append(f'<div class="s24-compare" id="shot-{shot["id"]}">{sides}</div>')
        elif kind == "quote":
            parts.append(
                f'<div class="s24-quote" id="shot-{shot["id"]}" data-at="{appear}" style="{style}">'
                f'{html.escape(shot.get("text", ""))}</div>'
            )
    cue_html = "".join(
        f'<div class="s24-subtitle" data-start="{cue["start"]}" data-end="{cue["end"]}">'
        f'{html.escape(str(cue["text"]))}</div>'
        for cue in (cues or [])
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + _overlay_base_css(theme)
        + "</style></head><body><div class='s24-overlay'>"
        + '<div class="s24-bgfx"><i class="b1"></i><i class="b2"></i></div>'
        + "".join(parts)
        + "</div>"
        + cue_html
        + ("<script>window.S24={seek:function(t){"
           "document.querySelectorAll('[data-at]').forEach(function(el){"
           "var a=parseFloat(el.getAttribute('data-at'));el.style.opacity=(t>=a)?'1':'0';});"
           "document.querySelectorAll('.s24-subtitle').forEach(function(el){"
           "var s=parseFloat(el.dataset.start),e=parseFloat(el.dataset.end);"
           "el.style.opacity=(t>=s&&t<e)?'1':'0';});}};"
           "(function(){var t0=performance.now();function tick(){"
           "window.S24.seek((performance.now()-t0)/1000);requestAnimationFrame(tick);}tick();})();</script>"
           if cues else "")
        + "</body></html>"
    )


def word_sync_plan(
    *,
    audio_path: str | Path | None = None,
    transcript: str = "",
    words: list[dict[str, Any]] | None = None,
    shots: list[dict[str, Any]],
    theme: str | dict[str, Any] | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """字级同步计划：每个元素在说到对应字的时刻出现；文字只走 HTML/CSS。"""
    palette = resolve_theme(theme)
    measured = list(words or [])
    source = "provided"
    if not measured:
        if audio_path is None:
            return {
                "schema": SCHEMA,
                "status": "pending_alignment",
                "reason": "没有 words，也没有 audio_path",
                "source": "none",
                "text_in_image": False,
                "overlay": "html_css",
                "shots": [],
                "css": _overlay_base_css(palette),
                "html": _overlay_html(palette, []),
            }
        alignment = align_words(audio_path)
        source = alignment.get("source", "whisper_local")
        if alignment.get("status") != "measured":
            return {
                "schema": SCHEMA,
                "status": "pending_alignment",
                "reason": alignment.get("reason", "whisper 不可用"),
                "source": source,
                "text_in_image": False,
                "overlay": "html_css",
                "shots": [{"id": shot.get("id"), "kind": shot.get("kind"), "appear_at": None} for shot in shots],
                "css": _overlay_base_css(palette),
                "html": _overlay_html(palette, []),
            }
        measured = map_words_to_transcript(alignment.get("segments") or [], transcript)

    plan_shots: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        kind = str(shot.get("kind") or "quote")
        item: dict[str, Any] = {
            "id": str(shot.get("id") or index + 1),
            "kind": kind,
            "title": str(shot.get("title") or ""),
            "text_in_image": False,
            "overlay": "html_css",
        }
        if kind == "checklist":
            items = []
            for entry in shot.get("items") or []:
                text = str(entry.get("text") if isinstance(entry, dict) else entry)
                trigger = str(entry.get("trigger") if isinstance(entry, dict) else text)
                word_index = _find_word_index(measured, trigger)
                items.append({
                    "text": text,
                    "appear_at": measured[word_index]["start"] if word_index is not None else None,
                    "word_index": word_index,
                })
            item["items"] = items
            item["appear_at"] = min([x["appear_at"] for x in items if x["appear_at"] is not None], default=None)
        elif kind == "compare":
            sides = []
            for entry in shot.get("sides") or []:
                text = str(entry.get("text") if isinstance(entry, dict) else entry)
                trigger = str(entry.get("trigger") if isinstance(entry, dict) else text)
                word_index = _find_word_index(measured, trigger)
                sides.append({
                    "text": text,
                    "appear_at": measured[word_index]["start"] if word_index is not None else None,
                    "word_index": word_index,
                })
            item["sides"] = sides
            item["appear_at"] = min([x["appear_at"] for x in sides if x["appear_at"] is not None], default=None)
        else:
            trigger = str(shot.get("trigger") or shot.get("text") or shot.get("value") or "")
            word_index = _find_word_index(measured, trigger)
            item["appear_at"] = measured[word_index]["start"] if word_index is not None else None
            item["word_index"] = word_index
            if kind == "number_roll":
                item["value"] = shot.get("value", "")
                item["label"] = str(shot.get("label") or "")
            else:
                item["text"] = str(shot.get("text") or trigger)
        item["image_prompt"] = (
            f"{shot.get('image_prompt') or shot.get('title') or '画面'}；"
            "画面内不生成任何文字、字幕、数字或 LOGO；文字全部由 HTML/CSS 叠加。"
        )
        plan_shots.append(item)

    result = {
        "schema": SCHEMA,
        "status": "measured",
        "source": source,
        "words": measured,
        "shots": plan_shots,
        "text_in_image": False,
        "overlay": "html_css",
        "theme": palette,
        "css": _overlay_base_css(palette),
        "html": _overlay_html(palette, plan_shots),
        "policy": "生成图里不放字；数字滚动、清单、对比、金句由 HTML/CSS 在说到的字出现。",
    }
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        _write_json(out / "word_sync.json", result)
        (out / "word_sync.html").write_text(result["html"], encoding="utf-8")
    return result

# ---------------------------------------------------------------------------
# 3. 一稿多发：主题变量 + 卡片 + 公众号 + 长图
# ---------------------------------------------------------------------------

THEMES: dict[str, dict[str, Any]] = {
    "editorial": {
        "id": "editorial", "label": "编辑部",
        "bg": "#F4EFE6", "fg": "#1B1C1E", "accent": "#B23A2E",
        "muted": "#6E6A63", "panel": "#E9E1D3", "font": "Noto Serif CJK SC",
        "subtitle_size": 54, "subtitle_bottom": 12,
    },
    "signal": {
        "id": "signal", "label": "信号蓝",
        "bg": "#0E1420", "fg": "#F3F6FA", "accent": "#2EC4B6",
        "muted": "#9AA7B8", "panel": "#182233", "font": "Noto Sans CJK SC",
        "subtitle_size": 54, "subtitle_bottom": 14,
    },
    "ink": {
        "id": "ink", "label": "墨纸",
        "bg": "#F7F5F0", "fg": "#202020", "accent": "#3B4B6B",
        "muted": "#6B6B6B", "panel": "#ECEAE4", "font": "Noto Serif CJK SC",
        "subtitle_size": 52, "subtitle_bottom": 12,
    },
    "sunrise": {
        "id": "sunrise", "label": "晨光",
        "bg": "#FFF4E4", "fg": "#2A211B", "accent": "#E4572E",
        "muted": "#7D6A5B", "panel": "#FFE6CC", "font": "Noto Sans CJK SC",
        "subtitle_size": 54, "subtitle_bottom": 12,
    },
    "night": {
        "id": "night", "label": "夜读",
        "bg": "#12121A", "fg": "#EDEBF2", "accent": "#8E7CFF",
        "muted": "#9A96A8", "panel": "#1D1C28", "font": "Noto Sans CJK SC",
        "subtitle_size": 54, "subtitle_bottom": 14,
    },
    "moss": {
        "id": "moss", "label": "苔绿",
        "bg": "#EEF2E9", "fg": "#1E2A22", "accent": "#3E7C59",
        "muted": "#68766B", "panel": "#DDE6D8", "font": "Noto Serif CJK SC",
        "subtitle_size": 52, "subtitle_bottom": 12,
    },
}
DEFAULT_THEMES = ("editorial", "signal")


def resolve_theme(theme: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(theme, dict):
        merged = dict(THEMES["editorial"])
        merged.update(theme)
        return merged
    key = str(theme or "editorial")
    return dict(THEMES.get(key, THEMES["editorial"]))


def theme_css(theme: str | dict[str, Any] | None) -> dict[str, Any]:
    palette = resolve_theme(theme)
    variables = {
        "--s24-bg": palette["bg"],
        "--s24-fg": palette["fg"],
        "--s24-accent": palette["accent"],
        "--s24-muted": palette["muted"],
        "--s24-panel": palette["panel"],
        "--s24-font": palette["font"],
        "--s24-subtitle-size": f"{palette['subtitle_size']}px",
        "--s24-subtitle-bottom": f"{palette['subtitle_bottom']}%",
    }
    css = ":root{" + ";".join(f"{key}:{value}" for key, value in variables.items()) + "}"
    return {
        "theme": palette,
        "variables": variables,
        "css": css,
        "subtitle_style": {
            "font_family": "var(--s24-font)",
            "font_size": "var(--s24-subtitle-size)",
            "bottom": "var(--s24-subtitle-bottom)",
            "color": "#FFFFFF",
            "background": "rgba(0,0,0,.42)",
            "max_line_chars": SUBTITLE_MAX_LINE_CHARS,
        },
    }


def _hex(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _wrap_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def _draw_card(
    theme: dict[str, Any], *, events: list[dict[str, Any]], footer: str, width: int = 1080,
    height: int = 1440,
) -> Any:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), _hex(theme["bg"]))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 18], fill=_hex(theme["accent"]))
    y = 120
    for event in events:
        kind = event.get("kind")
        if kind == "kicker":
            draw.text((90, y), event["text"], font=_font(30), fill=_hex(theme["accent"]))
            y += 58
        elif kind == "title":
            for line in _wrap_text(draw, event["text"], _font(74, bold=True), width - 180)[:4]:
                draw.text((90, y), line, font=_font(74, bold=True), fill=_hex(theme["fg"]))
                y += 96
            y += 20
        elif kind == "rule":
            draw.rectangle([90, y, 250, y + 8], fill=_hex(theme["accent"]))
            y += 36
        elif kind == "body":
            for line in _wrap_text(draw, event["text"], _font(36), width - 180):
                draw.text((90, y), line, font=_font(36), fill=_hex(theme["fg"]))
                y += 58
            y += 18
        elif kind == "bullet":
            draw.ellipse([92, y + 18, 112, y + 38], fill=_hex(theme["accent"]))
            for line in _wrap_text(draw, event["text"], _font(34), width - 240):
                draw.text((136, y), line, font=_font(34), fill=_hex(theme["fg"]))
                y += 54
            y += 12
        elif kind == "spacer":
            y += int(event.get("size") or 40)
        if y > height - 160:
            break
    draw.line([90, height - 120, width - 90, height - 120], fill=_hex(theme["panel"]), width=3)
    draw.text((90, height - 96), footer, font=_font(24), fill=_hex(theme["muted"]))
    return img


def _estimate_long_height(events: list[dict[str, Any]]) -> int:
    height = 120
    for event in events:
        kind = event.get("kind")
        if kind in {"kicker", "rule"}:
            height += 58 if kind == "kicker" else 36
        elif kind == "title":
            height += 96 * max(1, math.ceil(len(str(event.get("text") or "")) / 14)) + 20
        elif kind == "body":
            height += 58 * max(1, math.ceil(len(str(event.get("text") or "")) / 26)) + 18
        elif kind == "bullet":
            height += 54 * max(1, math.ceil(len(str(event.get("text") or "")) / 24)) + 12
        elif kind == "spacer":
            height += int(event.get("size") or 40)
    return max(1600, min(20000, height + 200))


def _section_bullets(section: dict[str, Any]) -> list[str]:
    bullets = section.get("bullets") or []
    if bullets:
        return [str(item) for item in bullets]
    body = str(section.get("body") or "")
    parts = [part.strip() for part in re.split(r"[。；;]\s*", body) if part.strip()]
    return parts[:3]


def export_text_pack(
    *,
    title: str,
    sections: list[dict[str, Any]],
    out_dir: str | Path,
    theme: str | dict[str, Any] | None = None,
    author: str = "",
    source_blocks: list[dict[str, Any]] | None = None,
    ratio: str = "3:4",
) -> dict[str, Any]:
    """一稿多发：3:4 卡片组 + 发帖文案 + 公众号内联 HTML + 长图。

    传 ``source_blocks`` 时走“一字不改”路径：卡片、长图、公众号都按原文块
    逐块渲染，渲染块与 SHA-256 账本逐块比对。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    palette = resolve_theme(theme)
    css = theme_css(palette)
    (out / "theme.css").write_text(css["css"] + "\n", encoding="utf-8")
    (out / "theme.json").write_text(json.dumps(css, ensure_ascii=False, indent=2), encoding="utf-8")

    exact = bool(source_blocks)
    if exact:
        items = [{"kind": str(block.get("kind") or "paragraph"), "text": str(block.get("text") or "")}
                 for block in source_blocks or []]
    else:
        items = [{
            "kind": "section",
            "heading": str(section.get("heading") or ""),
            "text": str(section.get("body") or ""),
            "bullets": _section_bullets(section),
        } for section in sections]

    cards_dir = out / "cards-3x4"
    cards_dir.mkdir(parents=True, exist_ok=True)
    footer = f"{author} · {palette['label']}" if author else palette["label"]
    cover = _draw_card(palette, events=[
        {"kind": "kicker", "text": "S24 · 一稿多发"},
        {"kind": "title", "text": title},
        {"kind": "rule"},
        {"kind": "body", "text": f"{len(items)} 节要点，读完带走一个结论。"},
    ], footer=footer)
    cover_path = cards_dir / "card-01.png"
    cover.save(cover_path)
    card_paths = [cover_path]
    for index, item in enumerate(items, start=2):
        heading = item.get("heading") or ""
        events = [
            {"kind": "kicker", "text": f"{index - 1:02d} / {len(items):02d}" + (f" · {item['kind']}" if exact else "")},
            *([{"kind": "title", "text": heading}] if heading else []),
            {"kind": "rule"},
            {"kind": "body", "text": item["text"]},
            *[{"kind": "bullet", "text": bullet} for bullet in (item.get("bullets") or [])[:2] if bullet != item["text"]],
        ]
        path = cards_dir / f"card-{index:02d}.png"
        _draw_card(palette, events=events, footer=footer).save(path)
        card_paths.append(path)

    long_events: list[dict[str, Any]] = [{"kind": "kicker", "text": "长图 · 一稿多发"}, {"kind": "title", "text": title}, {"kind": "rule"}]
    for item in items:
        if item.get("heading"):
            long_events.append({"kind": "title", "text": item["heading"]})
        long_events.append({"kind": "body", "text": item["text"]})
        long_events.extend({"kind": "bullet", "text": bullet} for bullet in (item.get("bullets") or []))
        long_events.append({"kind": "spacer", "size": 40})
    long_height = _estimate_long_height(long_events)
    long_img = _draw_card(palette, events=long_events, footer=footer, width=1080, height=long_height)
    long_path = out / "long-image.png"
    long_img.save(long_path)

    caption = _caption(title, items)
    (out / "caption.md").write_text(caption, encoding="utf-8")

    wechat_images: list[Path] = [cover_path]
    html_sections = []
    rendered_blocks: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not exact:
            section_path = cards_dir / f"card-{index + 2:02d}.png"
            if section_path.is_file():
                wechat_images.append(section_path)
        heading = item.get("heading") or ""
        bullets = "".join(
            f"<li style='margin:0 0 10px 0;color:{palette['fg']};font-size:16px;line-height:1.8'>{html.escape(b)}</li>"
            for b in (item.get("bullets") or [])
        )
        h2 = (
            f"<h2 style=\"margin:18px 0 10px;font-size:22px;color:{palette['accent']};"
            f"font-family:'{palette['font']}',sans-serif\">{html.escape(heading)}</h2>"
            if heading else ""
        )
        p = (
            f"<p data-block='{index}' style='margin:0 0 12px;font-size:16px;line-height:1.9;color:{palette['fg']};"
            f"font-family:'{palette['font']}',sans-serif'>{html.escape(item['text'])}</p>"
        )
        img = (
            f"<img src='{_data_uri(cards_dir / f'card-{index + 2:02d}.png')}' "
            "style='width:100%;border-radius:12px;display:block' alt=''/>"
            if (cards_dir / f"card-{index + 2:02d}.png").is_file() else ""
        )
        html_sections.append(
            f"<section data-block='{index}' style='margin:0 0 28px 0'>{h2}{p}"
            f"<ul style='margin:0 0 14px 22px;padding:0'>{bullets}</ul>{img}</section>"
        )
        rendered_blocks.append({"index": index, "kind": item["kind"], "text": item["text"]})

    article_html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        + html.escape(title)
        + "</title></head><body style='margin:0;background:"
        + palette["bg"]
        + ";padding:24px'>"
        "<div id='s24-article' style='max-width:720px;margin:0 auto;background:"
        + palette["bg"]
        + "'>"
        f"<img src='{_data_uri(cover_path)}' style='width:100%;border-radius:12px;display:block;margin-bottom:18px' alt=''/>"
        f"<h1 style=\"margin:0 0 18px;font-size:28px;line-height:1.35;color:{palette['fg']};"
        f"font-family:'{palette['font']}',sans-serif\">{html.escape(title)}</h1>"
        + "".join(html_sections)
        + "</div>"
        "<button onclick=\"(function(){var n=document.getElementById('s24-article');"
        "var r=document.createRange();r.selectNodeContents(n);var s=getSelection();"
        "s.removeAllRanges();s.addRange(r);document.execCommand('copy');"
        "this.textContent='已复制'})()\" style='position:fixed;right:20px;bottom:20px;"
        "padding:14px 22px;border:0;border-radius:999px;background:"
        + palette["accent"]
        + ";color:#fff;font-size:16px;cursor:pointer'>复制到公众号</button>"
        "</body></html>"
    )
    wechat_path = out / "wechat.html"
    wechat_path.write_text(article_html, encoding="utf-8")

    ledger_check = verify_article_render(source_blocks, rendered_blocks, mode="readback") if source_blocks else None
    manifest = {
        "schema": EXPORT_SCHEMA,
        "title": title,
        "theme": palette["id"],
        "ratio": ratio,
        "exact_blocks": exact,
        "paths": {
            "cards": [str(path) for path in card_paths],
            "caption": str(out / "caption.md"),
            "wechat_html": str(wechat_path),
            "long_image": str(long_path),
            "theme_css": str(out / "theme.css"),
        },
        "sha256": {path.name: _sha256_file(path) for path in [*card_paths, long_path, wechat_path]},
        "wechat_images_base64": len(wechat_images),
        "wechat_external_refs": 0,
        "ledger_check": ledger_check,
        "subtitle_style": css["subtitle_style"],
    }
    _write_json(out / "pack.json", manifest)
    return manifest


def _caption(title: str, sections: list[dict[str, Any]]) -> str:
    bullets = "\n".join(
        f"- {section.get('heading') or str(section.get('text') or '')[:18]}" for section in sections[:4]
    )
    tags = "#知识分享 #长图 #一稿多发 #内容创作"
    return f"{title}\n\n{bullets}\n\n{tags}\n"


def _data_uri(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"

# ---------------------------------------------------------------------------
# 4. 文章输入 + 原文块账本
# ---------------------------------------------------------------------------


class _ArticleParser:
    def __init__(self) -> None:
        from html.parser import HTMLParser

        class _Parser(HTMLParser):
            def __init__(self) -> None:
                super().__init__(convert_charrefs=True)
                self.stack: list[str] = []
                self.skip = 0
                self.chunks: list[str] = []
                self.title = ""
                self.author = ""
                self._in_title = False

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                attributes = dict(attrs)
                if tag in {"script", "style", "noscript"}:
                    self.skip += 1
                if tag == "title":
                    self._in_title = True
                if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3", "blockquote"}:
                    self.chunks.append("\n")
                if tag == "meta" and attributes.get("name") in {"author", "og:author"}:
                    self.author = attributes.get("content") or self.author
                self.stack.append(tag)

            def handle_endtag(self, tag: str) -> None:
                if tag in {"script", "style", "noscript"} and self.skip:
                    self.skip -= 1
                if tag == "title":
                    self._in_title = False
                if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "blockquote"}:
                    self.chunks.append("\n")
                if self.stack and self.stack[-1] == tag:
                    self.stack.pop()

            def handle_data(self, data: str) -> None:
                if self.skip:
                    return
                if self._in_title:
                    self.title = (self.title + data).strip()
                self.chunks.append(data)

        self.parser = _Parser()

    def parse(self, text: str) -> dict[str, str]:
        self.parser.feed(text)
        raw = "".join(self.parser.chunks)
        paragraphs = [_clean_text(part) for part in raw.splitlines()]
        body = "\n\n".join(part for part in paragraphs if part)
        return {"title": _clean_text(self.parser.title), "author": _clean_text(self.parser.author), "body": body}


def _read_source(source: str) -> tuple[str, str, str]:
    """返回 (platform, text, url)。"""
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "Mozilla/5.0 (compatible; hevi-s24/1.0)"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(8 * 1024 * 1024)
        platform = "wechat" if "mp.weixin.qq.com" in source else "web"
        return platform, raw.decode("utf-8", errors="replace"), source
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"文章不存在：{source}")
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "web", path.read_text(encoding="utf-8", errors="replace"), ""
    return "local", path.read_text(encoding="utf-8", errors="replace"), ""


def ingest_article(
    source: str,
    out_dir: str | Path,
    *,
    title: str = "",
    author: str = "",
    allow_network: bool = True,
) -> dict[str, Any]:
    """网页/公众号/Markdown → article.md + SHA-256 原文块账本。"""
    if source.startswith(("http://", "https://")) and not allow_network:
        raise ValueError("网络抓取被关闭；请先取得原文或打开 allow_network")
    platform, text, url = _read_source(source)
    if platform in {"web", "wechat"}:
        parsed = _ArticleParser().parse(text)
        body = parsed["body"]
        title = title or parsed["title"] or platform
        author = author or parsed["author"]
        if platform == "wechat":
            author = author or "微信公众号"
    else:
        body = text
        if body.lstrip().startswith("---"):
            lines = body.lstrip().split("\n")
            for cursor in range(1, len(lines)):
                if lines[cursor].strip() == "---":
                    body = "\n".join(lines[cursor + 1:])
                    break
        if not title:
            heading = next((line.lstrip("# ").strip() for line in body.splitlines() if line.startswith("# ")), "")
            title = heading or Path(source).stem
        if not author:
            author = "未知作者"
        if platform == "local" and Path(source).suffix.lower() in {".html", ".htm"}:
            parsed = _ArticleParser().parse(text)
            body = parsed["body"]
            title = title or parsed["title"]
            author = author or parsed["author"]

    body = _normalise_markdown(body)
    front_matter = (
        "---\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"author: {json.dumps(author or '未知作者', ensure_ascii=False)}\n"
        f"platform: {platform}\n"
        f"date: {datetime.now(UTC).date().isoformat()}\n"
        f"url: {json.dumps(url, ensure_ascii=False)}\n"
        "---\n\n"
    )
    heading = "" if body.lstrip().startswith("# ") else f"# {title}\n\n"
    article = front_matter + heading + body.strip() + "\n"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    article_path = out / "article.md"
    article_path.write_text(article, encoding="utf-8")
    ledger = lock_article_blocks(article, out_dir=out)
    _write_json(out / "meta.json", {
        "title": title, "author": author, "platform": platform, "url": url,
        "chars": _char_count(body), "article_sha256": _sha256_file(article_path),
    })
    return {
        "article_md": str(article_path),
        "meta": {"title": title, "author": author, "platform": platform, "url": url},
        "ledger": ledger,
        "chars": _char_count(body),
    }


def _normalise_markdown(text: str) -> str:
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                cleaned.append("")
            blank = True
            continue
        blank = False
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def split_article_blocks(article: str) -> list[dict[str, Any]]:
    lines = (article or "").replace("\r\n", "\n").split("\n")
    index = 0
    if lines and lines[0].strip() == "---":
        for cursor in range(1, len(lines)):
            if lines[cursor].strip() == "---":
                index = cursor + 1
                break
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal paragraph
        text = "\n".join(paragraph).strip()
        if text:
            blocks.append({"index": len(blocks), "kind": "paragraph", "text": text})
        paragraph = []

    for line in lines[index:]:
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            kind = "heading"
            blocks.append({"index": len(blocks), "kind": kind, "text": stripped.lstrip("#").strip()})
        elif stripped.startswith(("- ", "* ", "1. ")):
            flush()
            blocks.append({"index": len(blocks), "kind": "list_item", "text": stripped[2:].strip()})
        elif stripped.startswith(">"):
            flush()
            blocks.append({"index": len(blocks), "kind": "quote", "text": stripped.lstrip("> ").strip()})
        elif stripped.startswith("```"):
            flush()
            blocks.append({"index": len(blocks), "kind": "code", "text": stripped.strip("`")})
        else:
            paragraph.append(stripped)
    flush()
    for block in blocks:
        block["sha256"] = _sha256_text(block["text"])
        block["chars"] = _char_count(block["text"])
    return blocks


def lock_article_blocks(article: str, *, out_dir: str | Path) -> dict[str, Any]:
    blocks = split_article_blocks(article)
    ledger = {
        "schema": LEDGER_SCHEMA,
        "article_sha256": _sha256_text(article),
        "blocks": blocks,
        "locked_at": datetime.now(UTC).isoformat(),
    }
    _write_json(Path(out_dir) / "article_blocks.json", ledger)
    return {
        "schema": LEDGER_SCHEMA,
        "article_sha256": ledger["article_sha256"],
        "block_count": len(blocks),
        "blocks": [{"index": b["index"], "kind": b["kind"], "sha256": b["sha256"], "chars": b["chars"]} for b in blocks],
        "path": str(Path(out_dir) / "article_blocks.json"),
    }


def verify_article_render(
    ledger_blocks: list[dict[str, Any]],
    rendered_blocks: list[dict[str, Any]],
    *,
    mode: str = "readback",
) -> dict[str, Any]:
    """原文块账本对账：块数、顺序、逐块 SHA-256。"""
    mismatches: list[dict[str, Any]] = []
    if len(ledger_blocks) != len(rendered_blocks):
        mismatches.append({
            "index": -1,
            "kind": "count",
            "expected": len(ledger_blocks),
            "actual": len(rendered_blocks),
        })
    seen = min(len(ledger_blocks), len(rendered_blocks))
    for index in range(seen):
        expected = ledger_blocks[index]
        actual = rendered_blocks[index]
        actual_text = str(actual.get("text") or "")
        actual_hash = _sha256_text(actual_text)
        expected_hash = str(expected.get("sha256") or _sha256_text(str(expected.get("text") or "")))
        if actual_hash != expected_hash:
            mismatches.append({
                "index": index,
                "kind": "text",
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "expected_preview": str(expected.get("text") or "")[:40],
                "actual_preview": actual_text[:40],
            })
    return {
        "ok": not mismatches,
        "mode": mode,
        "ledger_blocks": len(ledger_blocks),
        "rendered_blocks": len(rendered_blocks),
        "matched": max(0, seen - len([m for m in mismatches if m.get("kind") == "text"])),
        "mismatches": mismatches,
    }


VIDEO_RIGHTS_BASES = {"self", "authorized", "licensed"}


def guard_video_transcript(
    *,
    url: str,
    rights_basis: str,
    author: str = "",
    declared: bool = False,
    bulk: bool = False,
) -> dict[str, Any]:
    """视频链接转逐字稿的授权门；不批量、不读 cookie。"""
    if bulk:
        raise ValueError("不批量抓取他人内容：一次只处理用户自己上传或声明有权使用的一条视频")
    if rights_basis not in VIDEO_RIGHTS_BASES:
        raise ValueError("需要声明授权：rights_basis 只能是 self / authorized / licensed")
    if rights_basis == "authorized" and not declared:
        raise ValueError("声明授权但未勾选确认；请先由用户确认")
    return {
        "ok": True,
        "url": url,
        "rights_basis": rights_basis,
        "author": author or "原作者（未提供）",
        "credit": f"内容来自 {author or '原作者'}；已按 {rights_basis} 声明使用。",
        "cookie_use": False,
        "bulk": False,
        "policy": "只处理用户本人上传或声明有权使用的内容；产出署原作者；不批量抓取；不读取浏览器 cookie。",
    }

# ---------------------------------------------------------------------------
# 5. 翻译校验（并入 localization_dub）
# ---------------------------------------------------------------------------


def extract_numbers(text: str) -> list[str]:
    normalised = (text or "").replace("，", ",").replace("．", ".").replace("％", "%")
    return [match.group(0).replace(" ", "") for match in _NUMBER_RE.finditer(normalised)]


def _number_key(token: str) -> str:
    """只比数字本体：2 ferments 与 2 次视为同一个 2。"""
    match = _NUMBER_RE.match(token.replace(" ", ""))
    raw = match.group(0) if match else token
    core = re.match(r"\d+(?:[.,]\d+)*\s*(?:%|％)?", raw)
    return (core.group(0) if core else raw).replace(",", "").replace(" ", "")


def check_localization(
    source_blocks: list[str],
    translated_blocks: list[str],
    *,
    source_lang: str = "",
    target_lang: str = "",
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if len(source_blocks) != len(translated_blocks):
        issues.append({
            "kind": "block_count",
            "severity": "fail",
            "detail": f"原文 {len(source_blocks)} 块，译文 {len(translated_blocks)} 块",
        })
    missing = 0
    number_loss: list[dict[str, Any]] = []
    for index in range(min(len(source_blocks), len(translated_blocks))):
        source = str(source_blocks[index] or "")
        translated = str(translated_blocks[index] or "")
        if source.strip() and not translated.strip():
            missing += 1
            issues.append({"kind": "omission", "severity": "fail", "index": index, "detail": "整块未翻译"})
            continue
        source_numbers = extract_numbers(source)
        translated_keys = {_number_key(item) for item in extract_numbers(translated)}
        for number in source_numbers:
            if _number_key(number) not in translated_keys:
                number_loss.append({"index": index, "number": number})
                issues.append({
                    "kind": "number_loss",
                    "severity": "fail",
                    "index": index,
                    "detail": f"第 {index + 1} 块丢失数字 {number}",
                })
    if len(source_blocks) > len(translated_blocks):
        missing += len(source_blocks) - len(translated_blocks)
    return {
        "ok": not any(issue["severity"] == "fail" for issue in issues),
        "source_lang": source_lang,
        "target_lang": target_lang,
        "block_count": {"source": len(source_blocks), "translated": len(translated_blocks)},
        "missing_blocks": missing,
        "number_loss": number_loss,
        "issues": issues,
        "counts": {
            "fail": sum(1 for issue in issues if issue["severity"] == "fail"),
            "warn": sum(1 for issue in issues if issue["severity"] == "warn"),
        },
    }

# ---------------------------------------------------------------------------
# 6. 合规：音色、AIGC、字体
# ---------------------------------------------------------------------------

VOICE_TIERS: tuple[dict[str, Any], ...] = (
    {
        "id": "pack",
        "label": "随包设计音色",
        "clone": False,
        "allowed": True,
        "requires": [],
        "policy": "可直接使用；按 S22 许可审计逐个音色登记来源。",
    },
    {
        "id": "cloned",
        "label": "克隆音色",
        "clone": True,
        "allowed": False,
        "requires": ["rights_basis=self", "export_confirmation"],
        "policy": "只接受用户本人授权上传；成片前必须确认一次。",
    },
)


def check_voice_tier(
    voice_id: str,
    *,
    cloned: bool,
    rights_basis: str = "",
    confirmed: bool = False,
) -> dict[str, Any]:
    if not cloned:
        return {
            "ok": True,
            "tier": "pack",
            "voice_id": voice_id,
            "policy": VOICE_TIERS[0]["policy"],
            "requires_confirmation": False,
        }
    if rights_basis != "self":
        raise ValueError("克隆音色只接受用户本人授权上传（rights_basis=self）")
    if not confirmed:
        return {
            "ok": False,
            "tier": "cloned",
            "voice_id": voice_id,
            "policy": VOICE_TIERS[1]["policy"],
            "requires_confirmation": True,
            "reason": "克隆音色成片前必须由用户确认一次",
        }
    return {
        "ok": True,
        "tier": "cloned",
        "voice_id": voice_id,
        "policy": VOICE_TIERS[1]["policy"],
        "requires_confirmation": True,
        "confirmed": True,
    }


def stamp_aigc(
    media_path: str | Path,
    out_path: str | Path,
    *,
    label: str = AIGC_LABEL,
    seconds: float = 2.0,
    extra_metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """首帧可见标识 + MP4 元数据写入 AIGC；返回 manifest。"""
    src = Path(media_path)
    if not src.is_file():
        raise FileNotFoundError(f"成片不存在：{src}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    font = next((path for path in _FONT_CANDIDATES if Path(path).is_file()), "")
    drawtext = (
        f"drawtext=text='{label}':x=36:y=36:fontsize=40:fontcolor=white@0.92:"
        "box=1:boxcolor=black@0.45:boxborderw=14"
    )
    if font:
        drawtext += f":fontfile='{font}'"
    drawtext += f":enable='lt(t,{seconds})'"
    metadata = {"comment": f"AIGC: {label}", "title": f"AIGC {label}", **(extra_metadata or {})}
    cmd = [_FFMPEG, "-y", "-i", str(src), "-vf", drawtext, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    for key, value in metadata.items():
        cmd.extend(["-metadata", f"{key}={value}"])
    cmd.extend(["-c:a", "copy", str(out)])
    proc = _run(cmd, timeout=600)
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"AIGC 标识写入失败：{proc.stderr[-400:]}")
    tags = _ffprobe_tags(out)
    manifest = {
        "schema": "hevi.s24.aigc.v1",
        "media": str(out),
        "sha256": _sha256_file(out),
        "label": label,
        "first_frame_visible_s": seconds,
        "metadata": metadata,
        "metadata_written": {key: tags.get(key) for key in metadata},
        "generated_at": datetime.now(UTC).isoformat(),
    }
    _write_json(out.with_suffix(".aigc.json"), manifest)
    return manifest


def _ffprobe_tags(path: Path) -> dict[str, str]:
    proc = _run([
        _FFPROBE, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path),
    ])
    if proc.returncode != 0:
        return {}
    payload = json.loads(proc.stdout or "{}")
    return {str(k).lower(): str(v) for k, v in (payload.get("format", {}).get("tags") or {}).items()}


FONT_LICENSES: tuple[dict[str, Any], ...] = (
    {
        "id": "noto-sans-cjk",
        "name": "Noto Sans CJK SC",
        "license": "OFL-1.1 (SIL Open Font License 1.1)",
        "commercial": True,
        "source": "Google Noto Fonts",
        "path": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    },
    {
        "id": "noto-serif-cjk",
        "name": "Noto Serif CJK SC",
        "license": "OFL-1.1 (SIL Open Font License 1.1)",
        "commercial": True,
        "source": "Google Noto Fonts",
        "path": "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    },
    {
        "id": "fusion-pixel",
        "name": "Fusion Pixel Font",
        "license": "OFL-1.1 (SIL Open Font License 1.1)",
        "commercial": True,
        "source": "third_party/fusion-pixel-font（OFL.txt）",
        "path": "third_party/fusion-pixel-font",
    },
    {
        "id": "be-vietnam-pro",
        "name": "Be Vietnam Pro",
        "license": "OFL-1.1 (SIL Open Font License 1.1)",
        "commercial": True,
        "source": "subtitle-fonts pack",
        "path": "assets/subtitle-fonts",
    },
    {
        "id": "patrick-hand",
        "name": "Patrick Hand",
        "license": "OFL-1.1 (SIL Open Font License 1.1)",
        "commercial": True,
        "source": "handwrite-font pack",
        "path": "assets/handwrite-font",
    },
    {
        "id": "charm",
        "name": "Charm",
        "license": "OFL-1.1 (SIL Open Font License 1.1)",
        "commercial": True,
        "source": "subtitle-fonts pack",
        "path": "assets/subtitle-fonts",
    },
)


def font_licenses(*, root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root) if root else Path.cwd()
    entries = []
    for item in FONT_LICENSES:
        record = dict(item)
        anchor = Path(record["path"])
        if not anchor.is_absolute():
            anchor = base / anchor
        record["installed"] = anchor.exists()
        record["risk"] = "low" if record["commercial"] else "high"
        entries.append(record)
    return {
        "entries": entries,
        "allowed": [item["id"] for item in entries if item["commercial"]],
        "blocked": [item["id"] for item in entries if not item["commercial"]],
        "policy": "字体只用 OFL 或明确可商用；逐个列许可，未登记的字体不得进成片。",
    }

# ---------------------------------------------------------------------------
# 汇总：给创建页与 API 用的计划
# ---------------------------------------------------------------------------


def plan_repurpose(
    *,
    format_id: str = "",
    topic: str = "",
    lines: list[str] | None = None,
    slots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lines = [str(line) for line in (lines or []) if str(line).strip()]
    theme = resolve_theme(slots.get("theme") if slots else None)
    return {
        "schema": SCHEMA,
        "format": format_id,
        "topic": topic,
        "delivery_review": {
            "schema": REVIEW_SCHEMA,
            "hard_limits": {
                "first_sentence_max_s": FIRST_SENTENCE_MAX_S,
                "first_sentence_max_chars": FIRST_SENTENCE_MAX_CHARS,
                "first_visual_max_s": FIRST_VISUAL_MAX_S,
                "static_max_s": STATIC_MAX_S,
                "speech_target_cps": SPEECH_TARGET_CPS,
                "speech_max_cps": SPEECH_MAX_CPS,
                "subtitle_max_line_chars": SUBTITLE_MAX_LINE_CHARS,
                "subtitle_min_dwell_s": SUBTITLE_MIN_DWELL_S,
                "subtitle_pause_hold_s": SUBTITLE_PAUSE_HOLD_S,
                "subtitle_blink_s": SUBTITLE_BLINK_S,
                "safe_area": SAFE_AREA,
                "lufs": LUFS_TARGET,
            },
            "nodes": [
                {"node": "script", "check": "首句 ≤5 秒且 ≤19 字", "retry": "重写首句"},
                {"node": "opening", "check": "首个画面信息 ≤2.5 秒", "retry": "前移首个画面"},
                {"node": "motion", "check": "画面静止 ≤5 秒", "retry": "加运动"},
                {"node": "narration", "check": "4.5 字/秒，单句 ≤5.2", "retry": "换种子；仍快则保音高放慢 ≤15%"},
                {"node": "subtitle", "check": "单行 ≤13 字、停留 ≥0.55s、1.4s 内不撤、闪断 0", "retry": "重排字幕后重烧"},
                {"node": "mix", "check": "-14 LUFS", "retry": "重混"},
            ],
        },
        "word_sync": {
            "trigger": "whisper_local_word_timestamps",
            "text_in_image": False,
            "overlay": "html_css",
            "applies_to": ["number_roll", "checklist", "compare", "quote"],
            "policy": "生成图里不放字；文字全部 HTML/CSS 叠加，与 S22 规则一致。",
        },
        "export_options": [
            {"id": "cards_3x4", "label": "小红书 3:4 卡片组 + 发帖文案", "path_key": "cards"},
            {"id": "wechat_html", "label": "公众号内联样式 HTML（base64 图，一键复制）", "path_key": "wechat_html"},
            {"id": "long_image", "label": "长图", "path_key": "long_image"},
        ],
        "theme": {"id": theme["id"], "label": theme["label"], "css": theme_css(theme)["css"]},
        "article": {
            "ingest": ["web", "wechat", "markdown"],
            "ledger": "sha256_per_block",
            "verify": "readback",
            "video_rights_bases": sorted(VIDEO_RIGHTS_BASES),
            "no_bulk": True,
            "no_cookies": True,
        },
        "localization": {
            "merged_into": "localization_dub",
            "checks": ["block_count", "omission", "number_loss"],
        },
        "compliance": {
            "voice_tiers": [dict(item) for item in VOICE_TIERS],
            "aigc": {"label": AIGC_LABEL, "first_frame": True, "mp4_metadata": True},
            "fonts": font_licenses(),
        },
        "line_hint": lines[:3],
    }


ALL_REVIEW_NODES = (
    "script", "opening", "motion", "narration", "subtitle", "mix",
)

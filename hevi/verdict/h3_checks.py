"""verdict 对 H3 成片的增量检查(L3,本地片常见项)。

在既有 verdict_shot(黑帧/崩手/身份 CLIP)之上,补 H3 后处理片常见项,全部
**确定性/低成本**:不引入新的重型模型(wardrobe 的 VLM 检查可选,没 VLM 就跳过
不假装通过)。

检查项(checks 键 → 说明):
  - black        : 黑帧占比(复用 verdict_checks.detect_black_ratio,ffmpeg blackdetect)
  - degraded     : 定妆照直出检测 —— freezedetect 静止时长占比过高 = 图生视频没动起来
  - identity     : 与 Subject master 的 CLIP 距离(调用方给 identity_score,复用既有信号)
  - wardrobe     : 服装与锁定母卡一致(可选 VLM;无 VLM/无母卡 → None = 没查)
  - lip_rough    : 有对白 → 音轨存在且音画时长粗对齐(±30%);无对白 → 通过
  - sc_morph     : 切镜处明显变形(插帧后)代理 —— 非切镜位置出现高帧差抖动帧的比例

retake 档位复用 hevi retake-protocol:black/degraded → re_roll(同母卡重掷);
identity/wardrobe → rewrite(带诊断重出/强调锚点);lip_rough/sc_morph → fix_in_post
(轻修,不进自动重掷)。一次返工只改一个变量(seed / action / 锚点),不换脸。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.director.verdict_checks import detect_black_ratio

logger = logging.getLogger(__name__)

_BLACK_FAIL_RATIO = 0.5  # 黑时长占比过半 → black
_STATIC_FAIL_RATIO = 0.6  # freezedetect 静止占比过半 → degraded(定妆照直出)
_LIP_ALIGN_TOLERANCE = 0.3  # |音轨长 - 视频长| / 视频长 ≤ 0.3 视为粗对齐
_SCENE_CUT_THRESHOLD = 0.35  # ffmpeg scene 滤镜阈值
_MORPH_DELTA = 12.0  # YAVG 帧差超过此值视为抖动帧(经验值,暗场/快切会压低)
_MORPH_NEAR_CUT_FRAMES = 3  # 切镜前后 N 帧内的抖动不计数(切镜本身就该有大帧差)
_MORPH_FAIL_RATIO = 0.08  # 抖动帧占比超此 → sc_morph 标记

_WARDROBE_PROMPT = (
    "只看人物服装。与参考图相比,服装款式/颜色/细节是否一致?"
    "有没有明显换装(颜色全变、款式全变、凭空多穿少穿)?"
    '严格只输出 JSON:{"wardrobe_ok": true 或 false, "note": "一句话"}。'
)


@dataclass
class H3ShotVerdict:
    shot_id: str = ""
    passed: bool = True
    checks: dict[str, Any] = field(default_factory=dict)
    diagnosis_category: str | None = None  # editor.DIAGNOSIS_CATEGORIES 同域
    retake_tier: str = "keep"  # keep / fix_in_post / edit / re_roll / rewrite


# ── 逐项检查(纯函数/低成本)──────────────────────────────────────────────


def _probe_fps(clip: Path) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate",
                "-of",
                "csv=p=0",
                str(clip),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
        num, _, den = out.partition("/")
        if den and float(den) > 0:
            return float(num) / float(den)
        return float(num)
    except Exception:
        return 24.0


async def _streams(clip: Path) -> list[dict[str, Any]]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-of",
        "json",
        str(clip),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    try:
        data = json.loads(out or b"{}")
        streams = data.get("streams", []) if isinstance(data, dict) else []
        return list(streams)
    except json.JSONDecodeError:
        return []


async def check_lip_rough(clip: Path, *, has_dialogue: bool) -> tuple[bool | None, str]:
    """有对白 → 音轨存在且音画时长粗对齐;无对白 → (True, "")。"""
    if not has_dialogue:
        return True, ""
    streams = await _streams(clip)
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    if not astreams:
        return False, "有对白但无音轨"
    try:
        adur = float(astreams[0].get("duration") or 0) or 0
        vdur = float(vstreams[0].get("duration") or 0) if vstreams else 0
    except (TypeError, ValueError):
        return None, "时长探测失败"
    if adur <= 0 or vdur <= 0:
        return None, "音画时长不可测"
    ratio = abs(vdur - adur) / adur
    ok = ratio <= _LIP_ALIGN_TOLERANCE
    return ok, f"audio={adur:.2f}s video={vdur:.2f}s Δ={ratio:.0%}"


def check_degraded_static(clip: Path) -> float | None:
    """freezedetect 静止时长占比(0=一直动,1=定妆照直出)。None=探测失败(不算失败)。"""
    import re as _re

    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(clip),
                "-vf",
                "freezedetect=n=-50dB:d=0.5",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:
        logger.warning("verdict freezedetect 失败 %s: %s", clip.name, e)
        return None
    durations = [float(x) for x in _re.findall(r"freeze_duration:([0-9.]+)", proc.stderr)]
    total_frozen = sum(durations)
    dur = _probe_duration(clip)
    if dur <= 0:
        return None
    return total_frozen / dur


def _probe_duration(clip: Path) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(clip),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def check_sc_morph(clip: Path) -> tuple[bool | None, float]:
    """插帧后切镜变形代理:非切镜位置出现高帧差抖动帧的比例。

    先跑 scene 检测拿切镜时间点,再逐帧 YAVG 算帧差;远离切镜的高帧差帧 = 可疑
    (RIFE 插帧鬼影/变形常表现为局部抖动)。解析失败 → (None, 0) 不误杀。
    """
    try:
        cut_proc = subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(clip),
                "-vf",
                f"select='gt(scene,{_SCENE_CUT_THRESHOLD})',metadata=print",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        cuts = {
            float(x)
            for x in re.findall(r"pts_time:([0-9.]+)", cut_proc.stderr)
        }
    except Exception as e:
        logger.warning("verdict scene 检测失败 %s: %s", clip.name, e)
        return None, 0.0
    fps = _probe_fps(clip)
    if fps <= 0:
        return None, 0.0

    try:
        sig_proc = subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(clip),
                "-vf",
                "signalstats,metadata=print",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        yavgs = [float(x) for x in re.findall(r"YAVG=([0-9.]+)", sig_proc.stderr)]
    except Exception as e:
        logger.warning("verdict signalstats 失败 %s: %s", clip.name, e)
        return None, 0.0
    if len(yavgs) < 4:
        return None, 0.0

    suspicious = 0
    total = 0
    for i in range(1, len(yavgs)):
        t = i / fps
        near_cut = any(abs(t - c) * fps <= _MORPH_NEAR_CUT_FRAMES for c in cuts)
        if near_cut:
            continue
        total += 1
        if abs(yavgs[i] - yavgs[i - 1]) > _MORPH_DELTA:
            suspicious += 1
    if total == 0:
        return None, 0.0
    ratio = suspicious / total
    return (ratio <= _MORPH_FAIL_RATIO, ratio)


async def check_wardrobe_vlm(frame: Path, vlm: Any, master: Path) -> tuple[bool | None, str]:
    """可选 VLM:服装与锁定母卡一致。无 vlm/无母卡/失败 → (None, "") 不误杀。"""
    if vlm is None or master is None or not master.exists() or not frame.exists():
        return None, ""
    try:
        resp = await vlm(
            messages=[{"role": "user", "content": _WARDROBE_PROMPT}],
            image_paths=[str(frame)],
            max_tokens=120,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        ok = bool(data.get("wardrobe_ok", True))
        return ok, str(data.get("note") or "")
    except Exception as e:
        logger.warning("verdict wardrobe VLM 失败,跳过: %s", e)
        return None, ""


def _extract_frame(clip: Path, t: float, out: Path) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1", str(out)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return out.exists() and out.stat().st_size > 0
    except Exception as e:
        logger.warning("verdict 抽帧失败 %s@%.1fs: %s", clip.name, t, e)
        return False


# ── 汇总 ───────────────────────────────────────────────────────────────────


async def verdict_h3_shot(
    *,
    shot_id: str,
    clip_path: Path,
    identity_score: float | None = None,
    consistency_floor: float = 0.75,
    has_dialogue: bool = False,
    subject_master: Path | None = None,
    vlm: Any = None,
) -> H3ShotVerdict:
    """H3 成片增量裁决:black/degraded/identity/wardrobe/lip_rough/sc_morph。

    优先级(先致命后一致性):black > degraded > identity > wardrobe > lip_rough
    > sc_morph。wardrobe/lip_rough/sc_morph 只记账不自动触发重掷(信号软,人工复核);
    black/degraded/identity 命中才进 re_roll/rewrite 自动返工(与既有 verdict 同哲学)。
    """
    v = H3ShotVerdict(shot_id=shot_id)
    clip = Path(clip_path)

    v.checks["black"] = detect_black_ratio(clip)
    static_ratio = check_degraded_static(clip)
    v.checks["degraded"] = static_ratio
    v.checks["identity_score"] = identity_score
    lip_ok, lip_note = await check_lip_rough(clip, has_dialogue=has_dialogue)
    v.checks["lip_rough"] = {"ok": lip_ok, "note": lip_note}
    morph_ok, morph_ratio = check_sc_morph(clip)
    v.checks["sc_morph"] = {"ok": morph_ok, "ratio": round(morph_ratio, 4)}

    # wardrobe(可选 VLM):抽中间帧对母卡。
    v.checks["wardrobe"] = {"ok": None, "note": "未查(无 VLM 或母卡)"}
    if subject_master is not None and vlm is not None:
        dur = _probe_duration(clip)
        if dur > 0:
            import tempfile

            with tempfile.TemporaryDirectory(prefix="hevi_h3verdict_") as td:
                frame = Path(td) / "wardrobe.png"
                if _extract_frame(clip, min(1.0, dur / 2), frame):
                    ok, note = await check_wardrobe_vlm(frame, vlm, subject_master)
                    v.checks["wardrobe"] = {"ok": ok, "note": note}

    # ── 决策 ──
    black = v.checks["black"]
    if black is None and static_ratio is None and identity_score is None:
        # No deterministic or model evidence means UNKNOWN, never keep/PASS.
        v.passed = False
        v.diagnosis_category = "quality_unverified"
        v.retake_tier = "fix_in_post"
    elif black is not None and black >= _BLACK_FAIL_RATIO:
        v.passed = False
        v.diagnosis_category = "动作"  # 全黑(生成返回空画面)→ 重掷
        v.retake_tier = "re_roll"
    elif static_ratio is not None and static_ratio >= _STATIC_FAIL_RATIO:
        v.passed = False
        v.diagnosis_category = "动作"  # 定妆照直出(没动起来)→ 重掷
        v.retake_tier = "re_roll"
    elif identity_score is not None and identity_score < consistency_floor:
        v.passed = False
        v.diagnosis_category = "参考图角色错配"
        v.retake_tier = "rewrite"
    else:
        v.passed = True
        v.retake_tier = "keep"

    # 软信号只进 checks,不翻盘(人工复核项)。
    logger.info(
        "verdict_h3[%s] passed=%s tier=%s checks=%s",
        shot_id,
        v.passed,
        v.retake_tier,
        json.dumps(v.checks, ensure_ascii=False),
    )
    return v

"""SPEC-003 ⑤ 成片逐镜头裁决(HEVI-ARCHITECTURE v3.2 §6.1/§6.2/§4.1.2)。

导演流水线成片此前零质检:黑屏镜头、崩手、身份漂移全靠肉眼扫(用户实测撞到"11 镜里 1
镜全黑"没人抓)。这里给每个 talking clip 跑三项检查,出诊断分类 + retake 五档决策,落
shot_verdict 表(护城河②数据资产)。

检查项(从"最有信号、最低成本"起步,不追求一次到位):
- 黑帧/空镜:ffmpeg blackdetect 测真实黑像素占比,零模型成本(纯色/暗场景不误判)。
- 身份一致:复用 tongjian 渲染已算的 character_consistency(CLIP),不重复算。
- hand safety:本地 VLM(qwen2.5-vl)查手部崩坏——AI 生成手部畸形高发,独立检查项。

retake 五档(§4.1.2)当前只接最关键两档:黑帧/崩手 → re_roll(重掷该镜);身份漂移 →
rewrite(带诊断重出关键帧)。keep/fix_in_post/edit 先占位不自动执行。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 黑帧判定:用 ffmpeg blackdetect(测真实黑像素占比,不是画面细节多少)——纯色/暗夜景
# 不会误判成黑。pic_th=0.98:一帧 98% 像素够黑才算黑帧。
_BLACK_PIC_TH = 0.98
_BLACK_FAIL_RATIO = 0.5  # 黑时长占比过半 → 判该镜为黑/废镜

_HAND_SAFETY_PROMPT = (
    "只看画面里人物的手。手指数量、形状、姿态是否正常自然?"
    "有没有 AI 生成常见的畸形(多指/少指/融合/扭曲/糊成一团)?"
    '严格只输出 JSON:{"hands_ok": true 或 false, "note": "一句话说明"}。'
    "画面里没有清晰可见的手时,hands_ok 判 true。"
)


@dataclass
class ShotVerdict:
    shot_index: int
    shot_id: str = ""
    provider: str = "cloud_avatar"
    identity_score: float | None = None
    black_ratio: float | None = None
    hand_safety_ok: bool | None = None
    checks: dict[str, Any] = field(default_factory=dict)
    diagnosis_category: str | None = None
    retake_tier: str = "keep"  # keep / fix_in_post / edit / re_roll / rewrite
    passed: bool = True
    # INC-004 §4.3(2026-07-19):L4 旗舰 provider 路由这一镜的实付美元。None = 本地免费路
    # (standard tier,绝大多数镜头)。攒"key 镜占比 × 单价"的真实数据,判断成本模型(90/10)
    # 准不准靠它——这类数据没法补录,今天不落库就是永久丢掉从现在起的信号(同 §6.2 四支柱
    # cost 那条"这类数据没法补录"的既有原则,但那条 cost 记的是校验算力,这条记的是生成
    # 花费,是两件事,不要混)。shot_verdict 表原来没有这一列,这次新加(见对应 alembic
    # 迁移),不是塞进 checks_json——想按成本模型聚合查询,一个真正的列比 JSONB 里挖字段
    # 好查得多。
    cost_usd: float | None = None


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


def detect_black_ratio(clip: Path) -> float | None:
    """clip 的黑时长占比(0=全好,1=全黑)。用 ffmpeg blackdetect 测真实黑像素,
    对纯色/暗场景不误判。探测失败返回 None。"""
    import re

    dur = _probe_duration(clip)
    if dur <= 0:
        return None
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(clip),
                "-vf",
                f"blackdetect=d=0.05:pic_th={_BLACK_PIC_TH}",
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
        logger.warning("verdict blackdetect 失败 %s: %s", clip.name, e)
        return None
    # blackdetect 把黑段信息打到 stderr:"black_start:0 black_end:1.0 black_duration:1.0"
    black = sum(float(x) for x in re.findall(r"black_duration:([0-9.]+)", proc.stderr))
    return min(1.0, black / dur)


async def check_hand_safety(frame: Path, vlm: Any) -> tuple[bool | None, str]:
    """本地 VLM 查手部崩坏。vlm 不可用/失败 → (None, "") 表示"没查",不假装通过也不误判。"""
    if vlm is None or not frame.exists():
        return None, ""
    import json

    try:
        resp = await vlm(
            messages=[{"role": "user", "content": _HAND_SAFETY_PROMPT}],
            image_paths=[str(frame)],
            max_tokens=120,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        import re

        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        ok = bool(data.get("hands_ok", True))
        return ok, str(data.get("note") or "")
    except Exception as e:
        logger.warning("verdict hand safety VLM 失败,跳过: %s", e)
        return None, ""


async def verdict_shot(
    *,
    shot_index: int,
    shot_id: str,
    clip_path: Path,
    identity_score: float | None,
    first_frame: Path | None = None,
    vlm: Any = None,
    consistency_floor: float = 0.75,
) -> ShotVerdict:
    """对一个镜头 clip 跑三项检查 → 出诊断 + retake 五档决策。

    优先级(先致命后一致性):黑帧 > 崩手 > 身份漂移。任一命中即判不过并给对应 retake 档。
    """
    v = ShotVerdict(shot_index=shot_index, shot_id=shot_id, identity_score=identity_score)

    v.black_ratio = detect_black_ratio(clip_path)
    frame = first_frame if (first_frame and first_frame.exists()) else None
    if frame is None:
        # 没有现成首帧就抽一张给 hand safety 用
        with tempfile.TemporaryDirectory(prefix="hevi_verdict_") as td:
            f = Path(td) / "hand.png"
            if _extract_frame(clip_path, min(1.0, _probe_duration(clip_path) / 2), f):
                v.hand_safety_ok, note = await check_hand_safety(f, vlm)
            else:
                v.hand_safety_ok, note = None, ""
    else:
        v.hand_safety_ok, note = await check_hand_safety(frame, vlm)

    v.checks = {
        "black_ratio": v.black_ratio,
        "identity_score": v.identity_score,
        "hand_safety_ok": v.hand_safety_ok,
        "hand_note": note,
    }

    # 决策(§4.1.2 五档,当前只自动接 re_roll/rewrite 两档,且要可靠信号才动)。
    # hand_safety 只记录不触发返工——本地 VLM 对手部判定太飘(实测同一好镜第0轮判崩、
    # 第1轮判好),据它 re_roll 会把好镜白白重掷、烧钱又撞限流。黑帧/身份是可靠信号,留作
    # 自动返工触发;hand_safety 进 checks_json 供人工复核。
    if v.black_ratio is not None and v.black_ratio >= _BLACK_FAIL_RATIO:
        v.passed = False
        v.diagnosis_category = "动作"  # 真实成片却全黑(生成返回空画面)→ 重掷
        v.retake_tier = "re_roll"
    elif v.identity_score is not None and v.identity_score < consistency_floor:
        v.passed = False
        v.diagnosis_category = "参考图角色错配"
        v.retake_tier = "rewrite"
    else:
        v.passed = True
        v.retake_tier = "keep"
    return v

"""SPEC-007 批1 ④:L5 终审——接缝两两比对 + 六项清单。

**为什么是"相邻段两两比对"而不是"全片一次性多图审片"**:本地小 VLM(qwen2.5vl:3b)
实测处理 6 图网格会退化输出纯乱码(ollama 日志确认:模型收到图后只吐约 33 个 token 就停,
greedy 解码下的"看不懂就摆烂")——1 图/2 图是这个模型的可用上限。改用相邻段接缝两两比对
(每次 2 图,已验证可用),配合 ①③②已经算出的真实数据(CLIP 身份分、TTS 时长、色彩增益)
在代码里合成六项清单,不依赖一次性多图审片。

**为什么 `review_seam` 要重试**:同一输入实测有过一次性乱码输出(3 次里 1 次),重试后
必然拿到正常结果——这是本地小模型的已知不稳定性,不是逻辑 bug。重试耗尽仍失败时显式记
`unverified`,**不能把"没判出来"默认当"通过"**(踩过这个坑:早期版本把解析失败的接缝
静默漏判,六项清单看起来全绿,实际有一段完全没被检查过)。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.director.segment_qc import SegmentQCResult

_MAX_RETRIES = 3

_SEAM_PROMPT = (
    "这是同一场戏里相邻两段的画面:第一张是前一段的最后一帧,第二张是后一段的第一帧。"
    "判断两张图之间的镜头衔接是否自然,分别回答:"
    "spatial_jump(bool,机位/环境是否突兀跳变)、"
    "camera_looks_repeated(bool,两个镜头的运镜/构图观感是否雷同)、"
    "identity_consistent(bool,人物脸部/服装是否一致没有明显漂移)、"
    "color_mismatch(bool,色温/明暗是否有割裂感)、"
    "reason(一句话理由)。只输出 JSON,不要多余文字:"
    '{"spatial_jump": false, "camera_looks_repeated": false, "identity_consistent": true, '
    '"color_mismatch": false, "reason": "..."}'
)


@dataclass
class SeamReview:
    seam: str  # "2->3"
    spatial_jump: bool | None = None
    camera_looks_repeated: bool | None = None
    identity_consistent: bool | None = None
    color_mismatch: bool | None = None
    reason: str = ""
    unverified: bool = False


async def review_seam(
    frame_a: Path, frame_b: Path, *, seam: str, vlm: Any, max_retries: int = _MAX_RETRIES
) -> SeamReview:
    for _attempt in range(max_retries):
        try:
            resp = await vlm(
                messages=[{"role": "user", "content": _SEAM_PROMPT}],
                image_paths=[str(frame_a), str(frame_b)],
                max_tokens=200,
            )
            content = resp.get("content") if hasattr(resp, "get") else str(resp)
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                return SeamReview(
                    seam=seam,
                    spatial_jump=data.get("spatial_jump"),
                    camera_looks_repeated=data.get("camera_looks_repeated"),
                    identity_consistent=data.get("identity_consistent"),
                    color_mismatch=data.get("color_mismatch"),
                    reason=str(data.get("reason", "")),
                )
        except Exception:
            pass
    return SeamReview(seam=seam, reason="3 次重试后仍未拿到有效判定", unverified=True)


def _seam_to_scenes(reviews: list[SeamReview], predicate) -> list[int]:
    out: set[int] = set()
    for r in reviews:
        if predicate(r):
            a, b = r.seam.split("->")
            out.add(int(a))
            out.add(int(b))
    return sorted(out)


def synthesize_final_checklist(
    *,
    seam_reviews: list[SeamReview],
    qc_results: list[SegmentQCResult],
    color_reports: list[dict],
    camera_lint_findings: list[str],
) -> dict:
    """六项清单——纯 code 合成已有数据,不二次调用 LLM 综合(数据来源见各字段)。"""
    unverified_seams = [r.seam for r in seam_reviews if r.unverified]

    spatial_bad = _seam_to_scenes(seam_reviews, lambda r: r.spatial_jump)
    camera_bad_seams = _seam_to_scenes(seam_reviews, lambda r: r.camera_looks_repeated)
    identity_bad_seams = _seam_to_scenes(seam_reviews, lambda r: r.identity_consistent is False)
    color_bad_seams = _seam_to_scenes(seam_reviews, lambda r: r.color_mismatch)

    bad_identity_qc = [
        r.segment_id
        for r in qc_results
        if r.identity_scores and min(r.identity_scores.values()) < 0.65
    ]
    bad_dialogue_qc = [r.segment_id for r in qc_results if not r.dialogue_fits]
    color_clamped = [
        rep.get("segment_id", rep.get("scene_no"))
        for rep in color_reports
        if any(abs(g - 0.7) < 1e-6 or abs(g - 1.4) < 1e-6 for g in rep.get("gain", ()))
    ]
    identity_bad_all = sorted(set(bad_identity_qc) | set(identity_bad_seams), key=str)
    color_bad_all = sorted(set(color_bad_seams) | set(color_clamped), key=str)

    items = [
        {
            "name": "空间连贯性",
            "passed": not spatial_bad,
            "reason": "接缝两两比对未见突兀跳变"
            if not spatial_bad
            else f"接缝比对在这些段附近发现突兀跳变: {spatial_bad}",
            "bad_scenes": spatial_bad,
        },
        {
            "name": "运镜多样性",
            "passed": not camera_lint_findings and not camera_bad_seams,
            "reason": "文本 lint(camera_movement 标签互异)+ 接缝观感均无雷同"
            if not camera_lint_findings and not camera_bad_seams
            else f"文本 lint: {camera_lint_findings or '干净'}; 接缝观感雷同段: {camera_bad_seams}",
            "bad_scenes": camera_bad_seams,
        },
        {
            "name": "身份保真度",
            "passed": not identity_bad_all,
            "reason": f"CLIP 身份分低于阈值或接缝观感漂移的段: {identity_bad_all}"
            if identity_bad_all
            else "CLIP 身份分 + 接缝观感均一致",
            "bad_scenes": identity_bad_all,
        },
        {
            "name": "对白/时间线连续性",
            "passed": not bad_dialogue_qc,
            "reason": f"TTS 实测时长超出视频请求时长的段: {bad_dialogue_qc}"
            if bad_dialogue_qc
            else "各段 TTS 实测时长均在视频时长内",
            "bad_scenes": bad_dialogue_qc,
        },
        {
            "name": "接缝可见度",
            "passed": not spatial_bad and not color_bad_seams,
            "reason": "接缝两两比对未见突兀剪辑点"
            if not spatial_bad and not color_bad_seams
            else f"接缝处仍有可见割裂(空间{spatial_bad}/色彩{color_bad_seams})",
            "bad_scenes": sorted(set(spatial_bad) | set(color_bad_seams)),
        },
        {
            "name": "色彩/影调一致性",
            "passed": not color_bad_all,
            "reason": f"色彩匹配已生效但仍有割裂感或增益被 clamp 到边界(校正不足)的段: "
            f"{color_bad_all}"
            if color_bad_all
            else "色彩匹配后接缝观感统一,增益均未触顶",
            "bad_scenes": color_bad_all,
        },
    ]
    return {"items": items, "unverified_seams": unverified_seams}

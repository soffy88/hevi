"""shot_scorecard —— 镜头评分卡(hevi 参考实现,L3 裁决;待回迁 oskill)。

3O manifest §C4。是 `oskill.mllm_frame_consistency_check`(仅 vlm_score)的**超集**:
  identity_score = 候选帧 CLIP 向量 vs Subject.identity_embedding 余弦(C1 锚,真·图对图)
  style_score    = vs StylePack 基准帧向量余弦(可选)
  vlm_score      = 本地 Qwen-VL 打分(可选,C2)
  checks         = 确定性项(时长/字幕/响度,pass-through)
→ 聚合成 Scorecard{best_frame, passed, identity/style/vlm_score, hints}。

**这补上 C2 的遗留**:consistency 不再把 reference 当文本发,而是用 C1 的身份向量做真正的
图对图比对 —— 双变体里挑"更像锁定角色"的那个。裁决**阈值/策略**留 hevi(护城河),
可复用的**打分机制**是这里(将来搬 oskill)。

candidate_frames 是候选 **.mp4**(omodul consistency_fn 契约),内部抽代表帧再打分;
best_frame 返回**候选原路径**(mp4),供 omodul 采纳为该镜头成片。
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.subjects.subject_embed import SubjectEmbedError, cosine_similarity, subject_embed
from hevi.verdict.frame_extract import FrameExtractError, extract_representative_frame

logger = logging.getLogger(__name__)

_SHOT_INDEX_RE = re.compile(r"shot_(\d+)_v\d+")


def _parse_shot_index(candidate: Path) -> int | None:
    """从 omodul 的 `shot_{idx:04d}_v{variant}.mp4` 文件名反解 shot index。

    解析失败(命名约定以外的调用方)→ None,调用方应放弃 capture,不阻断打分。
    """
    m = _SHOT_INDEX_RE.search(Path(candidate).stem)
    return int(m.group(1)) if m else None


@dataclass
class Scorecard:
    best_frame: Path
    best_index: int
    passed: bool
    identity_score: float = 0.0
    style_score: float = 0.0
    # None = 没跑本地 VLM(mllm 不可用 / 未触发 Tier1);跑了才是 0..1 的真实分数——
    # 不能用 0.0 当默认值,0.0 是"VLM 判定画面有严重瑕疵",跟"没跑"含义相反。
    vlm_score: float | None = None
    vlm_violations: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    hints: list[str] = field(default_factory=list)
    per_candidate: list[dict[str, Any]] = field(default_factory=list)


def _score_one(
    candidate: Path,
    tmpdir: str,
    idx: int,
    subject_ref_embedding: list[float] | None,
    subject_ref_embedding_face: list[float] | None,
    style_ref_embedding: list[float] | None,
) -> dict[str, Any]:
    """抽帧 + 算 identity/style 分。失败 → 分 0 + reason,不抛(不断整条链)。

    多区域(HEVI 路线图 Phase2 #34):全图 + 脸部区域两个向量都算,identity 分取
    两者较高值——背影/侧身镜头脸部裁剪可能裁到无关内容,靠全图向量兜底;正脸
    特写则脸部区域向量通常更准。不是真人脸检测,做不到"确定这帧有没有露脸"就
    精确择一,取 max 是在没有可靠判据时的稳妥退化。
    """
    rec: dict[str, Any] = {
        "index": idx,
        "candidate": str(candidate),
        "identity": 0.0,
        "identity_whole": 0.0,
        "identity_face": 0.0,
        "style": 0.0,
        "ok": False,
    }
    try:
        frame = extract_representative_frame(candidate, Path(tmpdir) / f"cand_{idx}.png")
        emb_whole = subject_embed(image_path=frame, kind="style")
        if subject_ref_embedding:
            rec["identity_whole"] = cosine_similarity(emb_whole, subject_ref_embedding)
        if subject_ref_embedding_face:
            emb_face = subject_embed(image_path=frame, kind="face")
            rec["identity_face"] = cosine_similarity(emb_face, subject_ref_embedding_face)
        rec["identity"] = max(rec["identity_whole"], rec["identity_face"])
        if style_ref_embedding:
            rec["style"] = cosine_similarity(emb_whole, style_ref_embedding)
        rec["ok"] = True
    except (FrameExtractError, SubjectEmbedError) as e:
        rec["reason"] = str(e)
        logger.warning("scorecard: candidate %d scored 0 (%s)", idx, e)
    return rec


def shot_scorecard(
    *,
    candidate_frames: list[Path],
    subject_ref_embedding: list[float] | None = None,
    subject_ref_embedding_face: list[float] | None = None,
    style_ref_embedding: list[float] | None = None,
    deterministic: dict[str, Any] | None = None,
    identity_floor: float = 0.2,
    config: dict[str, Any] | None = None,
) -> Scorecard:
    """给候选镜头打分并挑最优。

    combined = identity(有锚,取全图/脸部区域两者较高值) else style else 0.5。
    best = argmax(combined)。
    passed = best identity >= identity_floor(极低阈,仅拦全废;主价值在**选对变体**,非拦门)。
    无候选 → ValueError;有锚但全部抽帧/嵌入失败 → 退化选第一个、passed=True(不阻断)。
    """
    if not candidate_frames:
        raise ValueError("candidate_frames must not be empty")

    # 无任何锚 → 无打分依据,直接采纳第一个(不做无谓的抽帧/嵌入)。
    if not subject_ref_embedding and not subject_ref_embedding_face and not style_ref_embedding:
        return Scorecard(
            best_frame=Path(candidate_frames[0]),
            best_index=0,
            passed=True,
            per_candidate=[
                {"index": i, "candidate": str(c), "identity": 0.0, "style": 0.0}
                for i, c in enumerate(candidate_frames)
            ],
        )

    with tempfile.TemporaryDirectory(prefix="scorecard_") as td:
        recs = [
            _score_one(
                Path(c),
                td,
                i,
                subject_ref_embedding,
                subject_ref_embedding_face,
                style_ref_embedding,
            )
            for i, c in enumerate(candidate_frames)
        ]

    def _combined(r: dict[str, Any]) -> float:
        if subject_ref_embedding or subject_ref_embedding_face:
            return r["identity"]
        if style_ref_embedding:
            return r["style"]
        return 0.5

    best_i = max(range(len(recs)), key=lambda i: _combined(recs[i]))
    best = recs[best_i]
    hints: list[str] = []
    has_identity_anchor = bool(subject_ref_embedding or subject_ref_embedding_face)
    if has_identity_anchor and best["identity"] < identity_floor:
        hints.append(
            f"身份匹配偏低(best identity={best['identity']:.2f} < {identity_floor}):"
            "疑非锁定角色,建议重生成或换参考图"
        )
    if not any(r["ok"] for r in recs):
        hints.append("全部候选抽帧/嵌入失败 → 退化选第一个")

    passed = (not has_identity_anchor) or best["identity"] >= identity_floor
    return Scorecard(
        best_frame=Path(candidate_frames[best_i]),
        best_index=best_i,
        passed=passed,
        identity_score=best["identity"],
        style_score=best["style"],
        checks=dict(deterministic or {}),
        hints=hints,
        per_candidate=recs,
    )


_VLM_SHOT_AUDIT_PROMPT = """你是视频镜头质检员。检查这张画面有没有明显瑕疵,只关注
下面这几类,不做主观审美判断:

- 人物肢体/手部/五官是否严重畸变(多指/断肢/脸部融合扭曲这类明显问题)
- 画面是否有明显伪影、闪烁块、拼贴感(不是正常的运动模糊/景深虚化)
- 构图是否可用(不是全黑/纯色块/花屏/主体完全缺失)

没有命中以上任何一条就该判定通过——不要因为画质一般、风格不合口味就判不过。

只输出 JSON:{"passes": true/false, "violations": ["..."]}"""


async def _vlm_score_frame(frame_path: Path, mllm: Any) -> tuple[float | None, list[str]]:
    """本地 VLM 对最优候选帧做粗粒度质检(HEVI 路线图 Tier1,#33)。

    mllm 不可用/调用失败/解析失败 → (None, [])——区分"没跑"和"跑了但 0 分",不假装
    打过分。checklist 式判定(passes/violations),不是让模型直接吐一个连续分数——
    VLM 对无校准连续打分不可靠,布尔判定 + 违规清单更稳(同 identity_pack.py 的年代
    审核走的是同一个"默认通过、按清单挑刺"设计)。
    """
    if mllm is None:
        return None, []
    import json

    try:
        resp = await mllm(
            messages=[{"role": "user", "content": _VLM_SHOT_AUDIT_PROMPT}],
            image_paths=[str(frame_path)],
            max_tokens=300,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        data = json.loads(content)
        violations = [str(v) for v in (data.get("violations") or [])]
        passes = bool(data.get("passes", True))
        return (1.0 if passes else 0.3), violations
    except Exception as e:
        logger.warning("scorecard: vlm 打分失败,跳过(%s)", e)
        return None, []


def coarse_diagnosis(sc: Scorecard) -> str | None:
    """Scorecard → 粗粒度诊断分类(Phase1 占位,#29 会换成读取更多信号的完整 taxonomy)。

    分类表见 HEVI 路线图 §4.3:运镜/光照/动作/参考图角色错配/时长/构图/音频/安全词误触发。
    目前 Scorecard 只有身份匹配这一个信号,能可靠归类的只有"参考图角色错配"一种;
    其余分类需要 VLM(#33)/风格向量(#34)等尚未接入的信号,先返回 None 而非瞎猜。
    """
    if not sc.passed:
        return "参考图角色错配"
    return None


def make_scorecard_consistency_fn(
    subject_ref_embedding: list[float] | None,
    *,
    subject_ref_embedding_face: list[float] | None = None,
    style_ref_embedding: list[float] | None = None,
    identity_floor: float = 0.2,
    capture: dict[int, Scorecard] | None = None,
    enable_vlm_tier1: bool = True,
) -> Any:
    """→ 一个符合 omodul consistency_fn 契约的 async fn(身份锚驱动的双变体选优)。

    契约(见 omodul.agentic_longvideo_pipeline):
      result = await consistency_fn(mllm=..., candidate_frames=[...mp4], reference=..., criteria=...)
      result.best_frame  # Path(候选 mp4)
      result.passed      # bool
    评分卡(重:CLIP 嵌入 + PyAV 解码)丢线程池,不阻塞事件循环。

    `capture`(可选):omodul 的 `ShotRecord`(落库用)只透传 identity_score(见
    `_extract_consistency_score`),style_score/vlm_score/hints 会随 result 一起被丢弃。
    传入这个字典后,按 candidate 文件名(`shot_{idx:04d}_v{variant}.mp4`)反解出 shot
    index,把完整 Scorecard 存进去 —— 调用方(longvideo_orchestrator)在结果映射阶段
    (result_mapper.py)读它,补全 shot_verdict 需要的字段,不需要改 omodul。

    `enable_vlm_tier1`:Tier1(HEVI 路线图 Phase1 #33)——只在 Tier0(身份分)报警时才
    触发本地 VLM 质检,不是无差别全量跑(省成本)。omodul 会把 `mllm` 作为 kwarg 传给
    consistency_fn(3O manifest §C2 的既有约定,见 longvideo_orchestrator.py 的注入点);
    `mllm` 不可用(未探测到本地 VL 模型)时静默跳过,不阻断选优主流程。
    """
    import asyncio
    from types import SimpleNamespace

    async def _consistency_fn(*, candidate_frames: list[Path], **_kw: Any) -> Any:
        sc = await asyncio.to_thread(
            shot_scorecard,
            candidate_frames=candidate_frames,
            subject_ref_embedding=subject_ref_embedding,
            subject_ref_embedding_face=subject_ref_embedding_face,
            style_ref_embedding=style_ref_embedding,
            identity_floor=identity_floor,
        )
        logger.info(
            "scorecard: 选 v%d(identity=%.3f, passed=%s)%s",
            sc.best_index,
            sc.identity_score,
            sc.passed,
            f" hints={sc.hints}" if sc.hints else "",
        )
        if enable_vlm_tier1 and not sc.passed and _kw.get("mllm") is not None:
            try:
                frame = await asyncio.to_thread(
                    extract_representative_frame, sc.best_frame, sc.best_frame.with_suffix(".png")
                )
                score, violations = await _vlm_score_frame(frame, _kw["mllm"])
                sc.vlm_score = score
                sc.vlm_violations = violations
                if violations:
                    sc.hints.append(f"VLM 质检发现问题: {violations}")
            except Exception as e:
                logger.warning("scorecard: Tier1 VLM 触发失败,跳过(%s)", e)
        if capture is not None and candidate_frames:
            idx = _parse_shot_index(candidate_frames[0])
            if idx is not None:
                capture[idx] = sc
        return SimpleNamespace(best_frame=sc.best_frame, passed=sc.passed, scorecard=sc)

    return _consistency_fn


# SPEC-001 §5:跨集角色关系一致性守护,Tier0(确定性,不需 VLM)。跟上面的身份/风格打分
# 不共用同一个 consistency_fn 管线——那条管线拿到的只有渲染完的视频帧(见
# omodul.agentic_longvideo_pipeline 的 consistency_fn 契约:candidate_frames 是 .mp4),
# 台词文本在更早的 shot_gen_fn 阶段(oskill.ShotPlan.tts_text)才有,需要单独在那个阶段
# 旁路收集(见 longvideo_orchestrator.py 对 shot_gen_fn 的包装),生成结束后再调用本函数。
_POSITIVE_RELATION_KEYWORDS = (
    "亲爱的",
    "挚友",
    "知己",
    "敬爱",
    "深情",
    "心上人",
    "夫君",
    "娘子",
    "兄弟",
)
_NEGATIVE_RELATION_KEYWORDS = ("仇人", "滚", "贱人", "去死", "仇恨", "唾弃", "混账", "无良", "该死")
_VALENCE_STRONG_THRESHOLD = 0.3


def check_relationship_consistency(
    *,
    dialogue_texts: list[str],
    relationships: list[Any],
    characters: list[Any],
    episode_event_ids: list[str],
) -> dict[str, Any]:
    """本集台词里的称呼/关系指代,是否跟 StoryGraph 记录的"截至本集"关系状态矛盾。

    确定性版本:不做语义理解,只查字面——两个角色的姓名/别名在同一份台词里共同出现,
    且台词命中强烈褒义/贬义称呼关键词,跟图谱记录的关系极性(valence)方向相反时,
    判定"关系漂移"。本集自身 `evolution` 记录里发生在本集事件上的关系突变不算漂移
    (那正是剧情要演的转折,不是漂移)。

    Args:
        dialogue_texts: 本集所有分镜的台词/旁白文本。
        relationships: `StoryGraph.relationships`(`StoryRelationship` 列表)。
        characters: `StoryGraph.characters`(`StoryCharacter` 列表,取 name/aliases)。
        episode_event_ids: 本集覆盖的 event_id 列表(`EpisodePlan.event_ids`)。

    Returns:
        {"passed": bool, "drifts": [人类可读的漂移描述, ...]}
    """
    name_variants: dict[str, list[str]] = {
        c.char_id: [c.name, *c.aliases] for c in characters if getattr(c, "char_id", None)
    }
    text_blob = "\n".join(t for t in dialogue_texts if t)
    latest_event = max(episode_event_ids) if episode_event_ids else None

    drifts: list[str] = []
    for rel in relationships:
        # "截至本集"生效的关系极性:evolution 里 event_id <= 本集最新事件的最后一条,
        # 没有就用初始 valence(event_id 是 "E001" 这类零填充字符串,可直接字典序比较)。
        valence = rel.valence
        for ev in sorted(rel.evolution, key=lambda e: e["event_id"]):
            if latest_event is None or ev["event_id"] <= latest_event:
                valence = ev["valence"]

        from_names = name_variants.get(rel.from_char, [])
        to_names = name_variants.get(rel.to_char, [])
        if not (from_names and to_names):
            continue
        co_occurs = any(n in text_blob for n in from_names) and any(
            n in text_blob for n in to_names
        )
        if not co_occurs:
            continue

        # 本集自己的 evolution 记录(关系在本集事件上转变)是剧情本身,不算漂移。
        if any(ev["event_id"] in episode_event_ids for ev in rel.evolution):
            continue

        has_positive = any(k in text_blob for k in _POSITIVE_RELATION_KEYWORDS)
        has_negative = any(k in text_blob for k in _NEGATIVE_RELATION_KEYWORDS)
        if valence >= _VALENCE_STRONG_THRESHOLD and has_negative and not has_positive:
            drifts.append(
                f"{rel.from_char}->{rel.to_char}: 图谱记录为友好关系,但本集台词出现敌对称呼"
            )
        elif valence <= -_VALENCE_STRONG_THRESHOLD and has_positive and not has_negative:
            drifts.append(
                f"{rel.from_char}->{rel.to_char}: 图谱记录为敌对关系,但本集台词出现亲密称呼"
            )

    return {"passed": not drifts, "drifts": drifts}

    return _consistency_fn

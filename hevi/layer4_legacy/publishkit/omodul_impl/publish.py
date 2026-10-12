"""发布前套件编排（omodul 层）。

输入 = 成片 + 文稿；输出 = ``publish_bundle/``：

* ``cover_16_9.jpg`` / ``cover_3_4.jpg`` / ``cover_4_3.jpg`` + ``cover_qa.json``
* ``copy.md``（八平台，按上游模板）+ ``copy.json``（机读）
* ``qa_report.json``（黑帧/静音/响度/A-V 对齐/字幕越界/解码）
* ``fact_sources.json``（事实核查清单与来源台账）
* ``compliance.json``（合规三条红线）

LLM 部分走仓库已有抽象（``oprim.llm.llm_call``）。零成本约束下默认不连任何
付费端点；只有显式给出本地 ``ollama`` provider 才走 LLM。LLM 不可用时**规则
降级**产出完整文案，并在报告里标明降级原因——不产出占位正文。
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.publishkit.omodul_impl.cover import build_covers, run_cover_qa
from hevi.layer4_legacy.publishkit.omodul_impl.qa import run_delivery_qa, script_audio_consistency
from hevi.layer4_legacy.publishkit.oprim_impl.contracts import (
    PLATFORMS,
    PlatformCopy,
    PublishBundleResult,
    PublishError,
    PublishGate,
)
from hevi.layer4_legacy.publishkit.oskill_impl.compliance import run_compliance
from hevi.layer4_legacy.publishkit.oskill_impl.fact_check import (
    build_source_ledger,
    extract_claims,
    hedge_warnings,
)
from hevi.layer4_legacy.publishkit.oskill_impl.platform_copy import (
    build_platform_copies,
    render_copy_md,
)
from hevi.layer4_legacy.publishkit.oskill_impl.script_doc import parse_script

BUNDLE_DIRNAME = "publish_bundle"


def _today() -> str:
    return _dt.date.today().isoformat()


def _llm_refine(prompt: str, *, provider: str | None) -> tuple[str | None, str]:
    """用仓库 LLM 抽象润色；无 key / 不连通时如实返回降级原因。"""

    if not provider:
        return None, "llm_not_configured:零成本约束下未配置本地 provider，全部由规则生成"
    try:
        from oprim.llm.llm_call import llm_call

        resp = llm_call(prompt, provider=provider, temperature=0.4)
        text = getattr(resp, "text", "") or ""
        if not text.strip():
            return None, f"llm_empty_response:{provider}"
        return text, f"llm_provider={provider}"
    except Exception as exc:
        return None, f"llm_unavailable:{type(exc).__name__}:{exc}"


def build_publish_bundle(
    *,
    video_path: Path,
    script_path: Path,
    output_dir: Path,
    config: dict[str, Any] | None = None,
) -> PublishBundleResult:
    """成片 + 文稿 → 完整发布产物包。"""

    config = config or {}
    video_path = Path(video_path).resolve()
    script_path = Path(script_path).resolve()
    output_dir = Path(output_dir).resolve()
    if not video_path.is_file():
        raise PublishError(f"VIDEO_MISSING: {video_path}")

    bundle_dir = output_dir / BUNDLE_DIRNAME
    bundle_dir.mkdir(parents=True, exist_ok=True)
    checked_on = config.get("checked_on") or _today()

    # 1. 文稿（解析失败直接报错，不降级成占位正文）
    doc = parse_script(script_path)
    if config.get("topic"):
        # 调用方确实知道主题（如白板分镜的 topic）时用它，比从首句猜更准
        doc = replace(doc, topic=str(config["topic"]))
    if config.get("brand"):
        doc = replace(doc, brand=str(config["brand"]))
    if config.get("account"):
        doc = replace(doc, account=str(config["account"]))

    # 2. 成片交付 QA（实测）
    narration_end_s = config.get("narration_end_s")
    if narration_end_s is None and doc.timed:
        ends = [line.end_s for line in doc.lines if line.end_s is not None]
        narration_end_s = max(ends) if ends else None
    qa = run_delivery_qa(
        video_path,
        caption_box=config.get("caption_box"),
        caption_cues=config.get("caption_cues"),
        caption_source=str(config.get("caption_source") or "none"),
        narration_end_s=narration_end_s,
        silent_tail_s=float(config.get("silent_tail_s") or 0.0),
    )

    # 2b. 文稿 ↔ 成片音频一致性（F1）
    script_texts = [line.text for line in doc.lines if line.text]
    consistency = script_audio_consistency(
        video_path,
        script_texts=script_texts,
        narration_end_s=narration_end_s,
    )
    qa["script_audio_consistency"] = consistency

    # 3. 事实核查清单与来源台账
    claims = extract_claims(doc)
    ledger = build_source_ledger(doc, claims, checked_on=checked_on)

    # 4. 八平台文案
    copies: list[PlatformCopy] = build_platform_copies(doc, checked_on=checked_on)

    llm_text, llm_reason = _llm_refine(
        f"根据以下旁白稿，为抖音生成一条不超过30字的主推标题，只输出标题本身。\n{doc.full_text}",
        provider=config.get("llm_provider"),
    )
    llm_degraded = llm_text is None
    if llm_text and config.get("apply_llm_titles", True):
        refined = _clip_to_limit(llm_text, 30)
        if refined and _clip_to_limit(refined, 30) == refined:
            copies = [
                c if c.platform != "douyin" else PlatformCopy(
                    platform=c.platform, label=c.label, title=refined, alt_title=c.alt_title,
                    body=c.body, topics=c.topics, pinned_comment=c.pinned_comment,
                    chapters=c.chapters, summary=c.summary,
                )
                for c in copies
            ]

    copy_md = render_copy_md(doc, copies, checked_on=checked_on, version=config.get("copy_version", "v1"))

    # 5. 封面生成 + 封面 QA（F3：3:4 竖版封面从竖版成片取帧）
    portrait_video = config.get("portrait_video")
    portrait_path = Path(portrait_video) if portrait_video else None
    covers = build_covers(
        video_path, bundle_dir,
        topic=doc.topic, subtitle=config.get("cover_subtitle", ""),
        portrait_video=portrait_path,
    )
    cover_qa = run_cover_qa(covers, topic=doc.topic, video=video_path,
                             portrait_video=portrait_path)

    # 6. 合规自查
    findings = run_compliance(doc, copies)

    # 7. 落盘
    copy_json_path = bundle_dir / "copy.json"
    copy_json_path.write_text(
        json.dumps(
            {
                "topic": doc.topic,
                "script": doc.path,
                "script_kind": doc.source_kind,
                "checked_on": checked_on,
                "llm_degraded": llm_degraded,
                "llm_reason": llm_reason,
                "disclaimer": _disclaimer_for(doc, checked_on),
                "platforms": [c.as_dict() for c in copies],
                "platform_specs": [
                    {"id": p.id, "label": p.label, "title_limit": p.title_limit} for p in PLATFORMS
                ],
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    copy_md_path = bundle_dir / "copy.md"
    copy_md_path.write_text(copy_md, encoding="utf-8")

    qa_report = {
        **qa,
        "hedge_warnings": hedge_warnings(doc),
        "compliance_passed": all(f.passed for f in findings),
    }
    qa_report_path = bundle_dir / "qa_report.json"
    qa_report_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2), encoding="utf-8")

    fact_path = bundle_dir / "fact_sources.json"
    fact_path.write_text(json.dumps(ledger.payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cover_qa_path = bundle_dir / "cover_qa.json"
    cover_qa_path.write_text(json.dumps(cover_qa, ensure_ascii=False, indent=2), encoding="utf-8")

    compliance_path = bundle_dir / "compliance.json"
    compliance_path.write_text(
        json.dumps(
            {"checked_on": checked_on, "passed": all(f.passed for f in findings),
             "findings": [f.as_dict() for f in findings]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    gates = _gates(qa, cover_qa, findings, copies)
    return PublishBundleResult(
        output_dir=str(bundle_dir),
        cover_paths={k: str(v) for k, v in covers.items()},
        copy_json_path=str(copy_json_path),
        copy_md_path=str(copy_md_path),
        qa_report_path=str(qa_report_path),
        fact_sources_path=str(fact_path),
        cover_qa_path=str(cover_qa_path),
        compliance_path=str(compliance_path),
        gates=gates,
        llm_degraded=llm_degraded,
        llm_reason=llm_reason,
    )


def _disclaimer_for(doc, checked_on: str) -> str:
    return f"资料核对至{checked_on}。公开资料整理，未采访当事方；不构成消费/医疗/法律/求职建议。"


def _clip_to_limit(text: str, limit: int) -> str:
    text = text.strip().splitlines()[0].strip() if text.strip() else ""
    text = text.strip("「」\"'《》# ")
    return text[:limit]


def _gates(qa, cover_qa, findings, copies) -> tuple[PublishGate, ...]:
    # F1：文稿↔成片音频一致性不通过时，交付 QA 整体不放行（不静默通过）
    consistency = qa.get("script_audio_consistency") or {}
    consistency_passed = bool(consistency.get("passed"))
    delivery_ok = bool(qa["passed"]) and consistency_passed
    delivery_val = (qa["passed"], consistency_passed) if not delivery_ok else "ok"
    delivery_detail = (
        "成片机器验收全过 + 文稿/音频一致"
        if delivery_ok else
        f"验收={qa['passed']} 一致性={consistency.get('status','missing')}"
    )
    gates: list[PublishGate] = [
        PublishGate("delivery_qa", delivery_ok, delivery_val, delivery_detail),
        PublishGate("cover_ratios", cover_qa["passed"], cover_qa["passed"], "3:4 与 4:3 实测比例准确"),
        PublishGate("compliance", all(f.passed for f in findings), all(f.passed for f in findings), "三条红线无命中"),
        PublishGate(
            "platform_copy_complete",
            len(copies) == len(PLATFORMS),
            f"{len(copies)}/{len(PLATFORMS)}",
            "八平台成套文案",
        ),
        PublishGate(
            "titles_within_limit",
            all(len(c.title) <= p.title_limit and len(c.alt_title) <= p.title_limit
                for c, p in zip(copies, PLATFORMS, strict=True)),
            max(len(c.title) for c in copies),
            "各平台标题不超入口字数限制",
        ),
        PublishGate(
            "no_placeholder_copy",
            _copies_substantive(copies),
            True,
            "文案标题/正文不得为空、占位或源码；置顶评论按平台要求",
        ),
    ]
    return tuple(gates)


def _body_ok(text: str) -> bool:
    """正文不能是占位串或源码。"""

    if not text or len(text.strip()) < 8:
        return False
    bad = ("__TITLE__", "__WB_ROOT__", "TODO", "占位", "规则降级，未能生成文案", "//", "function ", "{ const ")
    return not any(b in text for b in bad)


def _copies_substantive(copies) -> bool:
    """标题/正文必须实质；置顶评论只在平台要求时才必须非空。"""

    required_pinned = {p.id for p in PLATFORMS if p.has_pinned_comment}
    for copy in copies:
        if not _body_ok(copy.title) or not _body_ok(copy.body):
            return False
        if copy.alt_title and not _body_ok(copy.alt_title):
            return False
        if copy.platform in required_pinned and not _body_ok(copy.pinned_comment):
            return False
    return True
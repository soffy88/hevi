"""Edit Craft Skill — 剪辑成片层（对标 video-use）。

流程: 策略确认 → 打包 transcript → (可选 filler 选切) → 校验/吸附 EDL
      → 渲染 → timeline 自检视图 → 成片自检
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hevi.assembly.cut_self_eval import assert_self_eval_passed, self_eval_edl
from hevi.assembly.edit_craft import (
    EditCraftError,
    EditDecisionList,
    EditRange,
    Word,
    edit_output_dir,
    require_strategy_confirmation,
    snap_range_to_words,
    validate_edl,
)
from hevi.assembly.filler_cut import plan_filler_cut, plan_to_edl
from hevi.assembly.takes_pack import pack_edit_dir, words_from_transcript_json
from hevi.assembly.timeline_view import cut_times_from_ranges, timeline_views_at_cuts

logger = logging.getLogger(__name__)


def _words_from_payload(raw: list[dict[str, Any]]) -> list[Word]:
    return [
        Word(
            word=str(w.get("word") or w.get("text") or ""),
            start=float(w["start"]),
            end=float(w["end"]),
        )
        for w in raw
        if "start" in w and "end" in w
    ]


class EditCraftSkill:
    """剪辑成片 Skill。"""

    async def execute(
        self,
        *,
        videos_dir: str,
        edl: dict[str, Any] | None = None,
        edl_path: str | None = None,
        strategy_confirmed: bool | None = None,
        words_by_source: dict[str, list[dict[str, Any]]] | None = None,
        preview: bool = False,
        skip_render: bool = False,
        require_subtitles: bool = False,
        auto_filler_cut: bool = False,
        source_id: str = "main",
        source_path: str | None = None,
        transcript_path: str | None = None,
        generate_timeline_views: bool = True,
    ) -> dict[str, Any]:
        """
        Args:
            videos_dir: 素材目录（输出进 videos_dir/edit/）
            edl / edl_path: 剪辑决策表
            strategy_confirmed: 覆盖 EDL 内确认位
            words_by_source: 可选词级时间戳，用于吸附 cut
            preview: 720p 预览
            skip_render: 只校验 + 打包，不渲染
            require_subtitles: 自检要求字幕
            auto_filler_cut: 从 transcript 自动生成去废话 EDL（仍需 strategy_confirmed）
            source_id / source_path / transcript_path: auto_filler_cut 时使用
            generate_timeline_views: 渲染后在 cut 边界生成 filmstrip
        """
        root = Path(videos_dir)
        edit_dir = edit_output_dir(root)

        stages: list[str] = []
        packed = None
        if (edit_dir / "transcripts").is_dir():
            packed = pack_edit_dir(edit_dir)
            stages.append("pack_transcripts")
            logger.info("takes_packed → %s", packed)

        filler_plan_dict = None
        if auto_filler_cut:
            if not source_path:
                raise EditCraftError("auto_filler_cut 需要 source_path")
            words: list[Word] = []
            if transcript_path:
                data = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
                words = words_from_transcript_json(data)
            elif words_by_source and source_id in words_by_source:
                words = _words_from_payload(words_by_source[source_id])
            else:
                # 尝试 edit/transcripts/{source_id}.json
                cand = edit_dir / "transcripts" / f"{source_id}.json"
                if cand.exists():
                    data = json.loads(cand.read_text(encoding="utf-8"))
                    words = words_from_transcript_json(data)
            if not words:
                raise EditCraftError("auto_filler_cut 需要词级 transcript")
            plan = plan_filler_cut(words)
            filler_plan_dict = plan.to_dict()
            (edit_dir / "filler_plan.json").write_text(
                json.dumps(filler_plan_dict, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            decision = plan_to_edl(
                plan,
                source_id=source_id,
                source_path=source_path,
                strategy_confirmed=bool(strategy_confirmed),
            )
            stages.append("filler_cut")
            edl = decision.to_dict()

        if edl is None and edl_path:
            edl = json.loads(Path(edl_path).read_text(encoding="utf-8"))
        if edl is None:
            raise EditCraftError("必须提供 edl / edl_path，或开启 auto_filler_cut")

        decision = EditDecisionList.from_dict(edl)
        if strategy_confirmed is not None:
            decision.strategy_confirmed = strategy_confirmed

        require_strategy_confirmation(decision)
        stages.append("strategy_gate")

        # 词边界吸附
        if words_by_source:
            new_ranges: list[EditRange] = []
            for r in decision.ranges:
                raw = words_by_source.get(r.source) or []
                words = _words_from_payload(raw)
                if words:
                    s, e = snap_range_to_words(r.start, r.end, words)
                    new_ranges.append(
                        EditRange(
                            source=r.source,
                            start=s,
                            end=e,
                            beat=r.beat,
                            quote=r.quote,
                            reason=r.reason or "snapped to word boundaries",
                        )
                    )
                else:
                    new_ranges.append(r)
            decision.ranges = new_ranges
            stages.append("word_snap")

        warnings = validate_edl(decision, require_confirm=True)
        stages.append("validate_edl")
        edl_out = edit_dir / "edl.json"
        edl_out.write_text(
            json.dumps(decision.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result: dict[str, Any] = {
            "status": "success",
            "edit_dir": str(edit_dir),
            "edl_path": str(edl_out),
            "takes_packed": str(packed) if packed else None,
            "filler_plan": filler_plan_dict,
            "warnings": warnings,
            "stages": stages,
        }

        final_path: Path | None = None
        if not skip_render:
            from hevi.assembly.edit_render import render_edl

            name = "preview.mp4" if preview else "final.mp4"
            final_path = await render_edl(
                decision,
                edit_dir=edit_dir,
                output_name=name,
                preview=preview,
                require_confirm=True,
            )
            result["final"] = str(final_path)
            result["stages"].append("render")

            if generate_timeline_views and len(decision.ranges) > 1:
                cuts = cut_times_from_ranges(decision.ranges)
                views = timeline_views_at_cuts(
                    final_path, cuts, edit_dir / "verify" / "timeline"
                )
                result["timeline_views"] = [str(v.path) for v in views]
                result["stages"].append("timeline_view")

        report = self_eval_edl(
            decision,
            final_path=final_path,
            require_confirm=True,
            require_subtitles=require_subtitles,
            extract_boundary_frames=bool(final_path),
            verify_dir=edit_dir / "verify" if final_path else None,
        )
        report_path = edit_dir / "self_eval.json"
        report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["self_eval"] = report.to_dict()
        result["self_eval_path"] = str(report_path)
        result["stages"].append("self_eval")

        assert_self_eval_passed(report)
        result["pipeline_passed"] = True
        return result


async def edit_craft_skill_execute(**kwargs: Any) -> dict[str, Any]:
    return await EditCraftSkill().execute(**kwargs)

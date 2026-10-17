"""剪辑成片层 · 对主链路的薄封装。

供 explainer / 脚本 / API 在「已有成片或单源 talking-head」后调用：
  transcript → filler 选切 →（确认后）render → self_eval → timeline_view
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
    Word,
    edit_output_dir,
)
from hevi.assembly.edit_render import render_edl
from hevi.assembly.filler_cut import plan_filler_cut, plan_to_edl
from hevi.assembly.takes_pack import (
    format_takes_packed,
    pack_phrases,
    words_from_transcript_json,
)
from hevi.assembly.timeline_view import cut_times_from_ranges, timeline_views_at_cuts

logger = logging.getLogger(__name__)


def _load_words(transcript: Path | dict[str, Any] | list[Word]) -> list[Word]:
    if isinstance(transcript, list):
        return list(transcript)
    if isinstance(transcript, dict):
        return words_from_transcript_json(transcript)
    data = json.loads(Path(transcript).read_text(encoding="utf-8"))
    return words_from_transcript_json(data)


async def talking_head_cleanup(
    *,
    source_video: Path,
    transcript: Path | dict[str, Any] | list[Word],
    work_dir: Path,
    strategy_confirmed: bool = False,
    preview: bool = True,
    source_id: str = "main",
    cut_fillers: bool = True,
    cut_silence: bool = True,
    strong_fillers_only: bool = True,
) -> dict[str, Any]:
    """对单源 talking-head 做去 filler / 压静音选切。

    默认 strategy_confirmed=False：只产出 plan + 建议 EDL，不渲染。
    用户确认后再次调用并 strategy_confirmed=True 才出片。
    """
    if not source_video.exists():
        raise EditCraftError(f"源视频不存在: {source_video}")

    edit_dir = edit_output_dir(work_dir)
    words = _load_words(transcript)
    if not words:
        raise EditCraftError("transcript 无词级时间戳，无法自动选切")

    # 缓存 transcript + takes_packed
    td = edit_dir / "transcripts"
    td.mkdir(exist_ok=True)
    tjson = td / f"{source_id}.json"
    if isinstance(transcript, Path) and transcript.exists():
        tjson.write_bytes(transcript.read_bytes())
    else:
        tjson.write_text(
            json.dumps(
                {
                    "words": [
                        {"word": w.word, "start": w.start, "end": w.end} for w in words
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    phrases = pack_phrases(words)
    (edit_dir / "takes_packed.md").write_text(
        format_takes_packed({source_id: phrases}),
        encoding="utf-8",
    )

    plan = plan_filler_cut(
        words,
        cut_fillers=cut_fillers,
        cut_silence=cut_silence,
        strong_fillers_only=strong_fillers_only,
    )
    (edit_dir / "filler_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    edl = plan_to_edl(
        plan,
        source_id=source_id,
        source_path=str(source_video.resolve()),
        strategy_confirmed=strategy_confirmed,
    )
    (edit_dir / "edl.json").write_text(
        json.dumps(edl.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result: dict[str, Any] = {
        "status": "planned" if not strategy_confirmed else "rendering",
        "edit_dir": str(edit_dir),
        "filler_plan": plan.to_dict(),
        "edl": edl.to_dict(),
        "takes_packed": str(edit_dir / "takes_packed.md"),
        "strategy_confirmed": strategy_confirmed,
    }

    if not strategy_confirmed:
        result["message"] = (
            "已生成 filler 选切方案，请审阅 edl.json / filler_plan.json 后 "
            "以 strategy_confirmed=True 再次调用以渲染"
        )
        return result

    final = await render_edl(
        edl,
        edit_dir=edit_dir,
        output_name="preview.mp4" if preview else "final.mp4",
        preview=preview,
        require_confirm=True,
    )
    result["final"] = str(final)

    if len(edl.ranges) > 1:
        cuts = cut_times_from_ranges(edl.ranges)
        views = timeline_views_at_cuts(final, cuts, edit_dir / "verify" / "timeline")
        result["timeline_views"] = [str(v.path) for v in views]

    report = self_eval_edl(
        edl,
        final_path=final,
        require_confirm=True,
        extract_boundary_frames=True,
        verify_dir=edit_dir / "verify",
    )
    (edit_dir / "self_eval.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["self_eval"] = report.to_dict()
    assert_self_eval_passed(report)
    result["status"] = "success"
    result["pipeline_passed"] = True
    return result

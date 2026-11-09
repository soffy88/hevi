"""ai_drama production pipeline as a checked canvas graph.

Stage order (each is one canvas node):

    script -> storyboard -> assets -> voice -> segments -> edit -> delivery

A node writes its document, runs its own checks, and only then lets the next
node run.  A failing node is retried by itself (``max_retries``); the rest of
the graph is not re-rendered.  The graph is also written as
``canvas_graph.json`` using hevi's existing CanvasNode node types, so the
same DAG can be opened by the canvas UI / incremental executor later.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import rules
from .assets import assign_shot_refs, build_assets, render_assets, save_assets
from .compile import compile_storyboard, draft_script_from_theme
from .credits import CreditLedger
from .edit import assemble, build_edit, export_fcpxml, export_jianying_plan, fit_storyboard_to_audio
from .game_pov import apply_game_pov_post
from .render import render_segments, render_shots
from .schema import normalize_script, normalize_storyboard
from .voice import attach_references, build_voice_plan

NODE_TYPES = {
    "script": "text",
    "storyboard": "script",
    "assets": "asset",
    "voice": "audio",
    "segments": "video",
    "edit": "segment",
    "delivery": "video",
}


def _write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def screenplay_markdown(script: dict[str, Any]) -> str:
    lines = [f"# {script.get('title', '未命名')}", ""]
    if script.get("logline"):
        lines += [f"> {script['logline']}", ""]
    for char in script.get("characters") or []:
        voice = char.get("voice") or {}
        lines.append(f"- **{char.get('name', char.get('id'))}**：{char.get('look', '')}；声音：{voice.get('description', '')}")
    lines.append("")
    for scene in script.get("scenes") or []:
        lines += [f"## {scene.get('header', '')}", ""]
        for beat in scene.get("beats") or []:
            for action in beat.get("action") or []:
                lines.append(str(action))
            for line in beat.get("dialogue") or []:
                kind = {"said": "", "inner": "（内心独白）", "vo": "（画外音）"}.get(str(line.get("kind")), "")
                lines.append(f"**{line.get('speaker')}**{kind}：{line.get('text')}")
            lines.append("")
    return "\n".join(lines)


def canvas_graph(episode_id: str, stages: list[str]) -> dict[str, Any]:
    nodes = []
    edges = []
    for i, stage in enumerate(stages):
        nid = f"{stage}_{i:02d}"
        nodes.append({
            "node_id": nid,
            "node_type": NODE_TYPES[stage],
            "label": stage,
            "config": {"stage": stage, "line": "ai_drama"},
            "position": {"x": i * 320, "y": 80},
        })
        if i:
            edges.append({"source": f"{stages[i - 1]}_{i - 1:02d}", "target": nid})
    return {"graph_id": episode_id, "line": "ai_drama", "nodes": nodes, "edges": edges}


class Pipeline:
    def __init__(
        self,
        out_dir: str | Path,
        *,
        episode_id: str = "ai_drama_sample",
        budget_cny: float | None = None,
        prefer_provider: str | None = None,
        seed: int = 42,
        max_retries: int = 1,
        render_images: bool = True,
        lipsync: bool | None = None,
        series: dict[str, Any] | None = None,
        gated: bool = False,
        edit_options: dict[str, Any] | None = None,
        cost_gate: bool = True,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.episode_id = episode_id
        self.cap = budget_cny
        self.prefer_provider = prefer_provider
        self.seed = seed
        self.max_retries = max_retries
        self.do_render_images = render_images
        self.lipsync = lipsync
        self.series = series
        self.gated = gated
        self.edit_options = dict(edit_options or {})
        self.cost_gate = cost_gate
        self.consistency: dict[str, Any] | None = None
        self.cost_plan: dict[str, Any] | None = None
        self.segment_gate: dict[str, Any] | None = None
        self.state: dict[str, Any] = {"episode_id": episode_id}
        self.report: dict[str, Any] = {"episode_id": episode_id, "nodes": {}, "line": "ai_drama"}

    # -- node runner -----------------------------------------------------
    def run_node(self, stage: str, fn: Callable[[], dict[str, Any]], check: Callable[[], list[dict[str, Any]]]) -> dict[str, Any]:
        attempts = []
        for attempt in range(self.max_retries + 1):
            payload = fn()
            self.state.update(payload)
            findings = check()
            result = rules.summarise(findings)
            attempts.append({"attempt": attempt + 1, "passed": result["passed"], "checks": result})
            if result["passed"]:
                self.report["nodes"][stage] = {"passed": True, "attempts": attempts}
                return payload
        self.report["nodes"][stage] = {"passed": False, "attempts": attempts}
        raise RuntimeError(f"ai_drama 节点 {stage} 自检失败: {attempts[-1]['checks']['findings'][:3]}")

    # -- stages ----------------------------------------------------------
    def stage_script(self) -> dict[str, Any]:
        data = self.state.get("input", {})
        if data.get("script"):
            script = normalize_script(data["script"])
        elif data.get("scenes") and data.get("characters"):
            script = normalize_script(data)
        else:
            script = normalize_script(draft_script_from_theme(str(data.get("theme") or "一个日常里的异常"),
                                                              style=str(data.get("style") or "live_action")))
        if self.series:
            from .series import inject_cast, series_findings

            script = inject_cast(script, self.series)
            self.state["series_findings"] = series_findings(script, self.series)
        _write(self.out_dir / "script.json", script)
        (self.out_dir / "screenplay.md").write_text(screenplay_markdown(script), encoding="utf-8")
        return {"script": script}

    def stage_storyboard(self) -> dict[str, Any]:
        provided = self.state.get("input", {}).get("storyboard")
        sb = normalize_storyboard(provided) if provided else normalize_storyboard(compile_storyboard(self.state["script"]))
        _write(self.out_dir / "storyboard.json", sb)
        return {"storyboard": sb}

    def stage_assets(self) -> dict[str, Any]:
        assets = build_assets(self.state["script"])
        if self.series:
            from .series import annotate_assets

            annotate_assets(assets, self.series)
        assign_shot_refs(self.state["storyboard"], assets)
        if self.do_render_images:
            render_assets(assets, self.out_dir / "assets", seed=self.seed)
        save_assets(assets, self.out_dir / "assets.json")
        if self.series:
            from .series import check_episode_consistency

            # Episode 1 establishes the series anchor from its own rendered
            # identity/portrait; later episodes are compared with that anchor.
            cards = {str(c.get("id")): c for c in self.series.get("cast") or []}
            for img in assets.get("images") or []:
                card = cards.get(str(img.get("character_id") or ""))
                if card is None or not img.get("path"):
                    continue
                if img.get("kind") == "character_identity" and not card.get("anchor_image"):
                    card["anchor_image"] = str(img["path"])
                if img.get("kind") == "character_portrait" and not card.get("portrait_image"):
                    card["portrait_image"] = str(img["path"])
            self.consistency = check_episode_consistency(
                assets, self.series, out_dir=self.out_dir,
                threshold=float((self.edit_options or {}).get("consistency_threshold", 0.72)),
            )
        return {"assets": assets, "asset_paths": {img["ref"]: img.get("path", "") for img in assets["images"]}}

    def stage_voice(self) -> dict[str, Any]:
        plan = build_voice_plan(self.state["script"], self.out_dir / "voice")
        plan = attach_references(plan, self.out_dir / "voice" / "references")
        _write(self.out_dir / "voice_plan.json", plan)
        fit_storyboard_to_audio(self.state["storyboard"], plan)
        _write(self.out_dir / "storyboard.json", self.state["storyboard"])
        return {"voice_plan": plan}

    def stage_segments(self) -> dict[str, Any]:
        ledger = CreditLedger(self.out_dir / "credit_ledger.jsonl", episode_id=self.episode_id, cap_cny=self.cap)
        if self.cost_gate:
            from .cost_gate import approve_plan, build_plan
            from .providers import select_provider

            provider, _ = select_provider(ledger, prefer=self.prefer_provider)
            self.cost_plan = approve_plan(
                build_plan(self.state["storyboard"], self.state["script"], provider=provider.name,
                           ledger=ledger),
                ledger=ledger,
            )
            _write(self.out_dir / "cost_plan.json", self.cost_plan)
            if not self.cost_plan["gate"]["allowed"]:
                raise RuntimeError(self.cost_plan["gate"]["reason"])
        if self.gated and self.series:
            from .segment_gate import render_segments_gated

            result = render_segments_gated(
                self.state["storyboard"], self.state["script"], self.state["assets"], self.state["asset_paths"],
                self.state["voice_plan"], self.out_dir, ledger=ledger,
                prefer_provider=self.prefer_provider, lipsync=self.lipsync, seed=self.seed,
                episode_id=self.episode_id, series=self.series,
                redo_attempts=int(self.edit_options.get("redo_attempts", 1)),
            )
            self.segment_gate = result["gate"]
            shots = result["shots"]
            segments = result["segments"]
        else:
            shots = render_shots(
                self.state["storyboard"], self.state["script"], self.state["assets"], self.state["asset_paths"],
                self.state["voice_plan"], self.out_dir, ledger=ledger, prefer_provider=self.prefer_provider,
                lipsync=self.lipsync, seed=self.seed, episode_id=self.episode_id,
            )
            segments = render_segments(self.state["storyboard"], shots["clips"], self.out_dir)
        _write(self.out_dir / "segments.json", {"shots": shots, "segments": segments,
                                                "ledger": ledger.report(),
                                                "cost_plan": self.cost_plan,
                                                "segment_gate": self.segment_gate})
        return {"segments": segments, "shots": shots, "ledger": ledger.report()}

    def stage_edit(self) -> dict[str, Any]:
        edit = build_edit(self.state["storyboard"], self.state["script"], self.state["voice_plan"],
                          self.out_dir, clip_paths=self.state["shots"]["clips"])
        if edit.get("ui_overlays"):
            for i, ui in enumerate(edit["ui_overlays"], start=1):
                if not ui.get("png"):
                    from .game_pov import make_ui_png
                    ui["png"] = str(make_ui_png(str(ui.get("text") or "继续"),
                                                self.out_dir / "ui" / f"ui_{i}.png"))
        target = self.edit_options.get("translate_to")
        if target:
            from .i18n import apply_bilingual, write_srt

            apply_bilingual(edit, str(target), llm=self.edit_options.get("llm"),
                            glossary=self.edit_options.get("glossary") or {})
            write_srt(edit, self.out_dir / f"subtitles_{target}.srt", lang="secondary")
        if self.edit_options.get("bgm"):
            edit["bgm"] = dict(self.edit_options["bgm"])
            edit["bgm_allowed"] = True
        _write(self.out_dir / "edit_list.json", edit)
        export_fcpxml(edit, self.out_dir / "timeline.fcpxml")
        export_jianying_plan(edit, self.out_dir / "jianying_plan.json")
        return {"edit": edit}

    def stage_delivery(self) -> dict[str, Any]:
        import copy

        edit = copy.deepcopy(self.state["edit"])
        if self.edit_options.get("trim"):
            from .edit import trim_silent_edges

            edit = trim_silent_edges(edit)
            _write(self.out_dir / "edit_list_trimmed.json", edit)
        result = assemble(edit, self.out_dir)
        result["trim"] = edit.get("trim")
        if self.state["script"].get("style") == "game_pov":
            game = apply_game_pov_post(Path(result["final"]), edit,
                                       self.out_dir / "final_game_pov.mp4", dialogue_box=True)
            result["game_pov"] = game
            result["deliverable"] = str(Path(result["final"]).with_name("final_game_pov.mp4"))
        else:
            result["deliverable"] = result["final"]
        result["canvas"] = str(self.out_dir / "canvas_graph.json")
        _write(self.out_dir / "delivery.json", result)
        return {"delivery": result}

    def _check_script(self) -> list[dict[str, Any]]:
        out = rules.check_script(self.state["script"])
        out.extend(self.state.get("series_findings") or [])
        return out

    def _check_storyboard(self) -> list[dict[str, Any]]:
        assets = self.state.get("assets")
        return rules.check_storyboard(self.state["storyboard"], self.state["script"], assets)

    def _check_assets(self) -> list[dict[str, Any]]:
        return rules.check_assets(self.state["assets"], self.state["script"], self.state["storyboard"]) + \
            rules.check_storyboard(self.state["storyboard"], self.state["script"], self.state["assets"])

    def _check_voice(self) -> list[dict[str, Any]]:
        out = []
        plan = self.state["voice_plan"]
        for cid, c in (plan.get("characters") or {}).items():
            if not c.get("description"):
                out.append(rules.finding("V-DESC", "major", f"角色 {cid} 缺声音描述", cid))
            if not c.get("reference"):
                out.append(rules.finding("V-REF", "major", f"角色 {cid} 还没有 3–8s 音频参考", cid))
        if not plan.get("lines"):
            out.append(rules.finding("V-LINES", "blocker", "没有合成任何台词"))
        return out

    def _check_segments(self) -> list[dict[str, Any]]:
        return rules.check_segments(self.state["storyboard"], self.state["assets"])

    def _check_edit(self) -> list[dict[str, Any]]:
        edit = self.state["edit"]
        return rules.check_edit(edit, self.state["script"], self.state["storyboard"]) + \
            rules.check_game_pov(self.state["script"], self.state["storyboard"], edit)

    def _check_delivery(self) -> list[dict[str, Any]]:
        out = []
        result = self.state["delivery"]
        deliverable = Path(result["deliverable"])
        if not deliverable.is_file() or deliverable.stat().st_size == 0:
            out.append(rules.finding("D-FILE", "blocker", "成片文件不存在"))
            return out
        import subprocess

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
             "-of", "json", str(deliverable)], capture_output=True, text=True,
        )
        try:
            info = json.loads(probe.stdout)
        except json.JSONDecodeError:
            out.append(rules.finding("D-PROBE", "blocker", "ffprobe 无法读取成片"))
            return out
        streams = info.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None:
            out.append(rules.finding("D-VIDEO", "blocker", "成片没有视频流"))
        elif (int(video.get("width", 0)), int(video.get("height", 0))) != (1080, 1920):
            out.append(rules.finding("D-ASPECT", "blocker", "成片不是 1080x1920 9:16"))
        if audio is None:
            out.append(rules.finding("D-AUDIO", "blocker", "成片没有音轨"))
        dur = float((info.get("format") or {}).get("duration") or 0)
        if dur < 10:
            out.append(rules.finding("D-DURATION", "blocker", "成片过短"))
        if result.get("loudness", {}).get("mode") not in ("two-pass", "single-pass"):
            out.append(rules.finding("D-LOUDNESS", "major", "响度归一未执行或没有记录"))
        return out

    def run(self, episode: dict[str, Any]) -> dict[str, Any]:
        self.state["input"] = episode
        stages = ["script", "storyboard", "assets", "voice", "segments", "edit", "delivery"]
        _write(self.out_dir / "canvas_graph.json", canvas_graph(self.episode_id, stages))
        checks = {
            "script": self._check_script,
            "storyboard": self._check_storyboard,
            "assets": self._check_assets,
            "voice": self._check_voice,
            "segments": self._check_segments,
            "edit": self._check_edit,
            "delivery": self._check_delivery,
        }
        fns = {
            "script": self.stage_script,
            "storyboard": self.stage_storyboard,
            "assets": self.stage_assets,
            "voice": self.stage_voice,
            "segments": self.stage_segments,
            "edit": self.stage_edit,
            "delivery": self.stage_delivery,
        }
        for stage in stages:
            self.run_node(stage, fns[stage], checks[stage])
        self.report["delivery"] = self.state["delivery"]
        self.report["cost_plan"] = self.cost_plan
        self.report["segment_gate"] = self.segment_gate
        self.report["consistency"] = self.consistency
        self.report["series_id"] = (self.series or {}).get("series_id")
        self.report["passed"] = True
        _write(self.out_dir / "pipeline_report.json", self.report)
        return self.report


def run_episode(episode: dict[str, Any], out_dir: str | Path, **kwargs: Any) -> dict[str, Any]:
    return Pipeline(out_dir, **kwargs).run(episode)

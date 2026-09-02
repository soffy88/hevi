"""Release coverage for the offline Lite production boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from hevi.pipeline_lite.omodul import omodul_script_loop as loop
from hevi.pipeline_lite.oprim import oprim_playwright as playwright
from hevi.pipeline_lite.oprim import oprim_tts as tts
from hevi.pipeline_lite.schemas import LiteCue, LiteRunRecord, ScriptDraft, ScriptVerdict


def _draft(topic: str = "机制") -> ScriptDraft:
    return ScriptDraft(
        topic=topic,
        title="标题",
        hook="反常识的第一句足够长，先抓住观众注意力。",
        cues=[
            LiteCue(index=0, narration="反常识的第一句足够长，先抓住观众注意力。"),
            LiteCue(index=1, narration="中段用一个生活例子把机制拆开讲清楚。"),
            LiteCue(index=2, narration="所以记住，机制比名词更值得复述。"),
        ],
        target_cues=3,
    )


@pytest.mark.asyncio
async def test_script_loop_json_adapters_and_review_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop, "_resolve_llm", lambda _llm=None: _llm)

    async def async_llm(**_kwargs: object) -> dict[str, str]:
        return {"content": '```json\n{"ok": 1}\n```'}

    assert await loop._call_llm_json(async_llm, "prompt") == {"ok": 1}

    def sync_llm(**_kwargs: object) -> dict[str, str]:
        return {"content": '{"ok": 2}'}

    assert await loop._call_llm_json(sync_llm, "prompt") == {"ok": 2}

    class CallableLLM:
        def __call__(self, **_kwargs: object) -> dict[str, str]:
            return {"content": '{"ok": 3}'}

    assert await loop._call_llm_json(CallableLLM(), "prompt") == {"ok": 3}

    class BrokenLLM:
        def __call__(self, **_kwargs: object) -> str:
            raise RuntimeError("offline")

    assert await loop._call_llm_json(BrokenLLM(), "prompt") == {}
    assert await loop._call_llm_json(lambda **_kwargs: {"content": "not json"}, "prompt") == {}
    assert loop._resolve_llm(CallableLLM()).__class__ is CallableLLM

    base = LiteCue(index=9, narration="一条足够长的旁白内容。")
    normalized = loop._normalize_cues(
        [base, {"text": "第二条旁白", "broll": "factory"}, None, {"narration": ""}],
        "主题",
    )
    assert [cue.index for cue in normalized] == [0, 1]
    assert normalized[1].props["visual_query"] == "factory"
    assert loop.draft_from_dict({}, "主题", 4).target_cues == 4
    assert (
        loop.draft_from_dict({"title": "T", "cues": [{"narration": "内容"}]}, "主题", 3).title
        == "T"
    )

    good = _draft()
    assert loop.deterministic_verdict(good).passed
    too_few = ScriptDraft(
        topic="x",
        cues=[LiteCue(index=0, narration="大家好")],
    )
    few_codes = {issue.code for issue in loop.deterministic_verdict(too_few).issues}
    assert {"too_few_cues", "weak_hook", "hook_too_short"} <= few_codes
    many = ScriptDraft(
        topic="x",
        cues=[
            LiteCue(index=i, narration=f"第{i}镜的旁白内容足够长，讲清一个具体机制。")
            for i in range(11)
        ],
    )
    assert any(issue.code == "too_many_cues" for issue in loop.deterministic_verdict(many).issues)
    noisy = ScriptDraft(
        topic="x",
        cues=[
            LiteCue(index=0, narration="这是一个足够长的重复内容。"),
            LiteCue(index=1, narration="这是一个足够长的重复内容。"),
            LiteCue(index=2, narration="这是" + "很长" * 70),
        ],
    )
    noisy_codes = {issue.code for issue in loop.deterministic_verdict(noisy).issues}
    assert {"duplicate_cue", "narration_too_long", "weak_close"} <= noisy_codes

    llm_pass = ScriptVerdict(passed=True, score=0.9, source="llm")
    merged = loop.merge_verdicts(loop.deterministic_verdict(good), llm_pass, round_idx=2)
    assert merged.passed and merged.source == "hybrid" and merged.round == 2
    llm_fail = ScriptVerdict(passed=False, score=0.2, source="llm")
    assert not loop.merge_verdicts(loop.deterministic_verdict(good), llm_fail, round_idx=0).passed

    class Critic:
        def __call__(self, **_kwargs: object) -> dict[str, str]:
            return {
                "content": json.dumps(
                    {
                        "score": "0.8",
                        "passed": True,
                        "summary": "ok",
                        "issues": [
                            {
                                "code": "soft",
                                "message": "note",
                                "severity": "unexpected",
                                "cue_index": "1",
                                "fix_hint": "fix",
                            }
                        ],
                    }
                )
            }

    verdict = await loop.llm_verdict(good, llm=Critic(), round_idx=1)
    assert verdict and verdict.source == "llm" and verdict.issues[0].severity == "soft"
    assert await loop.llm_verdict(good, llm=None) is None

    repaired = await loop.rewrite_draft(too_few, loop.deterministic_verdict(too_few), llm=None)
    assert len(repaired.cues) >= 3

    class Rewriter:
        def __call__(self, **_kwargs: object) -> dict[str, str]:
            return {
                "content": json.dumps(
                    {
                        "title": "重写",
                        "hook": "新的钩子",
                        "cues": [
                            {"narration": "第一镜重写后的旁白内容。"},
                            {"narration": "第二镜重写后的旁白内容。"},
                            {"narration": "所以第三镜完成收束。"},
                        ],
                    }
                )
            }

    rewritten = await loop.rewrite_draft(
        too_few, loop.deterministic_verdict(too_few), llm=Rewriter()
    )
    assert rewritten.title == "重写" and len(rewritten.cues) == 3
    assert await loop.draft_script("主题", target_cues=20, llm=None)
    with pytest.raises(ValueError, match="topic"):
        await loop.draft_script("  ", llm=None)
    assert loop.cues_from_script_text("主题", "一\n\n二")[-1].index == 1
    assert (await loop.run_veya_loop("主题", initial_draft=good, max_rounds=1)).passed
    failed = await loop.run_veya_loop("主题", initial_draft=too_few, max_rounds=1)
    assert failed.rounds == 1 and failed.decision_trail
    monkeypatch.setattr(loop, "_resolve_llm", lambda _llm=None: None)


@pytest.mark.asyncio
async def test_lite_tts_and_playwright_fail_closed_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cue = LiteCue(index=0, narration="旁白内容")

    async def cosyvoice(*, output_path: Path, **_kwargs: object) -> None:
        output_path.write_bytes(b"wav")

    one = await tts.synthesize_master_audio([cue], tmp_path / "one.wav", _cosyvoice=cosyvoice)
    assert one.read_bytes() == b"wav"

    async def unavailable(**_kwargs: object) -> None:
        raise tts.AiEngineError("offline")

    async def edge(**kwargs: object) -> None:
        Path(str(kwargs["output_path"])).write_bytes(b"edge-wav")

    fallback = await tts.synthesize_master_audio(
        [cue], tmp_path / "fallback.wav", _cosyvoice=unavailable, _edge_synthesize=edge
    )
    assert fallback.read_bytes() == b"edge-wav"

    async def empty_edge(**_kwargs: object) -> None:
        return None

    with pytest.raises(RuntimeError, match="未产出"):
        await tts.synthesize_master_audio(
            [cue], tmp_path / "empty.wav", _cosyvoice=unavailable, _edge_synthesize=empty_edge
        )
    with pytest.raises(RuntimeError, match="全部通道失败"):
        await tts.synthesize_master_audio(
            [cue],
            tmp_path / "failed.wav",
            _cosyvoice=unavailable,
            _edge_synthesize=AsyncMock(side_effect=RuntimeError("edge")),
        )

    cues = [cue, cue.model_copy(update={"index": 1, "narration": "第二句"})]
    monkeypatch.setattr(tts.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="拼接多段"):
        await tts.synthesize_master_audio(cues, tmp_path / "multi.wav", _cosyvoice=cosyvoice)

    class FakePage:
        def __init__(self, *, audio: bool = False) -> None:
            self.audio = audio
            self.wheels = 0
            self.waits: list[int] = []
            self.mouse = SimpleNamespace(wheel=self._wheel)

        async def _wheel(self, _x: int, _y: int) -> None:
            self.wheels += 1

        async def add_init_script(self, _script: str) -> None:
            return None

        async def goto(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def evaluate(self, expression: str) -> object:
            if "__heviAudioEnded" in expression and "hevi-master" in expression:
                return self.audio
            if "scrollHeight" in expression:
                return 2600
            if "animationDuration" in expression:
                return 1.2
            if "__heviAudioEnded === true" in expression:
                return self.audio
            return None

        async def wait_for_timeout(self, ms: int) -> None:
            self.waits.append(ms)

    page = FakePage()
    is_audio, effective = await playwright._prepare_page(
        page, tmp_path / "page.html", 0.1, freeze_until_fonts=True, probe_animation=True
    )
    assert not is_audio and effective == pytest.approx(0.4012)
    assert await playwright._load_page(page, tmp_path / "page.html") is False
    assert await playwright._drive_page(page, tmp_path / "page.html", 720, 1280, 0.2, True) > 0
    await playwright._drive_page(FakePage(), tmp_path / "page.html", 720, 1280, 0.2, False)
    await playwright._wait_audio_ended(FakePage(audio=True), 9999999999.0, 1.0)
    assert playwright._safety_seconds(1.0) == 45.0

    monkeypatch.setattr(playwright.shutil, "which", lambda _name: "ffprobe")
    monkeypatch.setattr(
        playwright.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="1.25"),
    )
    assert playwright._probe_duration(tmp_path / "x.mp4") == 1.25
    monkeypatch.setattr(
        playwright.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert playwright._probe_duration(tmp_path / "x.mp4") == 0.0

    frames = tmp_path / "frames"
    frames.mkdir()
    output = tmp_path / "frame.mp4"

    def fake_ffmpeg(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        Path(cmd[-1]).write_bytes(b"mp4")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(playwright.subprocess, "run", fake_ffmpeg)
    assert playwright._frames_to_mp4(frames, output, fps=24).read_bytes() == b"mp4"
    webm = tmp_path / "clip.webm"
    webm.write_bytes(b"webm")
    assert playwright.convert_webm_to_mp4(webm, fps=24).suffix == ".mp4"


@pytest.mark.asyncio
async def test_lite_router_state_machine_error_and_sync_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import BackgroundTasks, HTTPException

    from hevi.pipeline_lite.oapp import lite_router as router
    from hevi.pipeline_lite.schemas import LiteAssembleResult

    monkeypatch.setenv("HEVI_LITE_RUNS_DIR", str(tmp_path / "runs"))
    router._reset_runs_for_tests()
    assert router._draft_from_input("x") is None
    assert router._write_preview(LiteRunRecord(run_id="empty", topic="x")) is None
    router._persist(LiteRunRecord(run_id="empty", topic="x"))
    with pytest.raises(HTTPException, match="不存在"):
        router._get_run("missing")

    rec = LiteRunRecord(run_id="state", topic="主题", status="awaiting_confirm", draft=_draft())
    router._persist(rec)
    rec.status = "drafting"
    router._persist(rec)
    with pytest.raises(HTTPException, match="不可改稿"):
        await router.patch_script("state", router.LiteScriptPatch(script="x"))
    rec.status = "awaiting_confirm"
    edited = await router.patch_script(
        "state",
        router.LiteScriptPatch(
            cues=[LiteCue(index=4, narration="手工编辑后的一句旁白。")],
            title="新标题",
            hook="新钩子",
        ),
    )
    assert edited.draft and edited.draft.title == "新标题"
    with pytest.raises(HTTPException, match="尚无文案"):
        await router.reloop("empty")
    rereview = await router.reloop("state", max_rounds=0)
    assert rereview.status == "awaiting_confirm"

    rec.status = "drafting"
    router._persist(rec)
    with pytest.raises(HTTPException, match="不可确认"):
        await router.confirm_run("state", BackgroundTasks())
    rec.status = "awaiting_confirm"
    rec.draft = None
    router._persist(rec)
    with pytest.raises(HTTPException, match="文案为空"):
        await router.confirm_run("state", BackgroundTasks())

    async def fake_pipeline(ctx: Any, **_kwargs: object) -> LiteAssembleResult:
        task_id = ctx.task_id
        return LiteAssembleResult(
            task_id=task_id, status="failed", error="render failed", progress=7
        )

    monkeypatch.setattr(router, "run_lite_pipeline", fake_pipeline)
    body = router.LiteAssembleRequest(topic="主题", script="第一句")
    with pytest.raises(HTTPException, match="cues 不能为空"):
        await router.assemble_lite(router.LiteAssembleRequest(topic="主题"), BackgroundTasks())
    accepted = await router.assemble_lite(body, BackgroundTasks())
    assert accepted.status == "pending"
    generated = await router.generate_lite_sync(body)
    assert generated.status == "failed" and generated.error == "render failed"

    async def exploding_pipeline(*_args: object, **_kwargs: object) -> LiteAssembleResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(router, "_pipeline_from_cues", exploding_pipeline)
    exception_result = await router.generate_lite_sync(
        router.LiteAssembleRequest(topic="主题", cues=[LiteCue(index=0, narration="内容")])
    )
    assert exception_result.status == "failed" and "boom" in (exception_result.error or "")
    await router._run_background_assemble(
        "主题", [LiteCue(index=0, narration="内容")], "t", 720, 1280, 24, None
    )

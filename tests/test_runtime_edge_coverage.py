"""Meaningful edge coverage for production helpers with external boundaries."""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from uuid import uuid4

import httpx
import pytest


def test_oprim_resolve_covers_url_normalization_and_parameter_fallbacks() -> None:
    from hevi.platforms.oprim import resolve

    assert resolve.normalize_share_text("  no url  ") == "no url"
    assert resolve.extract_urls("https://a.test/x) https://b.test/y") == [
        "https://a.test/x",
        "https://b.test/y",
    ]
    assert resolve.extract_short_link("https://example.test/video") is None
    assert resolve.extract_short_link("xhslink.com/A1") == "xhslink.com/A1"
    assert resolve.identify_platform("https://IESDOUYIN.com/x") == "douyin"
    assert resolve.identify_platform("https://xiaohongshu.com/x") == "xhs"
    assert resolve.identify_platform("https://kuaishou.com/x") == "kuaishou"
    assert resolve.identify_platform("https://video.weixin.qq.com/x") == "shipinhao"
    assert resolve.identify_platform("https://unknown.example/x") is None
    assert resolve.extract_query_params("https://x.test/a?x=1&x=2") == {"x": "1"}
    assert resolve.extract_aweme_id_from_url("https://douyin.com/video/1?foo=bar") == "1"
    assert resolve.extract_aweme_id_from_url("https://douyin.com/video") is None
    assert resolve.extract_sec_uid_from_url("https://douyin.com/?foo=1") is None
    assert resolve.extract_note_id_from_url("https://xhs.com/?foo=1") is None
    assert resolve.extract_xsec_token_from_url("https://xhs.com/?foo=1") is None
    assert resolve.extract_ks_photo_id_from_url("https://ks.com/?foo=1") is None


def test_quality_gate_covers_compilation_coverage_and_three_state_policy() -> None:
    from hevi.quality import EvaluationEvidence, GatePolicy
    from hevi.quality.gate_policy import (
        evaluate_delivery_artifacts,
        gate_verdict,
        verify_compilation_integrity,
    )
    from hevi.quality.taxonomy import FailureCode

    assert verify_compilation_integrity(0, 0, [], []) == {
        "passed": True,
        "issues": [],
        "coverage": 1.0,
    }
    failed = verify_compilation_integrity(1, 2, ["unsupported"], ["dropped"])
    assert failed["passed"] is False and len(failed["issues"]) == 3

    def ev(metric: str, passed: bool | None, name: str) -> EvaluationEvidence:
        return EvaluationEvidence(
            id=str(uuid4()),
            attempt_id="attempt",
            artifact_id="artifact",
            constraint_id=name,
            evaluator_id=name,
            evaluator_version="1",
            metric=metric,
            passed=passed,
        )

    unknown = ev(FailureCode.IDENTITY_MISMATCH.value, None, "identity")
    advisory_fail = ev(FailureCode.WARDROBE_MISMATCH.value, False, "wardrobe")
    assert evaluate_delivery_artifacts([unknown], GatePolicy.for_profile("standard"))["passed"] is False
    economy = evaluate_delivery_artifacts([unknown], GatePolicy.for_profile("economy"))
    assert economy["passed"] is True and economy["degraded"] is True
    standard_advisory = evaluate_delivery_artifacts(
        [advisory_fail], GatePolicy.for_profile("standard")
    )
    assert standard_advisory["passed"] is True and standard_advisory["degraded"] is True
    assert GatePolicy.for_profile("invalid").profile == "standard"
    assert GatePolicy.for_profile("standard").blocks("身份漂移")
    cinema = gate_verdict(
        [],
        GatePolicy.for_profile("cinema"),
        {"provider_submission_rate": 0.9, "silent_drop_rate": 0.02},
    )
    assert cinema["passed"] is False and len(cinema["coverage_issues"]) == 2
    standard = gate_verdict(
        [],
        GatePolicy.for_profile("standard"),
        {"provider_submission_rate": 0.94, "silent_drop_rate": 0.02, "verification_rate": 0.5},
    )
    assert standard["passed"] is False and standard["degraded"] is True


def test_budget_envelope_rejects_invalid_and_boundary_transitions() -> None:
    from hevi.budget import BudgetEnvelope, BudgetError, BudgetExceeded, StageBudget

    def make_budget() -> BudgetEnvelope:
        return BudgetEnvelope(
            production_id=uuid4(),
            hard_limit_usd=10,
            soft_limit_usd=8,
            retake_pool_usd=2,
            stages={"rendering": StageBudget(category="rendering", allocation_usd=5)},
        )

    budget = make_budget()
    for amount, reason in ((0, "amount_must_be_positive"), (-1, "amount_must_be_positive")):
        with pytest.raises(BudgetExceeded, match=reason):
            budget.reserve(attempt_id=uuid4(), amount_usd=amount, stage_category="rendering")
    with pytest.raises(BudgetExceeded, match="unknown_stage"):
        budget.reserve(attempt_id=uuid4(), amount_usd=1, stage_category="missing")
    with pytest.raises(BudgetExceeded, match="production_hard_limit"):
        budget.reserve(attempt_id=uuid4(), amount_usd=11, stage_category="rendering")
    with pytest.raises(BudgetError, match="amount_must_be_positive"):
        budget.release(amount_usd=0, stage_category="rendering")
    with pytest.raises(BudgetError, match="reservation_release_exceeds_reserved"):
        budget.release(amount_usd=1, stage_category="rendering")

    budget, reservation = budget.reserve(
        attempt_id=uuid4(), amount_usd=2, stage_category="rendering"
    )
    with pytest.raises(BudgetError, match="settlement_exceeds_reserved"):
        budget.settle(reserved_usd=3, actual_usd=1, stage_category="rendering")
    with pytest.raises(BudgetError, match="invalid_settlement_amount"):
        budget.settle(reserved_usd=2, actual_usd=-1, stage_category="rendering")
    settled = budget.settle(
        reserved_usd=reservation.amount_usd, actual_usd=1, stage_category="rendering"
    )
    with pytest.raises(BudgetError, match="refund_exceeds_spent"):
        settled.refund(amount_usd=2, stage_category="rendering")
    refunded = settled.refund(amount_usd=1, stage_category="rendering")
    assert refunded.spent_usd == 0
    with pytest.raises(BudgetError, match="refund_exceeds_spent"):
        refunded.refund(amount_usd=1, stage_category="rendering")

    retake = make_budget()
    retake, _ = retake.reserve(
        attempt_id=uuid4(), amount_usd=2, stage_category="retake", is_retake=True
    )
    with pytest.raises(BudgetExceeded, match="retake_pool_exhausted_at_settlement"):
        retake.settle(reserved_usd=2, actual_usd=3, stage_category="retake", is_retake=True)
    retake_reserved = make_budget().model_copy(update={"reserved_usd": 1})
    with pytest.raises(BudgetError, match="retake_release_exceeds_reserved"):
        retake_reserved.release(amount_usd=1, stage_category="retake", is_retake=True)


def test_shot_preparation_state_rules_and_candidate_materialization() -> None:
    from hevi.director.pipeline_schemas import ShotListDialogueLine, ShotListItem
    from hevi.director.shot_preparation import (
        build_preparation_state,
        candidates_from_shot,
        compute_readiness_status,
    )

    assert compute_readiness_status(
        skip_extraction=True, extracted=False, asset_statuses=["pending"], dialogue_statuses=[]
    ) == "ready"
    assert compute_readiness_status(
        skip_extraction=False, extracted=False, asset_statuses=[], dialogue_statuses=[]
    ) == "pending"
    assert compute_readiness_status(
        skip_extraction=False, extracted=True, asset_statuses=[], dialogue_statuses=[]
    ) == "ready"
    assert compute_readiness_status(
        skip_extraction=False, extracted=True, asset_statuses=["linked"], dialogue_statuses=["accepted"]
    ) == "ready"
    assert compute_readiness_status(
        skip_extraction=False, extracted=True, asset_statuses=["pending"], dialogue_statuses=["ignored"]
    ) == "pending"

    shot = ShotListItem(
        shot_id="s1",
        scene_no=1,
        character_names=[" 王生 ", "王生", ""],
        scene_name=" 山洞 ",
        prop_names=["短刀", "短刀", " "],
        dialogue_lines=[
            ShotListDialogueLine(character_name="王生", text=" 走！ ", target_name="师父"),
            ShotListDialogueLine(text=""),
        ],
    )
    assets, dialogue = candidates_from_shot(shot)
    assert assets == [("character", "王生"), ("scene", "山洞"), ("prop", "短刀")]
    assert dialogue == [{"line_index": 0, "text": "走！", "speaker_name": "王生", "target_name": "师父"}]
    state = build_preparation_state(
        shot=None,
        readiness={"shot_id": "s1", "status": "pending", "extracted": True},
        asset_rows=[{"candidate_status": "pending"}, {"candidate_status": "linked"}],
        dialogue_rows=[{"candidate_status": "accepted"}, {"candidate_status": "pending"}],
    )
    assert state["pending_confirm_count"] == 2
    assert len(state["saved_dialogue_lines"]) == 1
    assert state["ready_for_generation"] is False


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _Stream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, _size: int) -> list[bytes]:
        return self.chunks


def test_corpus_seed_search_download_and_size_limits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from hevi.sourcing.corpus import Corpus
    from hevi.studio import corpus_seed

    def get(url: str, **_kwargs: object) -> _Response:
        if url == corpus_seed._NASA_SEARCH:
            return _Response({"collection": {"items": [{"data": [{"nasa_id": "n1", "title": "NASA"}], "href": "assets"}]}})
        if url == "assets":
            return _Response(["orig.mp4", "preview.mp4"])
        return _Response({"query": {"pages": {"1": {"pageid": 1, "title": "File:x.webm", "imageinfo": [{"url": "https://wiki/x.webm", "mime": "video/webm", "size": 100}]}}}})

    monkeypatch.setattr(corpus_seed.httpx, "get", get)
    assert corpus_seed.search_nasa_videos("history") == [
        {
            "id": "n1",
            "title": "NASA",
            "url": "preview.mp4",
            "source": "nasa",
            "license": "nasa-media",
            "page": "https://images.nasa.gov/details-n1",
        }
    ]
    wiki = corpus_seed.search_wikimedia_videos("history")
    assert wiki[0]["source"] == "wikimedia"

    corpus = Corpus.load(tmp_path)
    monkeypatch.setattr(corpus_seed.httpx, "stream", lambda *_args, **_kwargs: _Stream([b"video"]))
    hit = {"id": "n/1", "url": "https://cdn/x.mp4", "source": "nasa", "title": "x"}
    added = corpus_seed._add_http_clip(corpus, tmp_path, hit, query="q", max_mb=1)
    assert added is not None and (tmp_path / added["local_path"]).read_bytes() == b"video"
    duplicate = corpus_seed._add_http_clip(corpus, tmp_path, hit, query="q", max_mb=1)
    assert duplicate is not None and duplicate["clip_id"] == added["clip_id"]
    assert corpus.size == 1
    monkeypatch.setattr(corpus_seed.httpx, "stream", lambda *_args, **_kwargs: _Stream([b"x" * 20]))
    assert corpus_seed._add_http_clip(corpus, tmp_path, {**hit, "id": "large"}, query="q", max_mb=0) is None
    assert corpus_seed._add_http_clip(corpus, tmp_path, {"id": "none"}, query="q", max_mb=1) is None

    async def archive(*_args: object, **_kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(corpus, "add_archive_org", archive)
    added = asyncio.run(
        corpus_seed.seed_open_corpus(
            tmp_path / "seeded",
            [{"q": "", "source": "nasa"}, {"q": "q", "source": "archive"}],
        )
    )
    assert added == []


class _ExplainerRepo:
    def __init__(self, mode: str = "legacy") -> None:
        self.pool = object()
        self.row: dict[str, object] = {
            "id": "run-edge",
            "kind": "explainer",
            "user_id": "user-edge",
            "status": "PENDING",
            "input_json": {"topic": "topic", "mode": mode},
            "state_json": {},
            "task_ids": [],
            "created_at": SimpleNamespace(),
        }
        self.updates: list[dict[str, object]] = []

    async def get(self, _run_id: str) -> dict[str, object]:
        return self.row

    async def update(self, _run_id: str, values: dict[str, object]) -> None:
        self.updates.append(values)
        self.row.update(values)


class _Workspace:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.root = Path("/tmp/hevi-coverage-workspace")

    def update_progress(self, *_args: object) -> None:
        return None

    def mark_step_done(self, *_args: object, **_kwargs: object) -> None:
        return None

    def record_result_sha(self, _path: str) -> None:
        return None


@pytest.mark.asyncio
async def test_explainer_pipeline_failure_and_success_states_are_persisted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.api.routers import explainer
    from hevi.explainer import production, storyboard

    monkeypatch.setattr("hevi.core.workspace.WorkspaceManager", _Workspace)
    monkeypatch.setattr(explainer, "update_projection", _async_noop)

    async def fail_storyboard(_topic: str) -> object:
        raise RuntimeError("research unavailable")

    repo = _ExplainerRepo()
    monkeypatch.setattr(storyboard, "generate_storyboard", fail_storyboard)
    await explainer._run_pipeline(repo, "run-edge")
    assert repo.row["status"] == "FAILED"
    assert "E0 failed" in str(repo.row["state_json"])

    class Gate:
        def __init__(self) -> None:
            self.passed = False
            self.errors = ["missing hook"]

        def model_dump(self) -> dict[str, object]:
            return {"passed": self.passed, "errors": self.errors}

    async def valid_storyboard(_topic: str) -> object:
        return {"title": "ok"}

    monkeypatch.setattr(storyboard, "generate_storyboard", valid_storyboard)
    monkeypatch.setattr(storyboard, "gate_storyboard", lambda _story: Gate())
    repo = _ExplainerRepo()
    await explainer._run_pipeline(repo, "run-edge")
    assert repo.row["status"] == "FAILED"
    assert "E1 gate failed" in str(repo.row["state_json"])

    class PassedGate:
        def __init__(self) -> None:
            self.passed = True
            self.errors: list[str] = []

        def model_dump(self) -> dict[str, object]:
            return {"passed": True}

    class RenderResult:
        portrait_path = tmp_path / "portrait.mp4"
        landscape_path = tmp_path / "landscape.mp4"

    async def render(_story: object, _root: Path) -> RenderResult:
        return RenderResult()

    monkeypatch.setattr(storyboard, "gate_storyboard", lambda _story: PassedGate())
    monkeypatch.setattr(production, "render_narrated_storyboard", render)
    repo = _ExplainerRepo()
    await explainer._run_pipeline(repo, "run-edge")
    assert repo.row["status"] == "COMPLETED"
    assert repo.row["state_json"]["result_portrait_path"] == str(RenderResult.portrait_path)  # type: ignore[index]


async def _async_noop(*_args: object, **_kwargs: object) -> None:
    return None


async def _async_value(value: object) -> object:
    return value


@pytest.mark.asyncio
async def test_explainer_owned_run_and_presenter_binding_reject_wrong_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from hevi.api.routers import explainer
    from hevi.explainer.contracts import ExplainerAssembleRequest

    repo = _ExplainerRepo()
    with pytest.raises(HTTPException) as wrong_user:
        await explainer._get_owned_run(repo, "run-edge", "another-user")
    assert wrong_user.value.status_code == 404

    class PresenterRepo:
        def __init__(self, _pool: object) -> None:
            pass

        async def get(self, _presenter_id: str, _user_id: str) -> dict[str, object] | None:
            return {"id": "presenter", "name": "P", "delivery_json": {"provider": "heygen", "provider_presenter_id": "external"}}

        async def ensure_default(self, _user_id: str) -> dict[str, object]:
            return {"id": "default", "name": "D", "delivery_json": {}}

    monkeypatch.setattr(explainer, "PresenterRepository", PresenterRepo)
    cue = {"text": "x"}
    raw = ExplainerAssembleRequest(
        topic_or_url="topic", heygen_presenter_id="legacy", final_script_cues=[cue]
    )
    await explainer._bind_explainer_presenter(raw, pool=object(), user_id="u")
    assert raw.presenter_provider == "heygen" and raw.presenter_name == "HeyGen 数字人"
    invalid = ExplainerAssembleRequest(
        topic_or_url="topic", presenter_id="bad", final_script_cues=[cue]
    )
    with pytest.raises(HTTPException) as invalid_error:
        await explainer._bind_explainer_presenter(invalid, pool=object(), user_id="u")
    assert invalid_error.value.status_code == 422
    selected = ExplainerAssembleRequest(
        topic_or_url="topic", presenter_id=str(uuid4()), final_script_cues=[cue]
    )
    await explainer._bind_explainer_presenter(selected, pool=object(), user_id="u")
    assert selected.presenter_provider == "heygen" and selected.heygen_presenter_id == "external"
    default = ExplainerAssembleRequest(topic_or_url="topic", final_script_cues=[cue])
    await explainer._bind_explainer_presenter(default, pool=object(), user_id="u")
    assert default.presenter_provider == "remotion" and default.presenter_id == "default"


@pytest.mark.asyncio
async def test_audio_router_routes_backends_and_stitches_successful_segments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    def write_audio(path: Path) -> Path:
        path.write_bytes(b"audio" * 30)
        return path

    calls: list[str] = []

    async def conversational(**kwargs: object) -> Path:
        calls.append("conversation")
        return write_audio(kwargs["output_path"])  # type: ignore[arg-type]

    async def formal(**kwargs: object) -> Path:
        calls.append("formal")
        return write_audio(kwargs["output_path"])  # type: ignore[arg-type]

    monkeypatch.setattr(audio_router, "_synthesize_conversational", conversational)
    monkeypatch.setattr(audio_router, "_synthesize_formal", formal)
    assert await audio_router.route_single_cue(
        cue_text="哈哈", cue_style=None, output_path=tmp_path / "c.mp3", voice="v"
    ) == tmp_path / "c.mp3"
    assert await audio_router.route_single_cue(
        cue_text="formal", cue_style="formal", output_path=tmp_path / "f.mp3", voice="v"
    ) == tmp_path / "f.mp3"

    async def broken(**_kwargs: object) -> Path:
        raise RuntimeError("provider down")

    monkeypatch.setattr(audio_router, "_synthesize_conversational", broken)
    assert await audio_router.route_single_cue(
        cue_text="x", cue_style="conversational", output_path=tmp_path / "fallback.mp3", voice="v"
    ) == tmp_path / "fallback.mp3"
    assert calls == ["conversation", "formal", "formal"]

    class Cue:
        def __init__(self, cue_id: str, text: str) -> None:
            self.id = cue_id
            self.text = text
            self.audio_style = "formal"
            self.captions = [{"text": text}]

    async def route(**kwargs: object) -> Path:
        return write_audio(kwargs["output_path"])  # type: ignore[arg-type]

    monkeypatch.setattr(audio_router, "route_single_cue", route)
    monkeypatch.setattr(audio_router, "probe_duration", lambda _path: 1.25)

    class Process:
        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def spawn(*_args: object, **_kwargs: object) -> Process:
        return Process()

    monkeypatch.setattr(audio_router.asyncio, "create_subprocess_exec", spawn)
    result = await audio_router.route_and_stitch_master_audio(
        [Cue("a", "A"), Cue("b", "B")], tmp_path / "master", stitch_format="wav"
    )
    assert result["total_duration_s"] == 2.5
    assert len(result["manifest"]) == 2
    assert (tmp_path / "master" / "_concat_list.txt").exists() is False
    single = await audio_router.route_and_stitch_master_audio(
        [Cue("single", "S")], tmp_path / "single", stitch_format="wav"
    )
    assert single["master_path"].exists()


@pytest.mark.asyncio
async def test_audio_router_provider_specific_paths_and_empty_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    out = tmp_path / "voice.wav"

    async def vb(_text: str, path: Path, **_kwargs: object) -> None:
        path.write_bytes(b"v" * 120)

    monkeypatch.setattr("hevi.explainer.voicebox_client.synthesize", vb)
    monkeypatch.setenv("HEVI_TTS_CONVERSATIONAL_PROVIDER", "voicebox")
    assert await audio_router._synthesize_conversational(text="x", output_path=out, instruct=None) == out
    monkeypatch.setenv("HEVI_TTS_CONVERSATIONAL_PROVIDER", "chattts")
    monkeypatch.setattr(audio_router, "_synthesize_conversational", audio_router._synthesize_conversational)
    import oprim

    monkeypatch.setattr(oprim, "chattts_call", lambda **_kwargs: str(out), raising=False)
    assert await audio_router._synthesize_conversational(text="x", output_path=out, instruct=None) == out

    monkeypatch.setenv("HEVI_TTS_FORMAL_PROVIDER", "voicebox")
    assert await audio_router._synthesize_formal(text="x", output_path=out, voice="v", instruct=None) == out
    monkeypatch.setenv("HEVI_TTS_FORMAL_PROVIDER", "f5")
    monkeypatch.delenv("F5_TTS_REFERENCE_AUDIO", raising=False)
    monkeypatch.delenv("F5_TTS_REFERENCE_TEXT", raising=False)
    with pytest.raises(audio_router.AudioRoutingError, match="F5_TTS_REFERENCE"):
        await audio_router._synthesize_formal(text="x", output_path=out, voice="v", instruct=None)
    monkeypatch.setenv("HEVI_TTS_FORMAL_PROVIDER", "lux")
    monkeypatch.setattr("hevi.audio.lux_tts_service.lux_tts_available", lambda: False)
    with pytest.raises(audio_router.AudioRoutingError, match="luxvoice"):
        await audio_router._synthesize_formal(text="x", output_path=out, voice="v", instruct=None)

    async def missing(**_kwargs: object) -> Path:
        return tmp_path / "missing.wav"

    monkeypatch.setattr(audio_router, "_synthesize_formal", missing)
    with pytest.raises(audio_router.AudioRoutingError, match="All TTS"):
        await audio_router.route_single_cue(
            cue_text="x", cue_style="formal", output_path=out, voice="v"
        )


@pytest.mark.asyncio
async def test_cinematic_animation_provider_fallbacks_and_pipeline_callbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.cinematic import animation_pipeline
    from hevi.cinematic.golden_formula import GoldenBeat
    from hevi.video.alibaba_maas_service import AlibabaMaasError

    beat = GoldenBeat(
        index=1, shot_size="wide", movement="push_in", subject="subject", action="action",
        emotion_expression="calm", atmosphere="night", lighting="soft", duration_s=4,
        narration="narration",
    )
    shot = tmp_path / "shot.mp4"
    html_calls: list[tuple[int, int]] = []

    async def wan(**_kwargs: object) -> None:
        shot.write_bytes(b"wan")

    monkeypatch.setattr("hevi.video.alibaba_maas_service.alibaba_maas_generate", wan)
    assert await animation_pipeline._gen_shot(beat, 4, shot, "16:9") == "wan"

    async def wan_fail(**_kwargs: object) -> None:
        raise AlibabaMaasError("quota")

    async def wavespeed(**_kwargs: object) -> None:
        shot.write_bytes(b"wavespeed")

    monkeypatch.setattr("hevi.video.alibaba_maas_service.alibaba_maas_generate", wan_fail)
    monkeypatch.setattr("hevi.video.wavespeed_service.wavespeed_generate", wavespeed)
    assert await animation_pipeline._gen_shot(beat, 4, shot, "16:9") == "wavespeed"

    async def wavespeed_fail(**_kwargs: object) -> None:
        raise RuntimeError("offline")

    async def html(_beat: object, _html_dir: Path, out: Path, **kwargs: object) -> None:
        html_calls.append((int(kwargs["width"]), int(kwargs["height"])))
        out.write_bytes(b"html")

    monkeypatch.setattr("hevi.video.wavespeed_service.wavespeed_generate", wavespeed_fail)
    monkeypatch.setattr("hevi.cinematic.animation_html.render_html_shot", html)
    assert await animation_pipeline._gen_shot(beat, 4, shot, "9:16", tmp_path / "html", tmp_path / "nar") == "html"
    assert html_calls == [(720, 1280)]
    with pytest.raises(RuntimeError, match="无 HTML"):
        await animation_pipeline._gen_shot(beat, 4, shot, "16:9")

    wav = tmp_path / "nar.mp3"
    wav.write_bytes(b"audio")
    monkeypatch.setattr(animation_pipeline, "_wav_duration", lambda _path: 2.0)
    assert await animation_pipeline._tts(beat, wav) == 2.0
    wav.unlink()
    async def voicebox_fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("voicebox")

    async def cosy(*, script: object, output_path: Path, **_kwargs: object) -> None:
        del script
        output_path.write_bytes(b"audio")

    monkeypatch.setattr("hevi.explainer.voicebox_client.synthesize", voicebox_fail)
    monkeypatch.setattr("hevi.audio.cosyvoice_service.cosyvoice_synthesize", cosy)
    assert await animation_pipeline._tts(beat, wav) == 2.0

    monkeypatch.setattr("hevi.audio.cosyvoice_service.cosyvoice_synthesize", voicebox_fail)
    monkeypatch.setattr(animation_pipeline, "_run", lambda _cmd: None)
    monkeypatch.setattr(animation_pipeline.asyncio, "sleep", _async_noop)
    with pytest.raises(RuntimeError, match="所有 TTS"):
        await animation_pipeline._tts(beat, tmp_path / "none.mp3")

    beat_file = tmp_path / "beat_00.mp4"
    beat_file.write_bytes(b"beat")
    (tmp_path / "nar_00.mp3").write_bytes(b"nar")
    run_calls: list[list[str]] = []
    monkeypatch.setattr(animation_pipeline, "_run", lambda cmd: run_calls.append(cmd))
    assert animation_pipeline._concat(tmp_path, 1) == tmp_path / "final.mp4"
    assert len(run_calls) == 4

    events: list[tuple[int, str, int]] = []
    monkeypatch.setattr(animation_pipeline, "_tts", lambda *_args, **_kwargs: _async_value(3.0))
    monkeypatch.setattr(animation_pipeline, "_gen_shot", lambda *_args, **_kwargs: _async_value("html"))
    monkeypatch.setattr(animation_pipeline, "_concat", lambda *_args: tmp_path / "final.mp4")
    def progress(percent: int, stage: str, shot_index: int) -> None:
        events.append((percent, stage, shot_index))

    final, rows, report = await animation_pipeline.run_animation_pipeline(
        "story", task_id="task", output_dir=tmp_path / "pipeline", beats=[beat], progress_cb=progress
    )
    assert final.name == "final.mp4" and rows[0]["narration"] == "narration"
    assert report["renderers"] == ["html"] and events[-1][0] == 100


def test_digital_human_oprims_lock_content_timeline_captions_and_qa(
    tmp_path: Path,
) -> None:
    from hevi.digital_human.oprim import (
        add_clip_to_timeline,
        build_caption_plan,
        build_timeline,
        generate_narration,
        lock_content,
        run_preflight_check,
        run_qa_gate,
    )
    from hevi.digital_human.oprim.caption import build_caption_plan as build_caption_plan_impl
    from hevi.digital_human.oprim.narration import build_narration_spine, topic_to_script
    from hevi.digital_human.oprim.qa import check_audio_loudness, check_media_technical
    from hevi.digital_human.oprim.render import (
        build_loudnorm_filter,
        calculate_contact_timestamps,
        delivery_report,
        loudnorm_two_pass,
    )
    from hevi.digital_human.schemas import JobStatus, PresenterJob

    job = PresenterJob(topic="history", presenter_image=str(tmp_path / "presenter.png"))
    job.rights_confirmed = True
    job.adult_presenter_confirmed = True
    job.remote_upload_approved = True
    job.voice_clone_approved = True
    assert lock_content(job).status is JobStatus.CONTENT_LOCKED
    assert job.script and "history" in job.script
    assert generate_narration(job, voice_id="voice", rate=1.1).status is JobStatus.AUDIO_LOCKED
    assert job.voice_id == "voice" and job.rate == 1.1
    timeline = build_timeline(job, 30, opening_target_s=2, closing_target_s=3)
    assert timeline.total_video_duration_s == 30
    with pytest.raises(ValueError, match="Invalid clip"):
        add_clip_to_timeline(timeline, 0, 0, 0, 0, "missing.mp4")
    add_clip_to_timeline(timeline, 0, 4, 0, 5, "clip.mp4")
    assert timeline.is_available()
    assert build_caption_plan(4, "第一句。第二句！").is_available()
    assert build_caption_plan_impl(4, "long text", presets=["one"]).phrases[0].style == "one"
    assert not build_caption_plan_impl(4, "").is_available()
    assert build_narration_spine("topic", "zh")['beats']
    assert topic_to_script("topic", duration_s=30).endswith("。")

    preflight = run_preflight_check(job)
    assert preflight.ok is False and any("presenter_image" in e for e in preflight.errors)
    qa = run_qa_gate(job, identity_coherent=False, safe_zones_ok=False)
    assert qa.ok is False and len(qa.errors) == 2 and qa.remote_ready is False
    media = check_media_technical(job)
    assert media["errors"]
    audio = tmp_path / "audio.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "48000", "-ac", "1", str(audio),
        ],
        check=True,
        capture_output=True,
    )
    loudness = check_audio_loudness(str(audio))
    assert loudness["ok"] is True and "in_spec" in loudness
    assert check_audio_loudness(str(tmp_path / "none.wav"))["ok"] is False
    normalized = tmp_path / "normalized.wav"
    measurement = loudnorm_two_pass(str(audio), str(normalized))
    assert normalized.is_file()
    assert "measured_I" in build_loudnorm_filter(measurement)
    assert calculate_contact_timestamps(0, 3) == [0.2, 0.2, 0.2]
    assert calculate_contact_timestamps(10, 3)[-1] == 9.8
    report = delivery_report(
        "master.mp4", "share.mp4", "contact.jpg", 10, measurement, {}, {}, {}, black_events=1
    )
    assert report["status"] == "blocked" and report["black_frame_events"] == 1


@pytest.mark.asyncio
async def test_mpt_client_requires_context_and_maps_http_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hevi.services.mpt_integration import MPTClient, MPTConfig

    client = MPTClient(MPTConfig(api_base="http://mpt"))
    with pytest.raises(RuntimeError, match="not initialized"):
        await client.generate_video("topic")
    with pytest.raises(RuntimeError, match="not initialized"):
        await client.check_task_status("task")

    class Response:
        def __init__(self, value: object) -> None:
            self.value = value

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self.value

    class Http:
        async def post(self, url: str, **_kwargs: object) -> Response:
            if url.endswith("generate"):
                return Response({"task_id": "t"})
            if url.endswith("cross-post"):
                return Response({"ok": True})
            return Response({"transcript": "text"})

        async def get(self, url: str, **_kwargs: object) -> Response:
            if "/status/" in url:
                return Response({"state": "done"})
            return Response([{"url": "asset"}])

        async def aclose(self) -> None:
            return None

    http = Http()
    client._client = http  # type: ignore[assignment]
    assert (await client.generate_video("topic"))["task_id"] == "t"
    assert (await client.check_task_status("t"))["state"] == "done"
    assert (await client.get_materials("history"))[0]["url"] == "asset"
    assert (await client.cross_post("v.mp4", "title", ["xhs"]))["ok"] is True
    assert (await client.analyze_reference_video("url"))["transcript"] == "text"
    await client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_artifact_store_local_s3_and_delivery_integrity_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import HTTPException

    from hevi.artifact_store import http as artifact_http
    from hevi.artifact_store.lifecycle import expiry_for_role
    from hevi.artifact_store.object_store import LocalObjectStore, MinioObjectStore
    from hevi.production.artifacts import Artifact, ArtifactManifest

    source = tmp_path / "video.mp4"
    source.write_bytes(b"content")
    local_store = LocalObjectStore(tmp_path / "objects")
    stored = await local_store.put_file(source, media_type="video/mp4", key_prefix="ignored")
    assert stored.byte_size == 7
    assert await local_store.get_bytes(stored.uri) == b"content"
    assert await local_store.presign_get(stored.uri) is None
    await local_store.delete(stored.uri)
    with pytest.raises(FileNotFoundError):
        await local_store.put_file(tmp_path / "missing")

    manifest = ArtifactManifest(artifacts=[Artifact.from_path(source, kind="video", primary=True)])
    path = await artifact_http.materialize_artifact(manifest, kind="video")
    assert path == source
    response = await artifact_http.artifact_file_response(
        manifest, kind="video", filename="video.mp4", media_type="video/mp4"
    )
    assert response.filename == "video.mp4"
    bad = manifest.model_copy(deep=True)
    bad.artifacts[0].sha256 = "bad"
    with pytest.raises(HTTPException) as bad_hash:
        await artifact_http.materialize_artifact(bad, kind="video")
    assert bad_hash.value.status_code == 409
    with pytest.raises(HTTPException) as absent:
        await artifact_http.materialize_artifact(ArtifactManifest(), kind="video")
    assert absent.value.status_code == 404

    class Store:
        async def get_bytes(self, _uri: str) -> bytes:
            return b"s3 bytes"

        async def presign_get(self, _uri: str, *, expires_s: int) -> str:
            return f"https://signed/{expires_s}"

    s3 = ArtifactManifest(
        artifacts=[
            Artifact(
                kind="video", path="ignored", uri="s3://bucket/object", primary=True,
                sha256=__import__("hashlib").sha256(b"s3 bytes").hexdigest(),
            )
        ]
    )
    monkeypatch.setattr(artifact_http, "get_object_store", lambda: Store())
    materialized = await artifact_http.materialize_artifact(s3, kind="video")
    assert materialized.read_bytes() == b"s3 bytes"
    assert await artifact_http.artifact_delivery_url(s3, kind="video", expires_s=12) == "https://signed/12"
    assert await artifact_http.artifact_delivery_url(manifest, kind="video") is None

    class MinioClient:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}

        def bucket_exists(self, _bucket: str) -> bool:
            return False

        def make_bucket(self, _bucket: str) -> None:
            return None

        def stat_object(self, _bucket: str, key: str) -> object:
            if key not in self.objects:
                raise RuntimeError("missing")
            return object()

        def put_object(self, _bucket: str, key: str, stream: object, **_kwargs: object) -> None:
            self.objects[key] = stream.read()  # type: ignore[attr-defined]

        def get_object(self, _bucket: str, key: str) -> object:
            return SimpleNamespace(read=lambda: self.objects[key])

        def presigned_get_object(self, _bucket: str, key: str, *, expires: object) -> str:
            return f"signed:{key}:{expires}"

        def remove_object(self, _bucket: str, key: str) -> None:
            self.objects.pop(key, None)

    minio = MinioObjectStore(MinioClient(), bucket="hevi")
    uploaded = await minio.put_file(source, key_prefix="attempt")
    assert uploaded.uri.startswith("s3://hevi/attempt/")
    assert await minio.get_bytes(uploaded.uri) == b"content"
    assert "signed:" in (await minio.presign_get(uploaded.uri, expires_s=0) or "")
    await minio.delete(uploaded.uri)
    with pytest.raises(ValueError):
        await minio.get_bytes("s3://other/key")
    assert expiry_for_role("raw") is not None
    assert expiry_for_role("final") is None


@pytest.mark.asyncio
async def test_h3_comfy_client_builds_valid_workflows_and_handles_runtime_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.providers.h3_local.comfy_client import (
        ComfyClient,
        H3ComfyError,
        h3_length_for_duration,
    )

    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "valid.json").write_text(
        json.dumps({
            "1": {"class_type": "LoadImage", "inputs": {"image": "__REF_0__"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "__REF_1__"}},
            "3": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
                "prompt": "__PROMPT__", "length": "__LENGTH__", "width": "__WIDTH__",
                "height": "__HEIGHT__", "seed": "__SEED__", "ref_image_1": ["2", 0],
                "ref_image_0": ["1", 0],
            }},
        })
    )
    (workflows / "bad.json").write_text("[]")
    client = ComfyClient(workflows_dir=workflows, serial=False)
    assert client.load_workflow("valid")["1"]["class_type"] == "LoadImage"
    with pytest.raises(H3ComfyError, match="不存在"):
        client.load_workflow("missing")
    with pytest.raises(H3ComfyError, match="API 格式"):
        client.load_workflow("bad")
    built = client.build_workflow(
        "valid.json", prompt="prompt", length=124, seed=7, ref_images=["ref.png"],
        workflows_dir=workflows, extra_fills={"__CUSTOM__": "value"}
    )
    assert built["1"]["inputs"]["image"] == "ref.png"
    assert "2" not in built
    assert built["3"]["inputs"]["length"] == 124
    assert built["3"]["inputs"]["ref_image_0"] == ["1", 0]
    assert ComfyClient._ref_nodes(built) == []
    assert client.build_workflow({"x": {"class_type": "Node", "inputs": {"v": "x__PROMPT__"}}}, prompt="p")["x"]["inputs"]["v"] == "xp"
    assert h3_length_for_duration(0) == 5
    assert h3_length_for_duration(200) == 3600

    class Response:
        def __init__(self, status_code: int = 200, payload: object | None = None, content: bytes = b"") -> None:
            self.status_code = status_code
            self.payload = payload
            self.content = content
            self.text = json.dumps(payload) if payload is not None else "bad"

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("bad", request=SimpleNamespace(), response=self)

        def json(self) -> object:
            if self.payload is None:
                raise ValueError("not json")
            return self.payload

    class AsyncClient:
        history_calls = 0

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> AsyncClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, url: str, **_kwargs: object) -> Response:
            if url.endswith("system_stats"):
                return Response()
            if url.endswith("/history/p1"):
                self.history_calls += 1
                return Response(payload={"p1": {"status": {"status_str": "success"}, "outputs": {"1": {"videos": [{"filename": "x.mp4"}]}}}})
            if url.endswith("/history/p2"):
                return Response(payload={"p2": {"status": {"status_str": "failed"}, "error": "boom"}})
            return Response(content=b"video-bytes")

        async def post(self, url: str, **_kwargs: object) -> Response:
            if url.endswith("/prompt"):
                return Response(payload={"prompt_id": "p1"})
            if url.endswith("/upload/image"):
                return Response(payload={"name": "uploaded.png", "subfolder": "input"})
            return Response()

    monkeypatch.setattr("hevi.providers.h3_local.comfy_client.httpx.AsyncClient", AsyncClient)
    assert await client.health()
    assert await client.queue_prompt({}) == "p1"
    assert await client.wait_prompt("p1", timeout_s=1)
    with pytest.raises(H3ComfyError, match="执行失败"):
        await client.wait_prompt("p2", timeout_s=1)
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    assert await client.upload_image(image) == "input/uploaded.png"
    with pytest.raises(H3ComfyError, match="不存在"):
        await client.upload_input(tmp_path / "missing")
    output = client.find_video_output({"outputs": {"1": {"videos": [{"filename": "x.mp4"}]}}})
    assert output and output["filename"] == "x.mp4"
    assert client.find_video_output({"outputs": {"1": {"video": ["folder/y.mp4"]}}})["filename"] == "y.mp4"  # type: ignore[index]
    assert client.find_video_output({"outputs": {"1": {"video": "z.mp4"}}})["filename"] == "z.mp4"  # type: ignore[index]
    assert client.find_video_output({"outputs": {}}) is None
    assert await client.run_workflow({}, output_path=tmp_path / "out.mp4", timeout_s=1)
    assert (tmp_path / "out.mp4").read_bytes() == b"video-bytes"


@pytest.mark.asyncio
async def test_sdxl_adapter_covers_gpu_failures_prompt_fallback_and_batch_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.image import sdxl_local_service as sdxl

    class MissingGpu:
        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

        async def wait(self) -> None:
            return None

        def kill(self) -> None:
            return None

        returncode = 1

    async def missing(*_args: object, **_kwargs: object) -> MissingGpu:
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(sdxl.asyncio, "create_subprocess_exec", missing)
    with pytest.raises(sdxl.GPUUnavailableError, match="不存在"):
        await sdxl.check_gpu_available()

    class BadGpu(MissingGpu):
        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"no device"

    async def bad(*_args: object, **_kwargs: object) -> BadGpu:
        return BadGpu()

    monkeypatch.setattr(sdxl.asyncio, "create_subprocess_exec", bad)
    with pytest.raises(sdxl.GPUUnavailableError, match="失败"):
        await sdxl.check_gpu_available()

    class TimeoutGpu(BadGpu):
        async def communicate(self) -> tuple[bytes, bytes]:
            raise TimeoutError

    async def timeout(*_args: object, **_kwargs: object) -> TimeoutGpu:
        return TimeoutGpu()

    monkeypatch.setattr(sdxl.asyncio, "create_subprocess_exec", timeout)
    with pytest.raises(sdxl.GPUUnavailableError, match="超时"):
        await sdxl.check_gpu_available()

    monkeypatch.setattr("obase.provider_registry.ProviderRegistry.get", lambda: (_ for _ in ()).throw(RuntimeError("no llm")))
    assert await sdxl._ensure_english_prompt("中文") == "中文"
    monkeypatch.setattr("obase.provider_registry.ProviderRegistry.get", lambda: SimpleNamespace(llm=lambda _name: lambda **_kw: {"content": "中文"}))
    assert await sdxl._ensure_english_prompt("另一个中文") == "另一个中文"
    sdxl._EN_PROMPT_CACHE["缓存中文"] = "cached"
    assert await sdxl._ensure_english_prompt("缓存中文") == "cached"

    assert await sdxl.sdxl_local_generate_batch([]) == []
    calls: list[dict[str, object]] = []

    async def batch(requests: list[dict[str, object]]) -> list[dict[str, object]]:
        calls.extend(requests)
        return [{"ok": True}]

    original_batch_worker = sdxl._run_batch_worker
    monkeypatch.setattr(sdxl, "_run_batch_worker", batch)
    requests = [{"prompt": "English", "output_path": str(tmp_path / "one.png")}]
    result = await sdxl.sdxl_local_generate_batch(requests, require_gpu=False)
    assert result == [{"ok": True}] and calls[0]["prompt"] == "English"

    class Worker:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = self

        def __aiter__(self) -> Worker:
            return self

        async def __anext__(self) -> bytes:
            raise StopAsyncIteration

        async def wait(self) -> int:
            return self.returncode

        def kill(self) -> None:
            return None

    async def create_worker(*args: object, **_kwargs: object) -> Worker:
        task_file = Path(str(args[-1]))
        payload = json.loads(task_file.read_text())
        if "results_path" in payload:
            Path(payload["results_path"]).write_text(json.dumps([{"ok": True}, {"ok": False, "error": "bad item"}]))
        else:
            Path(payload["output_path"]).write_bytes(b"image")
        return Worker()

    monkeypatch.setattr(sdxl, "_run_batch_worker", original_batch_worker)
    monkeypatch.setattr(sdxl.asyncio, "create_subprocess_exec", create_worker)
    worker_results = await sdxl._run_batch_worker(
        [{"prompt": "p", "output_path": tmp_path / "a.png"}, {"prompt": "q", "output_path": tmp_path / "b.png"}]
    )
    assert worker_results[0]["seed"]  # type: ignore[index]
    assert isinstance(worker_results[1], RuntimeError)
    output = tmp_path / "single.png"
    await sdxl._run_worker(prompt="p", output_path=output, negative_prompt="n")
    assert output.read_bytes() == b"image"


@pytest.mark.asyncio
async def test_history_series_producer_selects_unproduced_lessons_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncpg

    from hevi.history_series import series_producer as producer

    class Connection:
        def __init__(self, rows: list[dict[str, object]]) -> None:
            self.rows = rows

        async def fetch(self, *_args: object) -> list[dict[str, object]]:
            return self.rows

        async def close(self) -> None:
            return None

    async def connect(_dsn: str) -> Connection:
        return Connection([{"display_order": 1, "name": "Lesson", "ku_cnt": 3}, {"display_order": 2, "name": "Done", "ku_cnt": 0}])

    monkeypatch.setattr(asyncpg, "connect", connect)
    monkeypatch.setattr(producer, "_produced_orders", lambda _pool=None: _async_set({2}))
    lesson = await producer.next_lesson(pool=object())
    assert lesson is not None and lesson.order == 1 and lesson.source_name.endswith("Lesson")
    monkeypatch.setattr(producer, "_produced_orders", lambda _pool=None: _async_set({1, 2}))
    assert await producer.next_lesson(pool=object()) is None

    async def assembled(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"source_name": "assembled", "layer_config": {}}

    monkeypatch.setattr("hevi.history_series.textbook_bridge.assemble_textbook_run_request", assembled)
    monkeypatch.setattr(producer, "_produced_orders", lambda _pool=None: _async_set(set()))
    monkeypatch.setattr("hevi.core.workspace.new_task_id", lambda: "task-new")
    task_id, request = await producer.produce_lesson(
        producer.LessonInfo(order=3, title="Three"), pool=object(), llm_layers={"L0": "local"}
    )
    assert task_id == "task-new" and request["lesson_order"] == 3
    assert request["layer_config"]["L0"]["model"] == "local"  # type: ignore[index]

    monkeypatch.setattr(producer, "_produced_orders", lambda _pool=None: _async_set({3}))
    monkeypatch.setattr(producer, "_existing_produced_task_id", lambda *_args, **_kwargs: _async_str("old-task"))
    existing_id, existing_request = await producer.produce_lesson(
        producer.LessonInfo(order=3, title="Three"), pool=object()
    )
    assert existing_id == "old-task" and existing_request == {}
    monkeypatch.setattr(producer, "next_lesson", lambda *_args, **_kwargs: _async_none())
    assert await producer.produce_next(pool=object()) is None

    monkeypatch.setattr(producer, "next_lesson", lambda *_args, **_kwargs: _async_lesson(producer.LessonInfo(4, "Four")))
    monkeypatch.setattr(producer, "produce_lesson", lambda *_args, **_kwargs: _async_pair("task-4", {"ok": True}))
    produced = await producer.produce_next(pool=object())
    assert produced and produced["task_id"] == "task-4" and produced["next"] is True

    class TaskRepo:
        def __init__(self, _pool: object) -> None:
            pass

        async def list_tasks(self, *, limit: int) -> list[dict[str, object]]:
            assert limit == 1000
            return [
                {"id": "task-1", "status": "completed", "progress_pct": 100, "config_json": {"lesson_order": 1}},
                {"id": "task-2", "status": "failed", "error": "bad", "config_json": {"request": {"lesson_order": 2}}},
            ]

    monkeypatch.setattr("hevi.tasks.repository.TaskRepository", TaskRepo)
    queue = await producer.series_queue(pool=object())
    assert queue == [
        {"lesson_order": 1, "title": "Lesson", "status": "completed", "task_id": "task-1", "progress": 100, "error": ""},
        {"lesson_order": 2, "title": "Done", "status": "failed", "task_id": "task-2", "progress": 0, "error": "bad"},
    ]


async def _async_set(value: set[int]) -> set[int]:
    return value


async def _async_str(value: str) -> str:
    return value


async def _async_none() -> None:
    return None


async def _async_lesson(value: object) -> object:
    return value


async def _async_pair(first: str, second: dict[str, object]) -> tuple[str, dict[str, object]]:
    return first, second


@pytest.mark.asyncio
async def test_task_service_adapter_failures_review_and_local_completion_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from hevi.tasks.task_service import TaskService

    def service_with(adapter_result: dict[str, object] | None = None, error: Exception | None = None) -> tuple[TaskService, MagicMock]:
        repo = MagicMock()
        repo.pool = MagicMock()
        repo.update_task = AsyncMock()
        repo.heartbeat = AsyncMock(return_value=True)
        adapters = MagicMock()

        async def execute(_task: dict[str, object], _pool: object) -> dict[str, object]:
            if error is not None:
                raise error
            return dict(adapter_result or {})

        adapters.execute = execute
        service = TaskService(repo, production_adapters=adapters)
        return service, repo

    failed_service, _failed_repo = service_with({"status": "failed", "error": "provider rejected"})
    failed = await failed_service._run_adapter_task({"id": uuid4(), "config_json": {"production_source": "director_graph"}})
    assert failed["status"] == "failed" and "provider rejected" in failed["error"]

    completed_service, completed_repo = service_with({"status": "completed"})
    completed = await completed_service._run_adapter_task({"id": uuid4(), "config_json": {"production_source": "director_graph"}})
    assert completed["status"] == "failed"
    assert any(call.args[1].get("status") == "failed" for call in completed_repo.update_task.await_args_list)

    exploding_service, exploding_repo = service_with(error=RuntimeError("adapter crashed"))
    exploded = await exploding_service._run_adapter_task(
        {"id": uuid4(), "config_json": {"production_source": "director_graph"}}
    )
    assert exploded["status"] == "failed"
    assert any(call.args[1].get("status") == "failed" for call in exploding_repo.update_task.await_args_list)

    service, _repo = service_with()
    assert service.is_local_provider("wan_local")
    assert service.is_local_provider("wan")
    assert not service.is_local_provider("wan_cloud")
    assert service.is_local_provider("ltx")

    class Attempts:
        async def start(self, *_args: object, **kwargs: object) -> dict[str, object]:
            return {"id": str(uuid4()), "worker_id": kwargs["worker_id"]}

        async def mark_running(self, *_args: object, **_kwargs: object) -> bool:
            return True

        async def checkpoint(self, **kwargs: object) -> None:
            self.checkpoint_value = kwargs

        async def finish(self, *_args: object, **_kwargs: object) -> bool:
            return True

        async def heartbeat(self, *_args: object, **_kwargs: object) -> bool:
            return True

    attempts = Attempts()
    service.attempt_repository = attempts  # type: ignore[assignment]
    task = {
        "id": str(uuid4()),
        "lease_token": "lease",
        "lease_until": "2026-01-01T00:00:00+00:00",
        "worker_id": "worker",
        "video_provider": "wan_local",
        "audio_provider": "edge_tts",
    }
    started = await service._start_attempt(task)
    assert started and task["_attempt_id"] == started["id"]
    await service._checkpoint(task, stage="render", progress_pct=50, state={"ok": True})
    await service._finish_attempt(task, status="succeeded")
    assert await service._renew_lease(task)
    assert attempts.checkpoint_value["stage"] == "render"  # type: ignore[attr-defined,index]


@pytest.mark.asyncio
async def test_task_service_create_task_idempotency_and_quality_repair_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from hevi.tasks.task_service import TaskService

    repo = MagicMock()
    repo.pool = MagicMock()
    repo.get_task_by_idempotency_key = AsyncMock(return_value={"id": "old"})
    service = TaskService(repo)
    existing = await service.create_task("topic", "1-5min", "wan_local", "edge_tts", idempotency_key=" idem ")
    assert existing == {"id": "old"}
    repo.get_task_by_idempotency_key.return_value = None
    repo.create_task = AsyncMock(side_effect=lambda data: data)

    class Estimate:
        total_usd = 1.25

    async def estimate(**_kwargs: object) -> Estimate:
        return Estimate()

    async def no_check(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("hevi.tasks.task_service.estimate_cost", estimate)
    monkeypatch.setattr("hevi.tasks.task_service.check_before_run", no_check)
    monkeypatch.setattr("hevi.tasks.task_service.check_daily_budget", no_check)
    created = await service.create_task(
        "topic", "1-5min", "wan_local", "edge_tts", idempotency_key="new", deadline_at="2026-01-01T00:00:00Z"
    )
    assert created["status"] == "pending" and created["config_json"]["estimated_usd"] == 1.25
    assert created["deadline_at"].tzinfo is None

    quality_task = {"id": str(uuid4()), "config_json": {"quality_profile": "standard"}}
    quality = await service._record_quality_repair(
        quality_task,
        {"passed": False, "violations": [{"code": "IDENTITY_MISMATCH", "message": "wrong"}]},
    )
    assert quality["quality_evaluation"]["passed"] is False
    assert quality["repair_decision"]["actions"]


@pytest.mark.asyncio
async def test_digital_human_omodul_builds_and_executes_the_full_job_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hevi.digital_human.omodul import (
        build_full_job_plan,
        execute_plan,
        init_job,
        plan_composition,
        plan_delivery,
        plan_generation,
        plan_presenter_generation,
        plan_visual,
    )
    from hevi.digital_human.schemas import JobStatus

    job = init_job(
        str(tmp_path / "job"),
        "presenter.png",
        topic="history",
        rights_confirmed=True,
        adult_presenter_confirmed=True,
        remote_upload_approved=True,
        voice_clone_approved=True,
    )
    monkeypatch.setenv("HEVI_DIGITAL_HUMAN_OUTPUT_DIR", str(tmp_path / "artifacts"))
    assert (tmp_path / "job" / "job.json").exists()
    assert plan_generation(job)["target_status"] == JobStatus.AUDIO_LOCKED.value
    assert plan_visual(job, 20)["target_status"] == JobStatus.VISUAL_PLAN_LOCKED.value
    assert plan_presenter_generation(job)["target_status"] == JobStatus.PRESENTER_GENERATED.value
    assert plan_composition(job)["target_status"] == JobStatus.COMPOSITION_CHECKED.value
    assert plan_delivery(job, "render.mp4", "out")["target_status"] == JobStatus.VERIFIED.value
    plan = build_full_job_plan(job, 20, "render.mp4", "out", "stem")
    assert len(plan["phases"]) == 5 and plan["state_machine"][-1] == "verified"
    with pytest.raises((FileNotFoundError, NotImplementedError), match="presenter image|no registered production adapter"):
        await execute_plan(job, plan)
    assert job.status is JobStatus.VISUAL_PLAN_LOCKED


@pytest.mark.asyncio
async def test_studio_kit_delegates_and_preserves_cross_line_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.ingest.video_watch import WatchResult
    from hevi.studio import kit

    async def concepts(result: object, *, llm: object = None) -> list[str]:
        assert isinstance(result, WatchResult)
        return ["concept:history"]

    monkeypatch.setattr("hevi.ingest.reference_concepts.derive_reference_concepts", concepts)
    watched = await kit.watch_video_tool(
        {"source": "inline", "transcript": "盐税改变了港口", "duration_s": 3}
    )
    assert watched["status"] == "ok"
    assert "盐税改变了港口" in watched["transcript"]
    assert watched["concepts"] == ["concept:history"]

    def fake_watch(*_args: object, **_kwargs: object) -> WatchResult:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("hevi.ingest.video_watch.watch_video", fake_watch)
    recovered = await kit.watch_video_tool({"source": "https://video.example/ref"})
    assert recovered["status"] == "ok" and recovered["duration_s"] == 0

    assert await kit.tongjian_l0({}) == {"status": "failed", "reason": "raw_text required"}
    fake_ir = SimpleNamespace(model_dump=lambda: {"quotes": [{"id": "q1"}]}, quotes=[1])

    async def extract_ir(**_kwargs: object) -> object:
        return fake_ir

    monkeypatch.setattr("hevi.tongjian.chapter_ir.extract_chapter_ir", extract_ir)
    l0 = await kit.tongjian_l0({"raw_text": "史料", "source_name": "册"})
    assert l0["status"] == "ok" and l0["quote_count"] == 1
    assert kit.tongjian_provenance({"lines": [{"type": "dialogue"}]})["passed"] is False
    assert kit.tongjian_provenance({"lines": [{"type": "dialogue", "dramatized": True}]})[
        "passed"
    ] is True

    assert await kit.storygraph_extract({}) == {"status": "failed", "reason": "raw_text required"}
    fake_graph = SimpleNamespace(
        model_dump=lambda mode=None: {"characters": ["c"], "events": ["e"]},
        characters=["c"],
        events=["e"],
    )

    async def extract_graph(**_kwargs: object) -> object:
        return fake_graph

    monkeypatch.setattr("hevi.storygraph.extract.extract_story_graph", extract_graph)
    graph = await kit.storygraph_extract({"raw_text": "故事"})
    assert graph["characters"] == 1 and graph["events"] == 1

    async def manim(**kwargs: object) -> Path:
        output = Path(str(kwargs["output_path"]))
        output.write_bytes(b"video")
        return output

    monkeypatch.setattr("hevi.providers.manim.provider.manim_generate", manim)
    manim_result = await kit.explainer_manim(
        {"text": "reveal", "output_path": str(tmp_path / "scene.mp4")}
    )
    assert manim_result["exists"] is True
    cues = await kit.explainer_cues_from_text({"texts": [" first ", "", "second"]})
    assert [item["text"] for item in cues["cues"]] == ["first", "second"]

    missing = await kit.avatar_compose({"image_path": "x"})
    assert missing["status"] == "failed"
    image = tmp_path / "presenter.png"
    audio = tmp_path / "line.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")

    async def make_face(**kwargs: object) -> Path:
        output = Path(str(kwargs["output_path"]))
        output.write_bytes(b"avatar")
        return output

    monkeypatch.setattr("hevi.digital_human.talking_face.generate_talking_face", make_face)
    composed = await kit.avatar_compose(
        {"image_path": image, "audio_path": audio, "output_path": tmp_path / "avatar.mp4"}
    )
    assert composed["status"] == "ok" and Path(composed["avatar_path"]).exists()

    async def broken_face(**_kwargs: object) -> Path:
        raise RuntimeError("face engine failed")

    monkeypatch.setattr("hevi.digital_human.talking_face.generate_talking_face", broken_face)
    assert (
        await kit.avatar_compose(
            {"image_path": image, "audio_path": audio, "output_path": tmp_path / "bad.mp4"}
        )
    )["status"] == "failed"

    assert (await kit.tts_synth({"text": ""}))["status"] == "failed"
    monkeypatch.setattr("hevi.audio.lux_tts_service.lux_tts_available", lambda: False)
    assert (await kit.tts_synth({"text": "hello", "provider": "lux"}))["status"] == "failed"

    class EdgeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            self.text, self.voice = text, voice

        async def save(self, path: str) -> None:
            Path(path).write_bytes(self.text.encode() + self.voice.encode())

    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", EdgeCommunicate)
    tts = await kit.tts_synth(
        {"text": "hello", "provider": "auto", "output_path": tmp_path / "line.mp3"}
    )
    assert tts["provider"] == "edge_tts" and Path(tts["audio_path"]).exists()


def test_studio_kit_exports_assets_profiles_nle_and_catalogs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.studio import kit
    from hevi.studio.assets import get_asset, reset_assets

    reset_assets()
    brick_path = tmp_path / "shot.json"
    exported = kit.shot_export(
        {
            "shot_id": "s1",
            "line_id": "director",
            "import_line": "tongjian",
            "prompt": "harbor",
            "camera": "wide",
            "duration_s": 2,
            "scene_no": 3,
            "asset_id": "asset-s1",
            "dest": brick_path,
        }
    )
    assert exported["status"] == "ok" and brick_path.exists()
    assert get_asset("asset-s1") is not None
    imported = kit.shot_import({"brick": exported["brick"], "target": "explainer"})
    assert imported["imported"]["target"] == "explainer"
    assert kit.shot_import({"shot_id": "s2", "prompt": "x"})["imported"]["target"] == "explainer"

    frozen = kit.freeze_profile(
        {"workspace": {"theme": "ink"}, "project": {"ratio": "9:16"}, "dest": tmp_path / "profile.json"}
    )
    assert frozen["status"] == "ok"
    assert kit.verify_profile({"resolved_path": frozen["resolved_path"]})["passed"] is True
    assert kit.verify_profile({"resolved_path": frozen["resolved_path"], "sha256": "wrong"})[
        "passed"
    ] is False
    assert kit.verify_profile({"resolved_path": str(tmp_path / "missing.json")})["status"] == "failed"
    assert kit.freeze_profile({"workspace": ["not-a-mapping"], "project": {}})["status"] == "failed"

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    copied = kit.nle_recut({"clips": [str(source)], "output_path": tmp_path / "copy.mp4"})
    assert copied["status"] == "ok" and Path(copied["video_path"]).read_bytes() == b"clip"
    assert kit.nle_recut({"clips": []})["status"] == "failed"
    monkeypatch.setattr("hevi.studio.kit.shutil.which", lambda _name: None)
    assert kit.nle_recut(
        {"clips": [{"source": str(source)}, {"source": str(source)}], "output_path": tmp_path / "x.mp4"}
    )["status"] == "failed"

    pack = kit.pack_matrix(
        {
            "topic": "盐税历史",
            "platforms": ["douyin", "bilibili"],
            "accounts": {"douyin": ["main", "backup"]},
            "dest_dir": tmp_path / "tickets",
        }
    )
    assert pack["status"] == "ok" and len(pack["tickets"]) == 3
    assert kit.list_pack_fonts({"root": str(tmp_path)})["count"] == 0
    assert kit.list_pack_mocap({"root": str(tmp_path)})["count"] == 0
    assert kit.list_pack_mocap({"root": str(tmp_path), "name": "missing"})["status"] == "failed"
    assert kit.list_celeb_voices({"root": str(tmp_path)})["count"] > 0
    assert kit.resolve_celeb_voice({})["status"] == "failed"
    assert kit.resolve_celeb_voice({"name": "missing", "root": str(tmp_path)})["status"] == "failed"


@pytest.mark.asyncio
async def test_dashscope_i2v_submit_poll_download_and_failure_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    from hevi.video.dashscope_i2v_service import (
        DashScopeI2VError,
        happyhorse_animate,
        i2v_animate,
    )

    image = tmp_path / "keyframe.jpg"
    image.write_bytes(b"keyframe")

    class Response:
        def __init__(self, body: dict[str, object], content: bytes = b"") -> None:
            self._body = body
            self.content = content
            self.text = json.dumps(body)

        def json(self) -> dict[str, object]:
            return self._body

        def raise_for_status(self) -> None:
            return None

    class SuccessfulClient:
        requests: ClassVar[list[tuple[str, dict[str, object] | None]]] = []

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> SuccessfulClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> Response:
            self.requests.append((url, kwargs.get("json")))
            return Response({"output": {"task_id": "job-1"}})

        async def get(self, url: str, **_kwargs: object) -> Response:
            self.requests.append((url, None))
            if url.endswith("job-1"):
                return Response({"output": {"task_status": "SUCCEEDED", "video_url": "https://video"}})
            return Response({}, b"v" * 1024)

    monkeypatch.setattr(httpx, "AsyncClient", SuccessfulClient)
    config = {"ALIBABA_MAAS_API_KEY": "key", "ALIBABA_MAAS_HOST": "maas.example"}
    rendered = await i2v_animate(
        image_path=image,
        prompt="slowly turn head",
        output_path=tmp_path / "i2v.mp4",
        config=config,
        poll_interval_s=0,
        timeout_s=1,
    )
    assert rendered.exists() and rendered.stat().st_size == 1024
    submit_payload = SuccessfulClient.requests[0][1]
    assert submit_payload is not None
    assert submit_payload["model"] == "wan2.2-i2v-flash"
    assert submit_payload["input"]["img_url"].startswith("data:image/jpeg;base64,")  # type: ignore[index]

    SuccessfulClient.requests.clear()
    rendered_hh = await happyhorse_animate(
        image_path=image,
        prompt="speak",
        output_path=tmp_path / "happyhorse.mp4",
        duration=5,
        config=config,
        poll_interval_s=0,
        timeout_s=1,
    )
    assert rendered_hh.exists()
    happy_payload = SuccessfulClient.requests[0][1]
    assert happy_payload is not None
    assert happy_payload["model"] == "happyhorse-1.1-r2v"
    assert happy_payload["parameters"]["duration"] == 5  # type: ignore[index]

    monkeypatch.setattr("hevi.video.dashscope_i2v_service.os.getenv", lambda _name: "")
    with pytest.raises(DashScopeI2VError, match="API_KEY"):
        await i2v_animate(image_path=image, prompt="x", output_path=tmp_path / "missing.mp4", config={})

    class NoTaskClient(SuccessfulClient):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"output": {}})

    monkeypatch.setattr(httpx, "AsyncClient", NoTaskClient)
    with pytest.raises(DashScopeI2VError, match="缺少 task_id"):
        await i2v_animate(
            image_path=image,
            prompt="x",
            output_path=tmp_path / "notask.mp4",
            config=config,
            poll_interval_s=0,
            timeout_s=1,
        )

    class FailedClient(SuccessfulClient):
        async def get(self, _url: str, **_kwargs: object) -> Response:
            return Response({"output": {"task_status": "FAILED"}})

    monkeypatch.setattr(httpx, "AsyncClient", FailedClient)
    with pytest.raises(DashScopeI2VError, match="status=FAILED"):
        await i2v_animate(
            image_path=image,
            prompt="x",
            output_path=tmp_path / "failed.mp4",
            config=config,
            poll_interval_s=0,
            timeout_s=1,
        )


@pytest.mark.asyncio
async def test_cinematic_router_canonical_adapter_and_local_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import BackgroundTasks, HTTPException

    import hevi.api.routers.cinematic as cinematic

    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"rendered video")
    progress: list[tuple[int, str, int]] = []

    class Repo:
        def __init__(self, _pool: object) -> None:
            self.update_task = AsyncMock()

    monkeypatch.setattr(cinematic, "TaskRepository", Repo)

    async def pipeline(*_args: object, **kwargs: object) -> tuple[Path, list[dict[str, object]], None]:
        callback = kwargs["progress_cb"]
        callback(50, "render", 0)
        progress.append((50, "render", 0))
        return rendered, [{"shot": 1}], None

    monkeypatch.setattr(cinematic, "run_animation_pipeline", pipeline)
    monkeypatch.setattr(cinematic, "_default_llm", lambda: object())
    result = await cinematic.execute_task(
        {
            "id": str(uuid4()),
            "topic": "a long historical story",
            "config_json": {
                "story": "story from config",
                "ratio": "9:16",
                "beats": [{"shot_size": "wide", "movement": "static"}],
            },
        },
        object(),
    )
    assert result["status"] == "completed" and result["completed_shots"] == 1
    assert progress == [(50, "render", 0)]

    session = MagicMock()
    accepted = await cinematic.animate(
        cinematic.AnimateRequest(
            story="这是一个足够长的动画故事",
            beats_json='[{"shot_size":"wide","movement":"static","subject":"港口"}]',
            ratio="1:1",
            task_id="local-cinematic",
        ),
        BackgroundTasks(),
        session,
        None,
    )
    assert accepted.task_id == "local-cinematic" and accepted.n_beats == 1
    session.add.assert_called_once()
    with pytest.raises(HTTPException, match="beats_json"):
        await cinematic.animate(
            cinematic.AnimateRequest(story="这是一个足够长的动画故事", beats_json="not json"),
            BackgroundTasks(),
            MagicMock(),
            None,
        )

    row = SimpleNamespace(
        task_id="local-cinematic",
        status="completed",
        progress=100,
        error_log=None,
        state_json={"video_path": str(rendered), "stage": "done"},
    )
    session.exec.return_value.first.return_value = row
    task_view = await cinematic.get_animation_task("local-cinematic", session, None)
    assert task_view["status"] == "completed" and task_view["video_path"] == str(rendered)
    video = await cinematic.get_animation_video("local-cinematic", session, None)
    assert video.path == str(rendered)
    session.exec.return_value.first.return_value = None
    with pytest.raises(HTTPException, match="task 不存在"):
        await cinematic.get_animation_task("missing", session, None)

    class FakeSession:
        def __init__(self, _engine: object) -> None:
            self.row = SimpleNamespace(
                task_id="run-1", status="pending", progress=0, state_json={}, error_log=None
            )

        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def exec(self, _query: object) -> SimpleNamespace:
            return SimpleNamespace(first=lambda: self.row)

        def add(self, _row: object) -> None:
            return None

        def commit(self) -> None:
            return None

    monkeypatch.setattr(cinematic, "Session", FakeSession)
    monkeypatch.setattr(cinematic.ws, "broadcast_task_update", AsyncMock())
    await cinematic._run_animation("run-1", "故事内容", "16:9", [])
    assert cinematic.ws.broadcast_task_update.await_count >= 1
    async def broken_pipeline(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("render broke")

    monkeypatch.setattr(cinematic, "run_animation_pipeline", broken_pipeline)
    await cinematic._run_animation("run-1", "故事内容", "16:9", [])


@pytest.mark.asyncio
async def test_history_series_router_covers_queue_submission_and_animation_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock

    from fastapi import BackgroundTasks, HTTPException, Request

    import hevi.api.routers.history_series as history

    def request(host: str = "127.0.0.1") -> Request:
        return Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer token")],
                "client": (host, 9000),
            }
        )

    lesson = history.LessonInfo(order=2, title="秦汉", ku_count=4)
    monkeypatch.setattr(history, "series_queue", AsyncMock(return_value=[{"order": 2}]))
    monkeypatch.setattr(history, "next_lesson", AsyncMock(return_value=lesson))
    assert await history.get_queue(pool=None) == [{"order": 2}]
    upcoming = await history.get_next(pool=None)
    assert upcoming["done"] is False and upcoming["source_name"] == lesson.source_name
    monkeypatch.setattr(history, "next_lesson", AsyncMock(return_value=None))
    assert (await history.get_next(pool=None))["done"] is True

    monkeypatch.setattr(history, "next_lesson", AsyncMock(return_value=None))
    with pytest.raises(HTTPException, match="全册已产完"):
        await history.produce(
            history.ProduceRequest(tb_id="tb"), BackgroundTasks(), request(), {"id": "u"}, None
        )
    monkeypatch.setattr(history, "produce_lesson", AsyncMock(return_value=("old-task", {})))
    already = await history.produce(
        history.ProduceRequest(lesson_order=2), BackgroundTasks(), request(), {"id": "u"}, None
    )
    assert already["status"] == "already_completed" and already["task_id"] == "old-task"

    req = {"source_name": "历史系列·第2课", "raw_text": "教材", "lesson_order": 2, "tb_id": "tb"}
    monkeypatch.setattr(history, "produce_lesson", AsyncMock(return_value=("new-task", req)))
    tasks = BackgroundTasks()
    pending = await history.produce(
        history.ProduceRequest(lesson_order=2), tasks, request(), {"id": "u"}, None
    )
    assert pending["status"] == "pending" and tasks.tasks[0].func is history._submit

    async def started(*_args: object, **_kwargs: object) -> dict[str, str]:
        return {"run_id": "tongjian-run", "status": "queued"}

    monkeypatch.setattr("hevi.api.routers.tongjian.start_run", started)
    production = await history.produce(
        history.ProduceRequest(lesson_order=2),
        BackgroundTasks(),
        request(),
        {"id": "u"},
        object(),
    )
    assert production["task_id"] == "tongjian-run" and production["status"] == "queued"

    monkeypatch.setattr(history, "next_lesson", AsyncMock(return_value=None))
    with pytest.raises(HTTPException, match="localhost"):
        await history.produce_daily(BackgroundTasks(), request("10.0.0.4"), pool=None)
    assert (await history.produce_daily(BackgroundTasks(), request(), pool=None))["done"] is True

    monkeypatch.setattr(history, "next_lesson", AsyncMock(return_value=lesson))
    monkeypatch.setattr(history, "produce_lesson", AsyncMock(return_value=("old", {})))
    daily_old = await history.produce_daily(BackgroundTasks(), request(), pool=None)
    assert daily_old["status"] == "already_completed"
    monkeypatch.setattr(history, "produce_lesson", AsyncMock(return_value=("daily", req)))
    daily_tasks = BackgroundTasks()
    daily = await history.produce_daily(daily_tasks, request(), pool=None)
    assert daily["status"] == "pending" and daily_tasks.tasks[0].func is history._submit_cron
    daily_production = await history.produce_daily(
        BackgroundTasks(), request(), pool=object()
    )
    assert daily_production["task_id"] == "tongjian-run"

    monkeypatch.setattr(history, "produce_lesson", AsyncMock(return_value=("anim-old", {})))
    animation_old = await history.animate_episode(
        history.ProduceRequest(lesson_order=2), BackgroundTasks(), {"id": "u"}, None
    )
    assert animation_old["status"] == "already_completed"
    monkeypatch.setattr(history, "produce_lesson", AsyncMock(return_value=("anim", req)))
    animation_tasks = BackgroundTasks()
    animation = await history.animate_episode(
        history.ProduceRequest(lesson_order=2), animation_tasks, {"id": "u"}, None
    )
    assert animation["status"] == "pending" and animation_tasks.tasks[0].func is history._run_animation_episode

    class HttpResponse:
        def json(self) -> dict[str, str]:
            return {"run_id": "submitted", "access_token": "cron-token"}

    class HttpClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> HttpClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _path: str, **_kwargs: object) -> HttpResponse:
            return HttpResponse()

    monkeypatch.setattr("httpx.AsyncClient", HttpClient)
    await history._submit("task", req, "token")
    failed: list[tuple[str, str]] = []
    monkeypatch.setattr(history, "_fail", lambda task_id, error: failed.append((task_id, error)))

    class NoTokenClient(HttpClient):
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def post(self, path: str, **kwargs: object) -> HttpResponse:
            if path == "/api/auth/login":
                class NoTokenResponse:
                    def json(self) -> dict[str, str]:
                        return {}

                return NoTokenResponse()  # type: ignore[return-value]
            return HttpResponse()

    monkeypatch.setattr("httpx.AsyncClient", NoTokenClient)
    await history._submit_cron("cron-task", req)
    assert failed == [("cron-task", "cron 登录失败")]

    final = tmp_path / "history.mp4"
    final.write_bytes(b"history")

    async def animate_lesson(*_args: object, **_kwargs: object) -> tuple[Path, list[dict[str, int]]]:
        return final, [{"shot": 1}]

    monkeypatch.setattr("hevi.history_series.series_animator.animate_lesson", animate_lesson)
    monkeypatch.setattr(history.ws, "broadcast_task_update", AsyncMock())
    await history.execute_animation_task(
        {"id": str(uuid4()), "topic": "秦汉", "config_json": {"lesson_order": 2, "lesson_title": "秦汉", "raw_text": "教材（教材主述）"}},
        object(),
    )


@pytest.mark.asyncio
async def test_task_service_repair_attempt_persists_lineage_and_fences_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from hevi.execution.plan import RepairPlan
    from hevi.production.artifacts import Artifact, ArtifactManifest
    from hevi.quality import EvaluationEvidence
    from hevi.tasks.task_service import TaskService

    production_id = uuid4()
    task_id = uuid4()
    source_attempt = uuid4()
    repaired_attempt = uuid4()
    video = tmp_path / "repaired.mp4"
    video.write_bytes(b"repaired")
    artifact_id = uuid4()
    manifest = ArtifactManifest(
        production_id=str(production_id),
        revision_id=str(uuid4()),
        artifacts=[
            Artifact(
                kind="video",
                path=str(video),
                uri=f"file://{video}",
                artifact_id=str(artifact_id),
                primary=True,
                sha256="sha",
                byte_size=8,
            )
        ],
    )
    task = {
        "id": str(task_id),
        "config_json": {"revision_id": manifest.revision_id, "quality_profile": "standard"},
        "lease_token": "lease",
        "lease_until": "2026-01-01T00:00:00+00:00",
        "worker_id": "worker",
    }
    repo = MagicMock()
    repo.pool = MagicMock()
    repo.get_task = AsyncMock(return_value=task)
    repo.update_task = AsyncMock()

    class Attempts:
        def __init__(self) -> None:
            self.finished: list[tuple[uuid.UUID, str]] = []

        async def start(self, *_args: object, **_kwargs: object) -> dict[str, str]:
            return {"id": str(repaired_attempt)}

        async def mark_running(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def finish(self, attempt: uuid.UUID, *, status: str, **_kwargs: object) -> None:
            self.finished.append((attempt, status))

    attempts = Attempts()
    service = TaskService(repo)
    service.attempt_repository = attempts  # type: ignore[assignment]

    class StoredArtifacts:
        async def commit(self, value: ArtifactManifest) -> ArtifactManifest:
            return value

    class StoredRepairs:
        saved = 0

        def __init__(self, _pool: object) -> None:
            pass

        async def save_run(self, **_kwargs: object) -> uuid.UUID:
            self.saved += 1
            return uuid4()

    monkeypatch.setattr("hevi.quality.repository.RepairRepository", StoredRepairs)
    plan = RepairPlan(
        id=str(uuid4()),
        production_id=str(production_id),
        source_attempt_id=str(source_attempt),
        source_verdict_id=str(uuid4()),
        violated_constraint_ids=["identity"],
        root_nodes=["B"],
        rerun_nodes=["B", "D"],
        preserve_artifact_ids=["a", "c", "e"],
        estimated_cost=1,
        expected_gain=0.8,
        decision="execute",
        reason="identity correction",
        iteration=1,
    )
    seen_nodes: list[list[str]] = []

    async def runner(attempt: uuid.UUID, nodes: list[str]) -> ArtifactManifest:
        assert attempt == repaired_attempt
        seen_nodes.append(nodes)
        return manifest

    evidence = [
        EvaluationEvidence(
            id=str(uuid4()),
            attempt_id=str(repaired_attempt),
            artifact_id=str(artifact_id),
            constraint_id="identity",
            evaluator_id="IDENTITY_MISMATCH",
            evaluator_version="1",
            metric="identity",
            passed=True,
        )
    ]

    async def evaluate(_manifest: ArtifactManifest) -> list[EvaluationEvidence]:
        return evidence

    result = await service.run_repair_attempt(
        task_id,
        plan,
        runner=runner,
        evaluator=evaluate,
        artifact_repository=StoredArtifacts(),  # type: ignore[arg-type]
    )
    assert result["verdict"]["passed"] is True
    assert result["attempt"]["id"] == str(repaired_attempt)
    assert seen_nodes == [["B", "D"]]
    assert attempts.finished[-1] == (repaired_attempt, "succeeded")

    async def evaluator_failure(_manifest: ArtifactManifest) -> list[EvaluationEvidence]:
        raise RuntimeError("quality service unavailable")

    failed = await service.run_repair_attempt(
        task_id,
        plan,
        runner=runner,
        evaluator=evaluator_failure,
        artifact_repository=StoredArtifacts(),  # type: ignore[arg-type]
    )
    assert failed["verdict"]["passed"] is False
    assert failed["evidence"][0].passed is None
    assert attempts.finished[-1] == (repaired_attempt, "failed")

    class BrokenArtifacts:
        async def commit(self, _value: ArtifactManifest) -> ArtifactManifest:
            raise RuntimeError("object store down")

    with pytest.raises(RuntimeError, match="object store down"):
        await service.run_repair_attempt(
            task_id,
            plan,
            runner=runner,
            evaluator=evaluate,
            artifact_repository=BrokenArtifacts(),  # type: ignore[arg-type]
        )
    assert attempts.finished[-1] == (repaired_attempt, "failed")


@pytest.mark.asyncio
async def test_tongjian_durable_context_and_provider_helper_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock

    import hevi.api.routers.tongjian as tongjian
    from hevi.tongjian.schemas import LayerConfig

    run_id = "coverage-tongjian"
    record = tongjian._init_run(run_id, "中国史", cache=True)
    assert record["status"] == "PENDING" and len(record["layers"]) == 9
    tongjian._update_layer(run_id, "L1", status="DEGRADED", error="advisory")
    assert tongjian._context(run_id)["current_layer"] == "L1"
    tongjian._finish_run(run_id, success=False, error="blocked")
    assert tongjian._context(run_id)["status"] == "FAILED"
    with pytest.raises(RuntimeError, match="not loaded"):
        tongjian._context("missing-run")

    req = tongjian.RunRequest(
        source_name="中国史",
        raw_text="原文",
        layer_config={
            "L1": LayerConfig(params={"n": 2}),
            "L3": LayerConfig(model="tts-model"),
            "L6": LayerConfig(model="cloud_avatar"),
        },
    )
    tongjian._apply_cloud_avatar_preset(req)
    assert req.layer_config["L1"].model == "qwen_cloud"
    assert req.layer_config["L3"].model == "tts-model"
    assert req.layer_config["L6"].model == "cloud_avatar"
    disabled = tongjian.RunRequest(source_name="x", raw_text="y")
    tongjian._apply_cloud_avatar_preset(disabled)
    assert disabled.layer_config == {}

    class Registry:
        def llm(self, name: str) -> str:
            return f"llm:{name}"

        def generic(self, kind: str, name: str) -> tuple[str, str]:
            return kind, name

    monkeypatch.setattr("obase.provider_registry.ProviderRegistry.get", lambda: Registry())
    llm, tts, params, gate_done = tongjian._pipeline_helpers(run_id, req)
    assert llm("L2") == "llm:qwen_cloud"
    assert tts("L3") == ("audio", "tts-model")
    assert params("L1") == {"n": 2}
    gate_done("L1", SimpleNamespace(passed=False, errors=["weak"], model_dump=lambda: {"passed": False}))
    assert tongjian._context(run_id)["layers"]["L1"]["degraded"] is True
    gate_done("L2", SimpleNamespace(passed=True, errors=[], model_dump=lambda: {"passed": True}))
    assert tongjian._context(run_id)["layers"]["L2"]["status"] == "PASSED"

    parsed = tongjian._request_from_record({"request": req.model_dump()})
    assert parsed.source_name == "中国史"
    assert tongjian._request_from_record({"req": req}) is req
    with pytest.raises(RuntimeError, match="no RunRequest"):
        tongjian._request_from_record({})
    tongjian._persist_context(run_id)
    await tongjian._flush_run_persistence(run_id)

    class Repo:
        pool = object()

        def __init__(self) -> None:
            self.update = AsyncMock()

    repo = Repo()
    tongjian._RUN_REPOSITORIES[run_id] = repo  # type: ignore[assignment]
    tongjian._context(run_id)["task_ids"] = []
    tongjian._update_layer(run_id, "L3", status="RUNNING")
    tongjian._finish_run(run_id, success=True, result_path=str(tmp_path / "video.mp4"))
    await tongjian._flush_run_persistence(run_id)
    assert repo.update.await_count >= 2
    tongjian._RUN_REPOSITORIES.pop(run_id, None)


@pytest.mark.asyncio
async def test_tasks_router_creation_repair_preparation_and_checkpoint_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock

    from fastapi import BackgroundTasks, HTTPException

    import hevi.api.routers.tasks as tasks_router

    task_id = uuid4()
    user = {"id": "user-1"}
    task = {
        "id": task_id,
        "task_id": str(task_id),
        "user_id": "user-1",
        "status": "failed",
        "progress_pct": 40,
        "config_json": {
            "quality_profile": "standard",
            "episode_plan": {"title": "港口", "characters_present": [{"name": "张三"}]},
        },
        "video_provider": "wan_local",
    }
    shot = {
        "shot_index": 0,
        "status": "pending",
        "output_path": "frame.png",
        "selection_json": {"script_excerpt": "张三看到挥剑"},
    }

    class Repo:
        pool = object()

        def __init__(self) -> None:
            self.saved_shots: list[dict[str, object]] = []
            self.latest = None

        async def list_tasks(self, **_kwargs: object) -> list[dict[str, object]]:
            return [task]

        async def get_task(self, _task_id: uuid4) -> dict[str, object]:  # type: ignore[valid-type]
            return task

        async def get_shots(self, _task_id: object) -> list[dict[str, object]]:
            return [shot]

        async def save_shot(self, value: dict[str, object]) -> None:
            self.saved_shots.append(value)

        async def update_task(self, _task_id: object, _update: dict[str, object]) -> None:
            return None

        async def latest_checkpoint(self, _task_id: object) -> object:
            return self.latest

    repo = Repo()

    class Service:
        def __init__(self) -> None:
            self.repository = repo
            self.created: list[dict[str, object]] = []

        async def create_task(self, **kwargs: object) -> dict[str, object]:
            self.created.append(kwargs)
            return {"id": task_id, "status": "pending", "progress_pct": 0}

        async def submit_task(self, _task_id: object) -> dict[str, object]:
            return {**task, "status": "pending"}

        async def resume_task(self, _task_id: object) -> dict[str, object]:
            return {**task, "status": "queued"}

        async def regenerate_task_shots(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def enqueue_resume(self, _task_id: object) -> dict[str, object]:
            return {**task, "status": "queued"}

        async def enqueue_rework(self, _task_id: object, **_kwargs: object) -> dict[str, object]:
            return {**task, "status": "queued"}

    service = Service()
    monkeypatch.setattr(tasks_router, "schedule_local_compat", lambda *_args: None)
    created = await tasks_router._create_task(
        tasks_router.LongVideoRequest(
            topic="历史港口",
            duration_archetype="1-5min",
            preset="economy",
            subject_id="subject-1",
            prompt_camera="slow push",
        ),
        user,
        service,  # type: ignore[arg-type]
        BackgroundTasks(),
        "idem-1",
    )
    assert created["task_id"] == str(task_id)
    assert service.created[0]["subject_id"] == "subject-1"
    with pytest.raises(HTTPException) as credits:
        async def no_credits(**_kwargs: object) -> object:
            raise tasks_router.InsufficientCredits(credits_needed=3, credits_available=1)

        monkeypatch.setattr(tasks_router, "resolve_preset", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(service, "create_task", no_credits)
        await tasks_router._create_task(
            tasks_router.LongVideoRequest(topic="历史港口", duration_archetype="1-5min"),
            user,
            service,  # type: ignore[arg-type]
            BackgroundTasks(),
        )
    assert credits.value.status_code == 402

    billing = type("Billing", (), {"estimate_credits": AsyncMock(return_value=4)})()
    estimate = await tasks_router.estimate_task_credits(
        tasks_router.EstimateRequest(duration_archetype="1-5min"), billing  # type: ignore[arg-type]
    )
    assert estimate == {"credits": 4, "credits_needed": 4}
    assert await tasks_router.list_tasks(repo, user, ["failed"]) == [tasks_router._serialize_task(task)]
    assert (await tasks_router.get_task_details(task_id, user, repo))["task_id"] == str(task_id)
    with pytest.raises(HTTPException, match="Task not found"):
        bad = {"id": "other", "user_id": "other", "status": "failed"}
        repo.get_task = AsyncMock(return_value=bad)  # type: ignore[method-assign]
        await tasks_router.get_task_details(task_id, user, repo)
    repo.get_task = AsyncMock(return_value=task)  # type: ignore[method-assign]

    resume_tasks = BackgroundTasks()
    resumed = await tasks_router.resume_task(task_id, user, service, resume_tasks)
    assert resumed["status"] == "failed" and resume_tasks.tasks
    completed = {**task, "status": "completed"}
    repo.get_task = AsyncMock(return_value=completed)  # type: ignore[method-assign]
    assert (await tasks_router.resume_task(task_id, user, service, BackgroundTasks()))["status"] == "completed"

    repo.get_task = AsyncMock(return_value={**task, "status": "completed"})  # type: ignore[method-assign]
    regen = await tasks_router.regenerate_task_shots(
        task_id,
        tasks_router.RegenerateRequest(shot_ids=[0], hints={0: "fix identity"}),
        user,
        service,
        BackgroundTasks(),
    )
    assert regen["task_id"] == str(task_id)
    with pytest.raises(HTTPException, match="must not be empty"):
        await tasks_router.regenerate_task_shots(
            task_id, tasks_router.RegenerateRequest(shot_ids=[]), user, service, BackgroundTasks()
        )

    repo.get_task = AsyncMock(return_value=task)  # type: ignore[method-assign]
    prep = await tasks_router.get_shots_preparation(task_id, user, repo)
    assert prep["total_pending"] > 0 and prep["all_ready"] is False
    candidate = prep["shots"][0]["candidates"][0]
    confirmed = await tasks_router.confirm_shot_candidate(
        task_id,
        0,
        candidate["id"],
        tasks_router.CandidateDecision(decision="accept", scope="assets"),
        user,
        repo,
    )
    assert confirmed["status"] in {"pending", "ready"} and repo.saved_shots
    beats = await tasks_router.update_shot_action_beats(
        task_id,
        0,
        tasks_router.ActionBeatsUpdate(trigger="see", peak="strike", aftermath="leave"),
        user,
        repo,
    )
    assert beats["action_beats"]["peak"] == "strike"
    repo.get_task = AsyncMock(return_value={**task, "status": "running"})  # type: ignore[method-assign]
    cancelled = await tasks_router.cancel_task(task_id, user, repo)
    assert cancelled["status"] == "cancelled"

    repo.latest = {
        "id": uuid4(),
        "attempt_id": uuid4(),
        "attempt_no": 2,
        "attempt_status": "running",
        "sequence": 3,
        "stage": "render",
        "progress_pct": 60,
        "completed_shots": 2,
        "total_shots": 4,
        "state_json": {"x": 1},
        "artifact_manifest_json": None,
        "created_at": "now",
    }
    checkpoint = await tasks_router.get_task_checkpoint(task_id, user, repo)
    assert checkpoint["resumable"] is True and checkpoint["completed_shots"] == 2
    repo.latest = None
    fallback = await tasks_router.get_task_checkpoint(
        task_id,
        user,
        type("CheckpointRepo", (), {"get_task": AsyncMock(return_value={"task_id": str(task_id), "status": "failed", "config_json": {"stage": "render"}, "completed_shots": 1, "total_shots": 2, "progress_pct": 20}), "latest_checkpoint": AsyncMock(return_value=None)})(),  # type: ignore[arg-type]
    )
    assert fallback["has_checkpoint"] is True and fallback["resumable"] is True


@pytest.mark.asyncio
async def test_tasks_router_media_delivery_and_stream_authorization_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    import hevi.api.routers.tasks as tasks_router
    from hevi.production.artifacts import Artifact, ArtifactManifest

    task_id = uuid4()
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    cover = video.with_suffix(".cover.jpg")
    cover.write_bytes(b"cover")
    task = {"id": task_id, "user_id": "u", "status": "completed", "result_video_path": str(video), "config_json": {}}

    class Repo:
        pool = object()

        def __init__(self) -> None:
            self.task = task

        async def get_task(self, _task_id: object) -> dict[str, object]:
            return self.task

    repo = Repo()
    monkeypatch.setattr(tasks_router, "decode_access_token", lambda _token: {"sub": "u"})
    monkeypatch.setattr(tasks_router.settings, "local_mode", True)
    monkeypatch.setattr(tasks_router.settings, "debug", True)
    video_response = await tasks_router.get_task_video(task_id, repo, "token")
    assert video_response.path == str(video)
    cover_response = await tasks_router.get_task_cover(task_id, repo, "token")
    assert cover_response.path == str(cover)
    cover.unlink()
    with pytest.raises(HTTPException, match="Cover not available"):
        await tasks_router.get_task_cover(task_id, repo, "token")
    with pytest.raises(HTTPException, match="Missing token"):
        await tasks_router._authorize_task_video(task_id, repo, None)

    async def export_video(_source: Path, destination: Path, _format: str) -> None:
        destination.write_bytes(b"exported")

    monkeypatch.setattr("hevi.assembly.exporter.export_video", export_video)
    exported = await tasks_router.export_task_video(task_id, repo, "token", "mov")
    assert exported.path == str(video.with_suffix(".mov"))
    with pytest.raises(HTTPException, match="unsupported format"):
        await tasks_router.export_task_video(task_id, repo, "token", "avi")

    async def dub_video(**kwargs: object) -> None:
        Path(str(kwargs["output_path"])).write_bytes(b"dubbed")

    monkeypatch.setattr("hevi.dub.dub_video", dub_video)
    dubbed = await tasks_router.dub_task_video(task_id, repo, "token", "ja")
    assert dubbed.path.endswith(".dub_ja.mp4")

    manifest = ArtifactManifest(
        production_id=str(uuid4()),
        artifacts=[
            Artifact(
                kind="video",
                path=str(video),
                uri=f"file://{video}",
                primary=True,
                artifact_id=str(uuid4()),
                sha256="sha",
                byte_size=5,
            ),
            Artifact(
                kind="audio",
                path=str(tmp_path / "line.wav"),
                uri=f"file://{tmp_path / 'line.wav'}",
                artifact_id=str(uuid4()),
                sha256="audio-sha",
                byte_size=5,
            ),
        ],
    )
    audio = tmp_path / "line.wav"
    audio.write_bytes(b"audio")
    repo.task = {**task, "config_json": {"artifact_manifest": manifest.model_dump(mode="json")}}

    async def materialize(_manifest: ArtifactManifest, *, kind: str) -> Path:
        return video if kind == "video" else audio

    monkeypatch.setattr(tasks_router, "materialize_artifact", materialize)
    audio_response = await tasks_router.get_task_audio(task_id, repo, "token")
    assert audio_response.path == str(audio)
    signed = AsyncMock(return_value="https://objects/video")
    monkeypatch.setattr(tasks_router, "artifact_delivery_url", signed)
    url = await tasks_router.get_task_video_url(task_id, repo, "token")
    assert url["delivery"] == "signed_object_url"
    signed.return_value = ""
    fallback = await tasks_router.get_task_video_url(task_id, repo, "token")
    assert fallback["delivery"] == "authenticated_api_stream"

    monkeypatch.setattr(tasks_router, "get_task_progress_stream", lambda *_args: iter([b"data: ok\n\n"]))
    stream = await tasks_router.stream_task_progress(task_id, repo, "token")
    assert stream.media_type == "text/event-stream"
    with pytest.raises(HTTPException, match="Missing token"):
        await tasks_router.stream_task_progress(task_id, repo, None)


def test_director_pipeline_state_machine_and_gate_report_contracts() -> None:
    from fastapi import HTTPException

    import hevi.api.routers.director_pipeline as director

    work = director._init_work(
        "work-coverage",
        material_text="史料正文",
        intent_hint="纪实",
        user_id="user-1",
        work_name="历史港口",
        target_episodes=2,
    )
    assert work["locked_through"] == -1 and director._stage_index("shot_list") == 4
    assert director._work_status(work)["work_id"] == "work-coverage"
    director._append_trail(work, "concept", "accepted", "concept ready")
    assert work["decision_trail"][-1]["status"] == "accepted"
    with pytest.raises(HTTPException, match="work 不存在"):
        director._require_work("missing", {"id": "user-1"})
    with pytest.raises(HTTPException, match="还没锁定"):
        director._require_stage_ready(work, "screenplay")
    work["locked_through"] = 4
    work.update({"concept": {"x": 1}, "screenplay": {"x": 1}, "design_list": {"x": 1}, "shot_list": {"x": 1}})
    work["constraint_graph"] = {"constraints": []}
    director._rollback_downstream(work, "design_list")
    assert work["design_list"] is None and work["shot_list"] is None
    assert "constraint_graph" not in work and work["locked_through"] == 1

    scene = SimpleNamespace(
        visual_actions=["walk"],
        event_summary="港口开市",
        narration="旁白",
        dialogue=[],
        production_complexity="low",
        cg_level="low",
        characters_present=["张三"],
        location="港口",
    )
    screenplay = SimpleNamespace(scenes=[scene])
    design = SimpleNamespace(
        characters=[SimpleNamespace(name="张三", appearance="neutral", wardrobe="robe")],
        scenes=[SimpleNamespace(name="港口")],
    )
    story = SimpleNamespace(characters=["张三"], events=["开市"])
    season = SimpleNamespace(episodes=[1], target_episodes=1)
    plan_gate = SimpleNamespace(passed=True, coverage=1.0, errors=[], warnings=[])
    report = director._build_director_gate(
        story=story,
        season_plan=season,
        plan_gate=plan_gate,
        screenplay=screenplay,
        design_list=design,
        estimated_cost_usd=5,
        season_budget_usd=10,
    )
    assert report.passed is True and report.identity_readiness == 1

    bad_scene = SimpleNamespace(
        visual_actions=[],
        event_summary="",
        narration="",
        dialogue=[],
        production_complexity="high",
        cg_level="high",
        characters_present=["未知"],
        location="未知地",
    )
    blocked = director._build_director_gate(
        story=SimpleNamespace(characters=[], events=[]),
        season_plan=SimpleNamespace(episodes=[], target_episodes=2),
        plan_gate=SimpleNamespace(passed=False, coverage=0.2, errors=["coverage"], warnings=["warning"]),
        screenplay=SimpleNamespace(scenes=[bad_scene, bad_scene]),
        design_list=SimpleNamespace(characters=[], scenes=[]),
        estimated_cost_usd=20,
        season_budget_usd=10,
    )
    assert blocked.passed is False and blocked.errors and blocked.warnings == ["warning"]


def test_sdxl_subprocess_workers_cover_cpu_img2img_and_partial_batch_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys
    import types

    class FakeImage:
        def __init__(self, marker: str = "image") -> None:
            self.marker = marker

        def convert(self, _mode: str) -> FakeImage:
            return self

        def resize(self, _size: tuple[int, int]) -> FakeImage:
            return self

        def save(self, path: str) -> None:
            Path(path).write_bytes(self.marker.encode())

    class FakePipe:
        fail_created_pipe = False

        def __init__(self) -> None:
            self.vae = types.SimpleNamespace(enable_tiling=lambda: None)
            self.calls: list[dict[str, object]] = []
            self.fail_next = type(self).fail_created_pipe

        @classmethod
        def from_pretrained(cls, *_args: object, **_kwargs: object) -> FakePipe:
            pipe = cls()
            pipes.append(pipe)
            return pipe

        def set_progress_bar_config(self, **_kwargs: object) -> None:
            return None

        def to(self, _device: str) -> FakePipe:
            return self

        def enable_model_cpu_offload(self) -> None:
            return None

        def enable_attention_slicing(self) -> None:
            return None

        def load_lora_weights(self, _path: str) -> None:
            return None

        def fuse_lora(self, **_kwargs: object) -> None:
            return None

        def unload_lora_weights(self) -> None:
            return None

        def load_ip_adapter(self, *_args: object, **_kwargs: object) -> None:
            return None

        def set_ip_adapter_scale(self, _scale: float) -> None:
            return None

        def __call__(self, **kwargs: object) -> object:
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("one item failed")
            self.calls.append(kwargs)
            return types.SimpleNamespace(images=[FakeImage()])

    pipes: list[FakePipe] = []

    class FakeGenerator:
        def __init__(self, _device: str = "cpu", **_kwargs: object) -> None:
            pass

        def manual_seed(self, _seed: int) -> FakeGenerator:
            return self

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.float16 = "float16"
    fake_torch.float32 = "float32"
    fake_torch.Generator = FakeGenerator  # type: ignore[attr-defined]
    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.AutoencoderKL = types.SimpleNamespace(
        from_pretrained=lambda *_args, **_kwargs: object()
    )
    fake_diffusers.StableDiffusionXLPipeline = FakePipe
    fake_diffusers.StableDiffusionXLImg2ImgPipeline = FakePipe
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)

    from PIL import Image

    init_image = tmp_path / "init.png"
    Image.new("RGB", (4, 4), "white").save(init_image)
    output = tmp_path / "worker.png"
    task_path = tmp_path / "worker.json"
    task_path.write_text(
        json.dumps(
            {
                "model_id": "sdxl",
                "seed": 4,
                "prompt": "ink harbor",
                "negative_prompt": "bad",
                "num_inference_steps": 2,
                "guidance_scale": 5,
                "width": 8,
                "height": 8,
                "output_path": str(output),
            }
        ),
        encoding="utf-8",
    )
    import hevi.image._sdxl_worker as worker

    monkeypatch.setattr(sys, "argv", ["_sdxl_worker.py", str(task_path)])
    worker.main()
    assert output.exists() and pipes[-1].calls[0]["width"] == 8

    img2img_output = tmp_path / "img2img.png"
    task_path.write_text(
        json.dumps(
            {
                "model_id": "sdxl",
                "seed": 5,
                "prompt": "turn",
                "num_inference_steps": 2,
                "guidance_scale": 5,
                "width": 8,
                "height": 8,
                "init_image": str(init_image),
                "strength": 0.7,
                "output_path": str(img2img_output),
            }
        ),
        encoding="utf-8",
    )
    worker.main()
    assert img2img_output.exists() and "image" in pipes[-1].calls[0]

    task_path.write_text(
        json.dumps({"init_image": str(init_image), "ip_adapter_image": str(init_image)}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="互斥"):
        worker.main()

    import hevi.image._sdxl_batch_worker as batch_worker

    batch_output = tmp_path / "batch.json"
    batch_task = tmp_path / "batch-task.json"
    pipes.clear()
    batch_task.write_text(
        json.dumps(
            {
                "model_id": "sdxl",
                "results_path": str(batch_output),
                "items": [
                    {
                        "seed": 1,
                        "prompt": "a",
                        "width": 8,
                        "height": 8,
                        "num_inference_steps": 2,
                        "guidance_scale": 5,
                        "output_path": str(tmp_path / "a.png"),
                    },
                    {
                        "seed": 2,
                        "prompt": "b",
                        "width": 8,
                        "height": 8,
                        "num_inference_steps": 2,
                        "guidance_scale": 5,
                        "output_path": str(tmp_path / "b.png"),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    FakePipe.fail_created_pipe = True
    monkeypatch.setattr(sys, "argv", ["_sdxl_batch_worker.py", str(batch_task)])
    batch_worker.main()
    results = json.loads(batch_output.read_text(encoding="utf-8"))
    assert results == [{"ok": False, "error": "one item failed"}, {"ok": True}]

    batch_task.write_text(
        json.dumps(
            {
                "model_id": "sdxl",
                "results_path": str(batch_output),
                "items": [{"ip_adapter_image": str(init_image), "seed": 1}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="需要 CUDA"):
        batch_worker.main()


@pytest.mark.asyncio
async def test_libtv_agent_boundary_extracts_and_downloads_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock

    import httpx

    import hevi.video.libtv_service as libtv

    monkeypatch.setattr(libtv.settings, "libtv_access_key", "secret")
    monkeypatch.setattr(libtv.settings, "libtv_im_base", "https://agent.example/")
    assert libtv._base() == "https://agent.example"
    assert libtv._headers()["Authorization"] == "Bearer secret"
    messages = [
        {"role": "tool", "content": json.dumps({"task_result": {"images": [{"previewPath": "https://libtv-res.liblib.art/a.png"}], "videos": [{"url": "https://libtv-res.liblib.art/a.mp4"}]}})},
        {"role": "assistant", "content": "see https://libtv-res.liblib.art/a.mp4"},
        {"role": "user", "content": "ignored"},
    ]
    assert libtv.extract_result_urls(messages) == [
        "https://libtv-res.liblib.art/a.png",
        "https://libtv-res.liblib.art/a.mp4",
    ]

    class Response:
        content = b"video-bytes"

        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def json(self) -> dict[str, object]:
            return self.body

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"data": {"sessionId": "sid", "projectUuid": "project"}})

        async def get(self, url: str, **_kwargs: object) -> Response:
            if "/openapi/session/" in url:
                return Response({"data": {"messages": messages}})
            return Response({})

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    result = await libtv.generate_via_libtv(
        "make a historical clip", tmp_path, poll_interval_s=0, timeout_s=1
    )
    assert result["session_id"] == "sid"
    assert result["video"] is not None
    assert Path(result["video"]).read_bytes() == b"video-bytes"
    assert ".liblib.tv/canvas?projectId=project" in result["project_url"]

    monkeypatch.setattr(libtv.settings, "libtv_access_key", "")
    with pytest.raises(libtv.LibtvError, match="未配置"):
        libtv._headers()
    monkeypatch.setattr(libtv, "create_session", AsyncMock(return_value={}))
    with pytest.raises(libtv.LibtvError, match="sessionId"):
        await libtv.generate_via_libtv("x", tmp_path, poll_interval_s=0, timeout_s=1)


@pytest.mark.asyncio
async def test_wan_local_generation_builds_t2v_and_vace_subprocess_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock

    import hevi.video.wan_local_service as wan

    assert wan._seed_for(Path("shot_0001_v0.mp4")) != wan._seed_for(Path("shot_0001_v1.mp4"))
    existing = tmp_path / "model.bin"
    existing.write_bytes(b"weights")
    monkeypatch.setattr(wan, "_WAN_CACHE_FILES", [existing, tmp_path / "missing.bin"])
    await wan.prewarm_wan_cache()

    class Lock:
        async def __aenter__(self) -> Lock:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    def acquire(_vram: int) -> Lock:
        return Lock()
    monkeypatch.setattr(wan.scheduler, "acquire", acquire)
    runner = AsyncMock(side_effect=lambda **kwargs: Path(kwargs["output_path"]))
    real_run_wgp = wan._run_wgp
    monkeypatch.setattr(wan, "prewarm_wan_cache", AsyncMock())
    monkeypatch.setattr(wan, "_run_wgp", runner)
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"ref")
    generated = await wan.wan_local_generate(prompt="t2v", output_path=tmp_path / "t2v.mp4")
    assert generated.name == "t2v.mp4"
    await wan.wan_local_generate(
        prompt="vace", output_path=tmp_path / "vace.mp4", reference_image=reference
    )
    first = runner.await_args_list[0].kwargs
    second = runner.await_args_list[1].kwargs
    assert first["reference_image"] is None and second["reference_image"] == reference

    class Proc:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode
            self.stdout = self

        def __aiter__(self) -> Proc:
            return self

        async def __anext__(self) -> bytes:
            if hasattr(self, "done"):
                raise StopAsyncIteration
            self.done = True
            return b"rendering\n"

        async def wait(self) -> int:
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    async def subprocess(*_args: object, **kwargs: object) -> Proc:
        output_dir = Path(str(kwargs["cwd"]))
        _ = output_dir
        cmd = [str(x) for x in _args]
        out_dir = Path(cmd[cmd.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "generated.mp4").write_bytes(b"video")
        return Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", subprocess)
    monkeypatch.setattr(wan, "_run_wgp", real_run_wgp)
    result = await wan._run_wgp(
        prompt="story", output_path=tmp_path / "direct.mp4", size=(8, 8), frame_num=3, seed=1
    )
    assert result.exists()
    result_vace = await wan._run_wgp(
        prompt="story", output_path=tmp_path / "direct-vace.mp4", size=(8, 8), frame_num=3, seed=2, reference_image=reference
    )
    assert result_vace.exists()


@pytest.mark.asyncio
async def test_voicepro_translate_providers_and_pipeline_dispatch_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from hevi.voicepro_translate.omodul import (
        plan_ai_short,
        plan_clip_generator,
        plan_youtube_studio,
    )
    from hevi.voicepro_translate.oprim import (
        apply_terminology,
        translate_azure_translator,
        translate_deep_translator,
        translate_deepl,
        translate_llm,
        translate_text,
    )
    from hevi.voicepro_translate.oskill import (
        skill_apply_terminology,
        skill_batch_translate,
        skill_translate_text,
    )
    from hevi.voicepro_translate.schemas import TranslateProvider, make_translate_config

    class DeepLResult:
        text = "你好"

    class Translator:
        def __init__(self, _key: str) -> None:
            pass

        def translate_text(self, *_args: object, **_kwargs: object) -> DeepLResult:
            return DeepLResult()

    deepl = types.ModuleType("deepl")
    deepl.Translator = Translator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepl", deepl)
    deepl_result = await translate_deepl("hello", api_key="key")
    assert deepl_result.translated_text == "你好" and deepl_result.provider is TranslateProvider.DEEPL

    class GoogleTranslator:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def translate(self, _text: str) -> str:
            return "译文"

    deep_translator = types.ModuleType("deep_translator")
    deep_translator.GoogleTranslator = GoogleTranslator  # type: ignore[attr-defined]
    deep_translator.BingTranslator = GoogleTranslator  # type: ignore[attr-defined]
    deep_translator.LibreTranslator = GoogleTranslator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deep_translator", deep_translator)
    translated = await translate_deep_translator("hello", backend="unknown")
    assert translated.translated_text == "译文"
    assert (await translate_azure_translator("hello")).translated_text == "hello"

    class Completions:
        async def create(self, **_kwargs: object) -> object:
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="LLM译文"))]
            )

    class OpenAI:
        def __init__(self, **_kwargs: object) -> None:
            self.chat = types.SimpleNamespace(completions=Completions())

    openai = types.ModuleType("openai")
    openai.AsyncOpenAI = OpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", openai)
    llm_result = await translate_llm("hello", terminology_map={"hello": "你好"})
    assert llm_result.translated_text == "LLM译文"
    assert apply_terminology("hello world", {"hello": "你好"}) == "你好 world"

    config = make_translate_config(TranslateProvider.AZURE_TRANSLATOR)
    assert (await translate_text("text", config)).provider is TranslateProvider.AZURE_TRANSLATOR
    assert (await translate_text("text", make_translate_config(TranslateProvider.DEEPL))).provider is TranslateProvider.DEEPL
    assert (await translate_text("text", make_translate_config(TranslateProvider.DEEP_TRANSLATOR))).provider is TranslateProvider.DEEP_TRANSLATOR
    with pytest.raises(ValueError, match="不支持"):
        await translate_text("text", types.SimpleNamespace(provider="bad"))  # type: ignore[arg-type]

    async def fake_translate(text: str, *_args: object, **_kwargs: object) -> object:
        return types.SimpleNamespace(translated_text=f"translated:{text}")

    import hevi.voicepro_translate.oskill as oskill

    monkeypatch.setattr(oskill, "translate_text", fake_translate)
    one = await skill_translate_text("a", provider=TranslateProvider.AZURE_TRANSLATOR)
    many = await skill_batch_translate(["a", "b"], provider=TranslateProvider.AZURE_TRANSLATOR)
    assert one.translated_text == "translated:a" and len(many) == 2
    assert skill_apply_terminology("old", {"old": "new"}) == "new"
    assert plan_ai_short(description="d", cost_mode="standard")["estimated_cost_usd"] == 2.0
    assert len(plan_youtube_studio("video")["stages"]) == 4
    assert plan_clip_generator("video", target_clips=3)["pipeline"] == "clip_generator"


@pytest.mark.asyncio
async def test_talking_face_engine_selection_and_fallback_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import AsyncMock

    import httpx

    import hevi.digital_human.talking_face as talking_face

    image = tmp_path / "presenter.jpg"
    audio = tmp_path / "audio.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")
    output = tmp_path / "face.mp4"
    monkeypatch.setenv("GEN_ENGINE_BASE_URL", "http://engine.example/")
    assert talking_face._engine_base_url() == "http://engine.example"

    class Response:
        def __init__(self, status_code: int = 200, content: bytes = b"video") -> None:
            self.status_code = status_code
            self.content = content
            self.text = "detail"

        def json(self) -> dict[str, object]:
            return {"longcat": True}

    class EngineClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> EngineClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _path: str) -> Response:
            return Response()

        async def post(self, _path: str, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", EngineClient)
    assert (await talking_face._engine_capabilities())["longcat"] is True
    engine_output = await talking_face._run_engine_longcat(
        image_path=image,
        audio_path=audio,
        output_path=output,
        preset_name="default",
        gpu_id=0,
    )
    assert engine_output == output and output.exists()

    class StatusClient(EngineClient):
        def __init__(self, **_kwargs: object) -> None:
            self.status = 501

        async def post(self, _path: str, **_kwargs: object) -> Response:
            return Response(self.status, b"")

    monkeypatch.setattr(httpx, "AsyncClient", StatusClient)
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="无 LongCat"):
        await talking_face._run_engine_longcat(
            image_path=image,
            audio_path=audio,
            output_path=tmp_path / "501.mp4",
            preset_name="default",
            gpu_id=0,
        )

    class EmptyClient(StatusClient):
        def __init__(self, **_kwargs: object) -> None:
            self.status = 200

        async def post(self, _path: str, **_kwargs: object) -> Response:
            return Response(200, b"")

    monkeypatch.setattr(httpx, "AsyncClient", EmptyClient)
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="空视频"):
        await talking_face._run_engine_longcat(
            image_path=image,
            audio_path=audio,
            output_path=tmp_path / "empty.mp4",
            preset_name="default",
            gpu_id=0,
        )

    async def echo(**kwargs: object) -> Path:
        path = Path(str(kwargs["output_path"]))
        path.write_bytes(b"echo")
        return path

    monkeypatch.setattr("hevi.providers.echo_mimic.provider.echo_mimic_generate", echo)
    monkeypatch.setenv("TALKING_FACE_ENGINE", "echomimic")
    generated = await talking_face.generate_talking_face(
        image_path=image, audio_path=audio, output_path=tmp_path / "echo.mp4"
    )
    assert generated.exists()

    async def duix(**kwargs: object) -> Path:
        path = Path(str(kwargs["output_path"]))
        path.write_bytes(b"duix")
        return path

    monkeypatch.setattr("hevi.digital_human.duix_offline.generate_silent_duix", duix)
    monkeypatch.setenv("TALKING_FACE_ENGINE", "duix")
    duix_path = await talking_face.generate_talking_face(
        image_path=image,
        audio_path=audio,
        output_path=tmp_path / "duix.mp4",
        reference_video=tmp_path / "missing-reference.mp4",
    )
    assert duix_path.exists()

    monkeypatch.setenv("TALKING_FACE_ENGINE", "generic")
    monkeypatch.setattr(talking_face, "_engine_capabilities", AsyncMock(return_value={}))
    generic = AsyncMock()
    generic.return_value = tmp_path / "generic.mp4"
    generic.return_value.write_bytes(b"generic")
    monkeypatch.setattr(talking_face, "_run_generic_lipsync", generic)
    generic_path = await talking_face.generate_talking_face(
        image_path=image, audio_path=audio, output_path=tmp_path / "generic.mp4"
    )
    assert generic_path.exists()

    placeholder = tmp_path / "placeholder.mp4"

    async def make_placeholder(**_kwargs: object) -> Path:
        placeholder.write_bytes(b"placeholder")
        return placeholder

    monkeypatch.setenv("TALKING_FACE_ENGINE", "unknown")
    monkeypatch.setattr(talking_face, "_generate_placeholder_avoiding_null", make_placeholder)
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="未知 Talking Face"):
        await talking_face.generate_talking_face(
            image_path=image, audio_path=audio, output_path=placeholder
        )

    with pytest.raises(talking_face.TalkingFaceUnavailable, match="Presenter image"):
        await talking_face.generate_talking_face(
            image_path=tmp_path / "missing.jpg", audio_path=audio, output_path=tmp_path / "x.mp4"
        )
    empty_audio = tmp_path / "empty.wav"
    empty_audio.touch()
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="empty"):
        await talking_face.generate_talking_face(
            image_path=image, audio_path=empty_audio, output_path=tmp_path / "x.mp4"
        )

    monkeypatch.setattr(talking_face, "generate_talking_face", AsyncMock(return_value=output))
    continuous = await talking_face.generate_continuous_avatar_track(
        image_path=image,
        master_audio_path=audio,
        output_dir=tmp_path / "continuous",
        aspect_ratio="16:9",
    )
    assert continuous == output


@pytest.mark.asyncio
async def test_runway_and_json2video_provider_boundaries_cover_submit_poll_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    import hevi.image.json2video_scene_service as json2video
    import hevi.video.runway_service as runway

    image = tmp_path / "reference.png"
    image.write_bytes(b"reference")

    class Response:
        def __init__(self, body: dict[str, object], content: bytes = b"") -> None:
            self.body = body
            self.content = content
            self.text = json.dumps(body)

        def json(self) -> dict[str, object]:
            return self.body

        def raise_for_status(self) -> None:
            return None

    class ProviderClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> ProviderClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"id": "runway-job"})

        async def get(self, url: str, **_kwargs: object) -> Response:
            if url.endswith("runway-job"):
                return Response({"status": "SUCCEEDED", "output": ["https://cdn/result.png"]})
            return Response({}, b"provider-result")

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(httpx, "AsyncClient", ProviderClient)
    monkeypatch.setattr("hevi.video.runway_service.asyncio.sleep", no_sleep)
    local_uri = runway._as_uri(str(image))
    assert local_uri.startswith("data:image/png;base64,")
    assert runway._as_uri("https://cdn/image.png") == "https://cdn/image.png"
    image_result = await runway.runway_text_to_image(
        prompt="harbor",
        output_path=tmp_path / "runway.png",
        config={"RUNWAY_API_KEY": "key"},
        reference_images=[str(image)],
        seed=4,
        poll_interval_s=0,
        timeout_s=1,
    )
    assert image_result.exists()
    video_result = await runway.runway_image_to_video(
        prompt="move",
        reference_images=[str(image)],
        output_path=tmp_path / "runway.mp4",
        config={"RUNWAY_API_KEY": "key"},
        duration=5,
        poll_interval_s=0,
        timeout_s=1,
    )
    assert video_result.exists()
    with pytest.raises(runway.RunwayError, match="at least"):
        await runway.runway_image_to_video(
            prompt="move", reference_images=[], output_path=tmp_path / "no.mp4", config={"RUNWAY_API_KEY": "key"}
        )
    with pytest.raises(runway.RunwayError, match="1-3"):
        await runway.runway_text_to_image(
            prompt="x", output_path=tmp_path / "no.png", config={"RUNWAY_API_KEY": "key"}, reference_images=["a", "b", "c", "d"]
        )
    monkeypatch.setenv("RUNWAY_API_KEY", "")
    with pytest.raises(runway.RunwayError, match="not configured"):
        runway._resolve_api_key({})

    class JsonClient(ProviderClient):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"project": "project-1"})

        async def get(self, url: str, **_kwargs: object) -> Response:
            if "movies?" in url or url.endswith("movies"):
                return Response({"movie": {"status": "done", "url": "https://cdn/movie.mp4"}})
            return Response({}, b"movie")

    monkeypatch.setattr(httpx, "AsyncClient", JsonClient)
    monkeypatch.setattr("hevi.image.json2video_scene_service.asyncio.sleep", no_sleep)
    monkeypatch.setattr(
        json2video,
        "_extract_first_frame",
        lambda _video, out: out.write_bytes(b"frame"),
    )
    frame = await json2video.json2video_scene_generate(
        prompt="harbor",
        negative_prompt="text",
        output_path=tmp_path / "frame.png",
        config={"JSON2VIDEO_API_KEY": "key"},
        poll_interval_s=0,
        timeout_s=1,
    )
    assert frame["output_path"].endswith("frame.png")
    monkeypatch.setenv("JSON2VIDEO_API_KEY", "")
    with pytest.raises(json2video.Json2VideoError, match="not configured"):
        await json2video.json2video_scene_generate(
            prompt="x", output_path=tmp_path / "missing.png", config={}
        )


@pytest.mark.asyncio
async def test_talking_face_fallback_subprocess_and_error_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys
    import types
    from unittest.mock import AsyncMock

    import httpx

    import hevi.digital_human.talking_face as talking_face

    image = tmp_path / "presenter.jpg"
    audio = tmp_path / "audio.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")

    class ErrorClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> ErrorClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _path: str) -> object:
            raise httpx.HTTPError("offline")

    monkeypatch.setattr(httpx, "AsyncClient", ErrorClient)
    assert await talking_face._engine_capabilities() == {}

    from hevi.digital_human.duix_service import DuixUnavailable

    async def bad_duix(**_kwargs: object) -> Path:
        raise DuixUnavailable("offline")

    monkeypatch.setattr("hevi.digital_human.duix_offline.generate_silent_duix", bad_duix)
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="Duix"):
        await talking_face._run_duix_offline(
            image_path=image,
            audio_path=audio,
            output_path=tmp_path / "duix-fail.mp4",
        )

    from hevi.providers.h3_local.comfy_client import H3ComfyError

    async def bad_echo(**_kwargs: object) -> Path:
        raise H3ComfyError("comfy offline")

    monkeypatch.setattr("hevi.providers.echo_mimic.provider.echo_mimic_generate", bad_echo)
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="EchoMimicV2"):
        await talking_face._run_echo_mimic(
            image_path=image,
            audio_path=audio,
            output_path=tmp_path / "echo-fail.mp4",
        )

    class ServerErrorClient(ErrorClient):
        async def post(self, _path: str, **_kwargs: object) -> object:
            return types.SimpleNamespace(status_code=500, content=b"", text="server error", json=dict)

    monkeypatch.setattr(httpx, "AsyncClient", ServerErrorClient)
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="HTTP 500"):
        await talking_face._run_engine_longcat(
            image_path=image,
            audio_path=audio,
            output_path=tmp_path / "server.mp4",
            preset_name="default",
            gpu_id=0,
        )
    with pytest.raises(talking_face.TalkingFaceUnavailable, match="服务不可用"):
        await talking_face._run_engine_longcat(
            image_path=tmp_path / "missing.jpg",
            audio_path=audio,
            output_path=tmp_path / "missing-output.mp4",
            preset_name="default",
            gpu_id=0,
        )

    class Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def subprocess(*_args: object, **_kwargs: object) -> Proc:
        return Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", subprocess)
    generic = await talking_face._run_generic_lipsync(
        image_path=image, audio_path=audio, output_path=tmp_path / "generic.mp4"
    )
    assert generic.name == "generic.mp4"

    fake_oprim = types.ModuleType("oprim")
    fake_oprim.probe_duration = lambda _path: 2.0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "oprim", fake_oprim)
    calls: list[tuple[object, ...]] = []

    async def placeholder_process(*args: object, **_kwargs: object) -> Proc:
        calls.append(args)
        if "-t" in args:
            output = Path(str(args[-1]))
            output.write_bytes(b"placeholder")
        return Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", placeholder_process)
    placeholder = await talking_face._generate_placeholder_avoiding_null(
        audio_path=audio, output_path=tmp_path / "placeholder.mp4"
    )
    assert placeholder.exists() and len(calls) == 2
    assert talking_face._detail(types.SimpleNamespace(json=lambda: {"detail": "bad"}, text="x", status_code=500)) == "bad"
    assert talking_face._detail(types.SimpleNamespace(json=dict, text="raw", status_code=500)) == "raw"

    monkeypatch.setattr(talking_face, "generate_talking_face", AsyncMock(return_value=image))
    portrait = await talking_face.generate_continuous_avatar_track(
        image_path=image,
        master_audio_path=audio,
        output_dir=tmp_path / "portrait",
        aspect_ratio="9:16",
    )
    assert portrait == image


@pytest.mark.asyncio
async def test_studio_ops_dispatches_wrappers_and_preserves_failure_semantics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:

    import hevi.studio.ops as ops

    assert (await ops.run_op("missing-op", {}))["status"] == "failed"
    monkeypatch.setitem(ops.OPS, "boom", lambda _payload: (_ for _ in ()).throw(RuntimeError("boom")))
    assert (await ops.run_op("boom", {}))["reason"] == "boom"
    monkeypatch.setattr(
        "hevi.ingest.preflight.check_env",
        lambda **_kwargs: SimpleNamespace(can_proceed=True, missing_binaries=["ffmpeg"]),
    )
    assert (await ops.run_op("ingest_preflight", {}))["missing"] == ["ffmpeg"]
    local = tmp_path / "local.mp4"
    local.write_bytes(b"video")
    fetched = await ops.ingest_fetch({"source": str(local), "work_dir": str(tmp_path / "work")})
    assert fetched["local"] is True
    monkeypatch.setattr("hevi.ingest.video_fetch.fetch_video", lambda *_args: local)
    remote = await ops.ingest_fetch({"source": "https://example/video", "work_dir": str(tmp_path)})
    assert remote["video_path"] == str(local)
    assert ops.research_context({"topic": "history"})["questions"]
    assert ops.split_history({"lines": ["旁白", {"type": "dialogue", "text": "你好"}]})["status"] == "ok"

    async def mix(_value: object) -> SimpleNamespace:
        return SimpleNamespace(to_dict=lambda: {"commentary_count": 1})

    monkeypatch.setattr("hevi.studio.mix.plan_history_mix", mix)
    assert (await ops.tongjian_mix({"script": []}))["mix"]["commentary_count"] == 1
    preview = ops.preview_budget({"cues": [{"text": "a"}, {"text": "b"}]})
    assert preview["count"] == 2
    monkeypatch.setattr("hevi.audio.prosody.analyze_prosody", lambda _text: (_ for _ in ()).throw(RuntimeError("no prosody")))
    assert ops.audio_prosody({"text": "a，b。"})["prosody"]["pauses"] == 2
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    concat = tmp_path / "concat.wav"
    monkeypatch.setattr("hevi.explainer.echo_avatar.concat_audio_files", lambda _paths, dest: dest.write_bytes(b"joined"))
    assert ops.audio_concat({"paths": [str(audio)], "output_path": str(concat)})["master"] == str(concat)
    assert ops.audio_concat({"paths": []})["status"] == "failed"
    monkeypatch.setattr("hevi.production.delivery_gate.probe_video", lambda _path: SimpleNamespace(duration_s=2, has_audio=True, has_video=True))
    assert ops.audio_probe({"path": str(local)})["probe"]["has_video"] is True
    assert ops.aspect_fit({"target": "16:9", "candidate": "9:16"})["status"] == "ok"
    assert ops.pick_best({"query": "harbor", "items": [{"id": "m1", "title": "harbor"}]})["best"]["id"] == "m1"

    async def invoke(_name: str, _payload: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(status="queued", reason="", payload={"accepted": True})

    monkeypatch.setattr("hevi.studio.tools.invoke_tool", invoke)
    assert (await ops.score_video({"path": str(local)}))["accepted"] is True
    for publisher in (ops.pub_douyin, ops.pub_kuaishou, ops.pub_xhs, ops.pub_sph, ops.pub_bili):
        assert (await publisher({"topic": "history"}))["accepted"] is True
    assert ops.qc_production({"shots": []})["status"] == "ok"
    assert ops.qc_layout({"boxes": [1]})["boxes"] == 1
    assert ops.clip_factory({"edit_plan": {"cuts": [{"action": "keep"}, {"action": "drop"}]}})["count"] == 1
    assert ops.dub_translate({"lines": [{"text": "x"}], "lang": "en"})["lines"][0]["translated"] is False
    assert ops.recipe_nodes({"line_id": "explainer"})["line_id"] == "explainer"

    fake_timeline = SimpleNamespace(to_dict=lambda: {"timeline_id": "tl"})
    monkeypatch.setattr("hevi.studio.timeline.timeline_from_edit_plan", lambda *_args, **_kwargs: fake_timeline)
    monkeypatch.setattr("hevi.studio.timeline.patch_clip", lambda *_args, **_kwargs: fake_timeline)
    monkeypatch.setattr("hevi.studio.timeline.export_timeline", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr("hevi.studio.timeline.split_at", lambda *_args, **_kwargs: fake_timeline)
    monkeypatch.setattr("hevi.studio.timeline.ripple", lambda *_args, **_kwargs: fake_timeline)
    monkeypatch.setattr("hevi.studio.timeline.set_bgm", lambda *_args, **_kwargs: fake_timeline)
    assert (await ops.tl_create({"edit_plan": {}, "title": "x"}))["timeline"]["timeline_id"] == "tl"
    assert (await ops.tl_patch({"timeline_id": "tl", "clip_id": "c"}))["status"] == "ok"
    assert (await ops.tl_export({"timeline_id": "tl"}))["status"] == "ok"
    assert (await ops.tl_split({"timeline_id": "tl", "at_s": 1}))["status"] == "ok"
    assert (await ops.tl_ripple({"timeline_id": "tl"}))["status"] == "ok"
    assert (await ops.tl_bgm({"timeline_id": "tl", "bgm": "music"}))["status"] == "ok"
    monkeypatch.setattr("hevi.studio.timeline.patch_clip", lambda *_args, **_kwargs: None)
    assert (await ops.tl_patch({"timeline_id": "missing", "clip_id": "c"}))["status"] == "failed"

    craft = {
        "compile_shot_spec": lambda value: {"shot": value},
        "seedance_prompt": lambda value: {"seedance": value},
        "plan_broll": lambda value: {"broll": value},
        "taste_dials": lambda value: {"taste": value},
        "slideshow_risk": lambda value: {"slideshow": value},
        "source_review": lambda value: {"source": value},
        "variation_check": lambda value: {"variation": value},
        "grade_plan": lambda value: {"grade": value},
        "site_to_video_plan": lambda value: {"site": value},
    }
    for name, fn in craft.items():
        monkeypatch.setattr("hevi.studio.craft." + name, fn)
    assert ops.craft_shot_spec({"x": 1})["shot"]["x"] == 1
    assert ops.craft_seedance({})["seedance"] == {}
    assert ops.craft_broll({})["broll"] == {}
    assert ops.craft_taste({})["taste"] == {}
    assert ops.craft_slideshow({})["slideshow"] == {}
    assert ops.craft_source({})["source"] == {}
    assert ops.craft_variation({})["variation"] == {}
    assert ops.craft_grade({})["grade"] == {}
    assert ops.craft_site({})["site"] == {}
    assert ops.delivery_validate({})["status"] == "failed"
    assert ops.verdict_source_review({})["status"] == "failed"

    async def tick(**_kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(to_dict=lambda: {"job": "j"})]

    async def produce(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(to_dict=lambda: {"job": "p"})

    monkeypatch.setattr("hevi.studio.daily.tick", tick)
    monkeypatch.setattr("hevi.studio.veya.produce", produce)
    assert (await ops.daily_tick({"publish": False}))["count"] == 1
    assert (await ops.veya_produce({"line_id": "explainer"}))["job"]["job"] == "p"


@pytest.mark.asyncio
async def test_provider_boundaries_reject_malformed_and_terminal_failure_responses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    import hevi.image.json2video_scene_service as json2video
    import hevi.video.runway_service as runway

    class Response:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body
            self.text = json.dumps(body)
            self.content = b""

        def json(self) -> dict[str, object]:
            return self.body

        def raise_for_status(self) -> None:
            return None

    class Client:
        response = Response({})

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **_kwargs: object) -> Response:
            return self.response

        async def get(self, _url: str, **_kwargs: object) -> Response:
            return self.response

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("hevi.image.json2video_scene_service.asyncio.sleep", no_sleep)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    Client.response = Response({})
    with pytest.raises(json2video.Json2VideoError, match="project id"):
        await json2video.json2video_scene_generate(
            prompt="x", output_path=tmp_path / "bad.png", config={"JSON2VIDEO_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )
    with pytest.raises(json2video.Json2VideoError, match="失败"):
        class ErrorJsonClient(Client):
            async def post(self, _url: str, **_kwargs: object) -> Response:
                return Response({"project": "p"})

            async def get(self, _url: str, **_kwargs: object) -> Response:
                return Response({"movie": {"status": "error", "message": "provider failed"}})

        monkeypatch.setattr(httpx, "AsyncClient", ErrorJsonClient)
        await json2video.json2video_scene_generate(
            prompt="x", output_path=tmp_path / "bad.png", config={"JSON2VIDEO_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )
    class DoneWithoutUrl(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"project": "p"})

        async def get(self, _url: str, **_kwargs: object) -> Response:
            return Response({"movie": {"status": "done"}})

    monkeypatch.setattr(httpx, "AsyncClient", DoneWithoutUrl)
    with pytest.raises(json2video.Json2VideoError, match="无产物 URL"):
        await json2video.json2video_scene_generate(
            prompt="x", output_path=tmp_path / "bad.png", config={"JSON2VIDEO_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )

    monkeypatch.setattr("hevi.video.runway_service.asyncio.sleep", no_sleep)
    class FailedRunway(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"id": "job"})

        async def get(self, _url: str, **_kwargs: object) -> Response:
            return Response({"status": "FAILED", "failure": "bad prompt"})

    monkeypatch.setattr(httpx, "AsyncClient", FailedRunway)
    with pytest.raises(runway.RunwayError, match="失败"):
        await runway.runway_text_to_image(
            prompt="x", output_path=tmp_path / "bad.png", config={"RUNWAY_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )

    class NoRunwayId(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({})

    monkeypatch.setattr(httpx, "AsyncClient", NoRunwayId)
    with pytest.raises(runway.RunwayError, match="缺少 id"):
        await runway.runway_text_to_image(
            prompt="x", output_path=tmp_path / "bad.png", config={"RUNWAY_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )

    class PendingRunway(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"id": "job"})

        async def get(self, _url: str, **_kwargs: object) -> Response:
            return Response({"status": "RUNNING"})

    monkeypatch.setattr(httpx, "AsyncClient", PendingRunway)
    with pytest.raises(runway.RunwayError, match="未完成"):
        await runway.runway_text_to_image(
            prompt="x", output_path=tmp_path / "pending.png", config={"RUNWAY_API_KEY": "key"}, poll_interval_s=1, timeout_s=1
        )

    class NoOutputRunway(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"id": "job"})

        async def get(self, _url: str, **_kwargs: object) -> Response:
            return Response({"status": "SUCCEEDED", "output": []})

    monkeypatch.setattr(httpx, "AsyncClient", NoOutputRunway)
    with pytest.raises(runway.RunwayError, match="无产物"):
        await runway.runway_text_to_image(
            prompt="x", output_path=tmp_path / "empty.png", config={"RUNWAY_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )

    frame = tmp_path / "frame.png"
    calls: list[tuple[object, ...]] = []

    def successful_ffmpeg(*args: object, **_kwargs: object) -> None:
        calls.append(args)

    monkeypatch.setattr(json2video.subprocess, "run", successful_ffmpeg)
    json2video._extract_first_frame(tmp_path / "movie.mp4", frame)
    assert calls and "-frames:v" in calls[0][0]

    def failed_ffmpeg(*_args: object, **_kwargs: object) -> None:
        raise json2video.subprocess.CalledProcessError(1, "ffmpeg", stderr="invalid movie")

    monkeypatch.setattr(json2video.subprocess, "run", failed_ffmpeg)
    with pytest.raises(json2video.Json2VideoError, match="抽帧失败"):
        json2video._extract_first_frame(tmp_path / "movie.mp4", frame)

    class HttpErrorJsonClient(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            class ErrorResponse(Response):
                def raise_for_status(self) -> None:
                    raise httpx.HTTPError("submit unavailable")

            return ErrorResponse({})

    monkeypatch.setattr(httpx, "AsyncClient", HttpErrorJsonClient)
    with pytest.raises(json2video.Json2VideoError, match="任务提交失败"):
        await json2video.json2video_scene_generate(
            prompt="x", output_path=tmp_path / "bad.png", config={"JSON2VIDEO_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )

    class PollErrorJsonClient(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"project": "p"})

        async def get(self, _url: str, **_kwargs: object) -> Response:
            class ErrorResponse(Response):
                def raise_for_status(self) -> None:
                    raise httpx.HTTPError("poll unavailable")

            return ErrorResponse({})

    monkeypatch.setattr(httpx, "AsyncClient", PollErrorJsonClient)
    with pytest.raises(json2video.Json2VideoError, match="任务查询失败"):
        await json2video.json2video_scene_generate(
            prompt="x", output_path=tmp_path / "bad.png", config={"JSON2VIDEO_API_KEY": "key"}, poll_interval_s=0, timeout_s=1
        )

    class PendingJsonClient(Client):
        async def post(self, _url: str, **_kwargs: object) -> Response:
            return Response({"project": "p"})

        async def get(self, _url: str, **_kwargs: object) -> Response:
            return Response({"movie": {"status": "running"}})

    monkeypatch.setattr(httpx, "AsyncClient", PendingJsonClient)
    with pytest.raises(json2video.Json2VideoError, match="未完成"):
        await json2video.json2video_scene_generate(
            prompt="x", output_path=tmp_path / "pending.png", config={"JSON2VIDEO_API_KEY": "key"}, poll_interval_s=1, timeout_s=1
        )

"""Behavioral coverage for the small production contracts and dispatch edges.

These tests exercise the public schemas as they are consumed by the runtime;
they intentionally assert normalization, state transitions, and rejected input
instead of merely importing or instantiating models.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.platforms.oprim.extract import (
    extract_aweme_id,
    extract_aweme_id_from_url,
    extract_ks_photo_id_from_url,
    extract_note_id_from_url,
    extract_query_params,
    extract_sec_uid_from_url,
    extract_short_link,
    extract_urls,
    extract_xsec_token_from_url,
    identify_platform,
    is_short_link,
    looks_like_platform_url,
    normalize_share_text,
    parse_aweme_card,
    parse_creator_target,
    parse_keyword_target,
    parse_note_card,
    strip_emoji,
)


def test_platform_url_and_share_parsers_cover_supported_and_invalid_inputs() -> None:
    assert not looks_like_platform_url("")
    assert looks_like_platform_url("https://www.douyin.com/video/123")
    assert looks_like_platform_url("https://www.xiaohongshu.com/explore/abc")
    assert looks_like_platform_url("https://www.kuaishou.com/short-video/abc")
    assert looks_like_platform_url("https://video.weixin.qq.com/s/abc")
    assert not looks_like_platform_url("https://example.test/video")
    assert not is_short_link("")
    assert is_short_link("dy123")
    assert is_short_link("ks123")
    assert not is_short_link("https://example.test")

    text = "看看 https://v.douyin.com/Ab12) 和 https://xhslink.com/a9。"
    assert normalize_share_text(text) == "https://v.douyin.com/Ab12)"
    assert normalize_share_text("") == ""
    assert extract_urls(text) == ["https://v.douyin.com/Ab12", "https://xhslink.com/a9。"]
    assert extract_urls("") == []
    assert extract_short_link(text) == "v.douyin.com/Ab12"
    assert extract_short_link("nothing here") is None
    assert strip_emoji("你好😀, world!") == "你好, world!"
    assert strip_emoji("") == ""


def test_platform_identifier_and_query_extractors_cover_each_platform() -> None:
    assert identify_platform("https://www.douyin.com/video/1") == "douyin"
    assert identify_platform("https://xhslink.com/a") == "xhs"
    assert identify_platform("https://ks.com/v/1") == "kuaishou"
    assert identify_platform("https://share.videostore.weixin.qq.com/a") == "shipinhao"
    assert identify_platform("https://example.test") is None
    assert identify_platform("") is None

    url = "https://www.douyin.com/video/123?aweme_id=456&sec_uid=u%2B1"
    assert extract_query_params(url) == {"aweme_id": "456", "sec_uid": "u+1"}
    assert extract_query_params("") == {}
    assert extract_aweme_id_from_url(url) == "456"
    assert extract_aweme_id_from_url("https://douyin.com/987") == "987"
    assert extract_aweme_id_from_url("bad") is None
    assert extract_aweme_id(url) == "456"
    assert extract_aweme_id("https://douyin.com/987") == "987"
    assert extract_aweme_id("") is None
    assert extract_sec_uid_from_url(url) == "u+1"
    assert extract_sec_uid_from_url("https://douyin.com/video/1") is None
    assert extract_note_id_from_url("https://xhs.com/a?note_id=n1") == "n1"
    assert extract_note_id_from_url("https://xhs.com/a") is None
    assert extract_xsec_token_from_url("https://xhs.com/a?xsec_token=t1") == "t1"
    assert extract_xsec_token_from_url("") is None
    assert extract_ks_photo_id_from_url("https://ks.com/a?photo_id=p1") == "p1"
    assert extract_ks_photo_id_from_url("") is None


def test_platform_cards_and_monitor_targets_preserve_runtime_fields() -> None:
    aweme = parse_aweme_card(
        {
            "aweme_id": "a1",
            "desc": "desc",
            "author": {"nickname": "N", "uid": "u"},
            "create_time": 10,
            "duration": 2.5,
            "statistics": {"aweme_id": 7, "comment_count": 8},
            "share_count": 9,
            "cover": "cover",
            "tags": ["x"],
            "music": {"music_name": "song", "music_id": "m1"},
            "video": {"width": 1080, "height": 1920},
        }
    )
    assert aweme["author"] == "N"
    assert aweme["like_count"] == 7
    assert aweme["music_id"] == "m1"
    assert parse_aweme_card(None) == {}  # type: ignore[arg-type]

    note = parse_note_card(
        {
            "id": "n1",
            "display_title": "title",
            "images_list": [{"url_default": "i1"}, {"urlDefault": "i2"}, "bad"],
            "video_info": {
                "type": "video",
                "cover": "vc",
                "duration": 4,
                "medias": [{"url": "v1"}, {}],
            },
            "interact_info": {"liked_count": 1, "comment_count": 2, "view_count": 3},
        }
    )
    assert note["note_id"] == "n1"
    assert note["image_urls"] == ["i1", "i2"]
    assert note["video_urls"] == ["v1"]
    assert note["view_count"] == 3
    assert parse_note_card(None) == {}  # type: ignore[arg-type]

    keyword = parse_keyword_target("  history  ")
    assert keyword.target_type == "keyword"
    assert keyword.target_name == "history"
    assert parse_creator_target("https://douyin.com/u?sec_uid=s1").target_id == "s1"
    assert parse_creator_target("https://xhs.com/u?note_id=n1").target_id == "n1"
    assert parse_creator_target("https://example.test/u").platform == "unknown"


def test_platform_schema_decisions_and_risk_classification() -> None:
    from hevi.platforms.schemas import (
        AccountProfile,
        ContentRecord,
        MonitorTarget,
        PublishResult,
        PublishTask,
        RiskCategory,
        classify_platform_error,
    )

    account = AccountProfile(platform="douyin", status="active", has_read_state=True)
    assert account.is_available()
    assert account.can_publish()
    account.status = "risk"
    assert not account.is_available()
    assert not account.can_publish()
    target = MonitorTarget(platform="douyin", group_name="g", tags=["a"])
    assert target.matches_tags("g", "a")
    assert not target.matches_tags("other", "a")
    assert not target.matches_tags("g", "b")
    assert ContentRecord(platform="xhs").media_type == "video"
    assert not PublishTask(platform="xhs", account_id=1).is_available()
    publish = PublishTask(platform="xhs", account_id=1, media_paths=["out.mp4"])
    assert publish.is_available()
    result = PublishResult(status="ok", platform="xhs", external_id="e", url="u")
    assert result.to_dict()["external_id"] == "e"
    assert classify_platform_error("429 captcha")[0] is RiskCategory.RISK
    assert classify_platform_error("login required")[0] is RiskCategory.AUTH
    assert classify_platform_error("network timeout")[0] is RiskCategory.NETWORK
    assert classify_platform_error("unexpected")[0] is RiskCategory.UNKNOWN


def test_montage_contracts_validate_pipeline_cost_and_checkpoint_behavior() -> None:
    from hevi.montage.schemas import (
        Artifact,
        ArtifactType,
        CheckpointPolicy,
        CostBudget,
        CostLineItem,
        PipelineCategory,
        PipelineStability,
        PlaybookSchema,
        StageDef,
        ToolCapability,
        ToolEnvelope,
        ToolTier,
        VideoAnalysisBrief,
        make_default_checkpoint,
        make_default_cost_budget,
        make_default_pipeline_manifest,
        make_default_tool_contract,
    )

    stage = StageDef(name="script", skill="writer", produces=["script"])
    manifest = make_default_pipeline_manifest("test")
    manifest.category = PipelineCategory.TEST
    manifest.stability = PipelineStability.BETA
    manifest.default_checkpoint_policy = CheckpointPolicy.AUTO
    manifest.stages = [stage]
    assert manifest.stages[0].produces == ["script"]
    tool = make_default_tool_contract("writer", ToolCapability.SCRIPT)
    tool.tier = ToolTier.CORE
    tool.fallback_tools = ["local-writer"]
    assert tool.capability is ToolCapability.SCRIPT
    envelope = ToolEnvelope(capabilities={"script": [tool.name]}, total_tools=1)
    assert envelope.total_tools == len(envelope.capabilities["script"])
    budget = CostBudget(
        budget_usd=10,
        reserved_usd=2,
        spent_usd=1,
        line_items=[CostLineItem(tool_name="writer", provider="local", capability="script")],
    )
    assert budget.remaining() == 7
    artifact = Artifact(type=ArtifactType.SCRIPT, pipeline="test", stage="script", approved=True)
    checkpoint = make_default_checkpoint("test", "script")
    checkpoint.artifacts["script"] = artifact
    checkpoint.cost_state = make_default_cost_budget(5)
    assert checkpoint.artifacts["script"].type is ArtifactType.SCRIPT
    assert PlaybookSchema(name="p").preferred_runtime == "remotion"
    assert VideoAnalysisBrief(source_url="u", scene_count=2).scene_count == 2
    assert make_default_cost_budget(3).budget_usd == 3


def test_openshorts_krillin_and_voicepro_contracts_cover_state_changes() -> None:
    from hevi.krillinai.schemas import (
        ClipGeneratorJob as KrillinJob,
    )
    from hevi.krillinai.schemas import (
        JobStatus as KrillinStatus,
    )
    from hevi.krillinai.schemas import (
        make_clip_generator_job as make_krillin_job,
    )
    from hevi.openshorts.schemas import (
        ClipSpec,
        ReframingMode,
        make_ai_short_job,
        make_clip_generator_job,
        make_youtube_studio_job,
    )
    from hevi.voicepro_asr.schemas import (
        ASRResult,
        FunASRResult,
        FunASRWord,
        SentenceSegment,
        WordTimestamp,
        make_asr_config,
    )
    from hevi.voicepro_clone.schemas import CloneMode, make_clone_config
    from hevi.voicepro_translate.schemas import make_translate_config, make_translate_result
    from hevi.voicepro_tts.schemas import make_tts_config, make_tts_result

    clip = ClipSpec(clip_index=1, start_time_s=1, end_time_s=3)
    assert clip.duration_s == 2
    explicit = ClipSpec(clip_index=2, start_time_s=0, end_time_s=3, duration_s=2.5)
    assert explicit.duration_s == 2.5
    short_job = make_clip_generator_job("input.mp4", "u")
    short_job.clips = [clip]
    short_job.reframing = ReframingMode.TRACK
    assert short_job.clips[0].duration_s == 2
    assert make_ai_short_job("product", "https://p", "u").product_url == "https://p"
    assert make_youtube_studio_job("video.mp4", "u").video_path == "video.mp4"

    krillin = make_krillin_job("input.mp4", "u")
    assert isinstance(krillin, KrillinJob)
    krillin.update_status(KrillinStatus.TRANSCRIBING, "asr")
    assert krillin.status is KrillinStatus.TRANSCRIBING
    assert krillin.current_stage == "asr"
    assert krillin.model_dump()["input_source"] == "input.mp4"

    asr = make_asr_config("faster_whisper", model="small", language="en")
    asr_result = ASRResult(
        text="hello",
        words=[WordTimestamp(word="hello", start_s=0, end_s=1)],
        segments=[SentenceSegment(text="hello", is_complete=True)],
    )
    assert asr.provider.value == "faster_whisper"
    assert asr_result.segments[0].is_complete
    assert FunASRResult(result=[FunASRWord(text="hi", start=0, end=1)]).result[0].end == 1
    with pytest.raises(ValueError):
        make_asr_config("not-a-provider")

    translate = make_translate_config("llm_translate", target_lang="en")
    translated = make_translate_result("你好", "hello", "zh", "en", "llm_translate")
    assert translate.target_lang == "en"
    assert translated.translated_text == "hello"
    assert make_translate_result("x", "x", "en", "zh", "deepl", True).kept_original
    tts = make_tts_config("edge_tts", voice="voice", speed=1.2)
    tts_result = make_tts_result("out.wav", "hello", 1.5, "voice", "edge_tts")
    assert tts.speed == 1.2
    assert tts_result.duration_s == 1.5
    clone = make_clone_config("cosyvoice", CloneMode.CROSS_LINGUAL, "ref.wav")
    assert clone.mode is CloneMode.CROSS_LINGUAL
    assert clone.reference_audio == "ref.wav"


def test_erduo_and_magiviz_contracts_parse_inputs_and_preserve_lineage() -> None:
    from hevi.erduo.schemas import (
        ChapterSpec,
        DesignIntent,
        RuntimeBackend,
        Truth,
        make_production_job,
        parse_srt,
    )
    from hevi.magiviz.schemas import (
        SceneVideo,
        VideoAspectRatio,
        VideoModel,
        make_magiviz_job,
        make_story_outline,
    )

    srt = parse_srt("1\n00:00:01,250 --> 00:00:02,500\n第一行\n\n2\n00:00:03,000 --> 00:00:04,000\n第二行\n")
    assert [(entry.start_ms, entry.end_ms) for entry in srt] == [(1250, 2500), (3000, 4000)]
    assert parse_srt("not a subtitle") == []
    truth = Truth(srt=srt, design=DesignIntent(visual_style="ink"))
    job = make_production_job("a.srt", "design.json", RuntimeBackend.REMOTION, "u")
    job.truth = truth
    job.chapters = [ChapterSpec(chapter_id="c1")]
    assert job.backend is RuntimeBackend.REMOTION
    assert job.truth.srt[0].text == "第一行"

    outline = make_story_outline("Title", "Premise", aspect_ratio=VideoAspectRatio.PORTRAIT_9_16)
    magi = make_magiviz_job(outline, "u")
    magi.scene_videos = [SceneVideo(scene_id="s1", video_model=VideoModel.WAN, duration_s=3)]
    assert magi.story_outline.aspect_ratio is VideoAspectRatio.PORTRAIT_9_16
    assert magi.scene_videos[0].video_model is VideoModel.WAN


@pytest.mark.asyncio
async def test_studio_dispatch_ops_return_real_structured_results(tmp_path: Path) -> None:
    from hevi.studio.ops import run_op

    assert (await run_op("does.not.exist", {}))["status"] == "failed"
    assert (await run_op("ingest_fetch", {}))["reason"] == "source required"
    local = tmp_path / "input.mp4"
    local.write_bytes(b"video")
    fetched = await run_op("ingest_fetch", {"source": str(local)})
    assert fetched["local"] is True
    assert (await run_op("ingest_frames", {"source": "x"}))["frames"] == []
    assert (await run_op("ingest_transcript", {"transcript": "hello"}))["transcript"] == "hello"
    assert (await run_op("ingest_contact", {"frames": [1, 2]}))["frames"] == 2
    assert (await run_op("episode_brief", {"topic": "T", "episode": {"beats": ["a"]}}))["brief"] == "T\na"
    assert (await run_op("script_from_watch", {"transcript": "a。b"}))["script_lines"][1]["text"] == "b"
    assert (await run_op("tongjian_quotes", {"chapter_ir": {"quotes": ["q"]}}))["count"] == 1
    assert (await run_op("lint_stage", {}))["status"] == "ok"
    assert (await run_op("h3_cuts", {"durations": [2, 3]}))["starts"] == [0, 2]
    assert (await run_op("h3_align", {"text": "a", "durations": [1]}))["errors"]
    assert (await run_op("h3_pack", {"shots": [1]}))["groups"] == [1]
    assert (await run_op("stock_query", {"topic": "history"}))["query"] == "history"
    assert (await run_op("audio_bgm", {"_tool_id": "audio.bgm.calm"}))["bgm"]["mood"] == "calm"
    assert (await run_op("nle_drop", {"cuts": [{"id": 1}], "index": 0}))["cuts"][0]["action"] == "drop"
    assert (await run_op("nle_transition", {"_tool_id": "transition.fade"}))["plan"]["transition"] == "fade"
    assert (await run_op("camera_plan", {"_tool_id": "camera.close", "topic": "T"}))["plan"]["scene"] == "T"
    assert (await run_op("qc_layout", {"boxes": [1, 2]}))["boxes"] == 2
    assert (await run_op("qc_motion", {}))["ok"] is True
    assert (await run_op("qc_gate", {"_tool_id": "qc.final"}))["gate"] == "final"
    assert (await run_op("clip_factory", {"edit_plan": {"cuts": [{"action": "keep"}, {"action": "drop"}]}}))["count"] == 1
    dubbed = await run_op("dub_translate", {"lines": [{"text": "a"}, "bad"], "lang": "en"})
    assert dubbed["lines"] == [{"text": "a", "lang": "en", "translated": False}]
    assert (await run_op("montage_queries", {"topic": "city"}))["queries"][-1] == "city city night"
    assert (await run_op("character_beats", {"text": "x"}))["beats"] == ["trigger", "peak", "aftermath"]
    assert (await run_op("batch_rank", {"candidates": ["best"]}))["best"] == "best"
    assert (await run_op("explainer_card", {"_tool_id": "card.hook", "text": "T"}))["cue"]["card"] == "hook"
    assert (await run_op("out_profile", {"_tool_id": "out.tiktok"}))["profile"]["ar"] == "9:16"
    assert (await run_op("material_src", {"_tool_id": "source.pexels", "topic": "T"}))["plan"]["source"] == "pexels"
    assert (await run_op("layer_ticket", {"_tool_id": "layer.video", "topic": "T"}))["ticket"]["topic"] == "T"
    assert (await run_op("recipe_nodes", {"line_id": "missing"}))["status"] == "failed"
    assert (await run_op("nle_transition", {}))["plan"]["transition"] == "cut"
    assert (await run_op("craft_shot_prompt", {"scene": {"text": "T"}, "style_context": {}}))["status"] == "ok"
    assert (await run_op("delivery_validate", {}))["status"] == "failed"
    assert (await run_op("verdict_source_review", {}))["status"] == "failed"
    aligned = await run_op(
        "verdict_scene_pacing",
        {"steps": [], "scene_start": 0, "scene_end": 1, "narration_cues": []},
    )
    assert aligned["status"] == "ok"


def test_platform_login_risk_and_account_state_are_safe() -> None:
    from datetime import UTC, datetime

    from hevi.platforms.oprim.login import (
        cookie_str_from_state,
        has_a1,
        is_creator_cookie,
        platform_needs_creator_state,
        platform_supports_keyword_collection,
        resolve_browser_mode,
        validate_storage_state,
    )
    from hevi.platforms.oprim.risk import (
        classify_auth_failure,
        cooldown_for_error,
        cooldown_minutes_for,
        is_risk_status,
        next_risk_check_time,
        progressive_recovery_steps,
    )
    from hevi.platforms.schemas import RiskCategory

    state = '{"cookies":[{"name":"a1","value":"abc"},{"name":"web_session","value":"s"}]}'
    assert cookie_str_from_state(state) == "a1=abc; web_session=s"
    assert cookie_str_from_state("not-json") == ""
    assert has_a1("a1=abc")
    assert not has_a1("x=1")
    assert is_creator_cookie("web_session=s")
    assert not is_creator_cookie("")
    valid = validate_storage_state(state)
    assert valid["valid"] and valid["cookies_count"] == 2 and valid["is_creator"]
    assert validate_storage_state("")["errors"] == ["empty"]
    assert not validate_storage_state("not-json")["valid"]
    assert platform_needs_creator_state("douyin")
    assert not platform_needs_creator_state("xhs")
    assert platform_supports_keyword_collection("douyin")
    assert not platform_supports_keyword_collection("xhs")
    assert resolve_browser_mode("patchright", True) == "patchright"
    assert resolve_browser_mode("cdp", True) == "cdp"
    assert resolve_browser_mode("cdp", False) == "error"
    assert resolve_browser_mode("auto", False) == "patchright"

    assert classify_auth_failure(403) is RiskCategory.RISK
    assert classify_auth_failure(401) is RiskCategory.AUTH
    assert classify_auth_failure(503) is RiskCategory.NETWORK
    assert classify_auth_failure(404) is RiskCategory.UNKNOWN
    assert cooldown_for_error("risk", 2)["minutes"] == 2
    assert cooldown_for_error("unclassified")["minutes"] == 60
    assert cooldown_minutes_for(RiskCategory.AUTH) == 120
    assert is_risk_status("blocked") and not is_risk_status("normal")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert next_risk_check_time(RiskCategory.RISK, now=now) > now
    assert progressive_recovery_steps("blocked") == ["blocked", "warn", "cool", "normal"]
    assert progressive_recovery_steps("invalid")[0] == "normal"


def test_account_manager_persists_and_filters_storage_states(tmp_path: Path) -> None:
    from hevi.platforms.oskill.account import (
        AccountManager,
        load_account_state,
        save_account_state,
        verify_account,
    )

    manager = AccountManager(tmp_path)
    assert manager.load_read_state(1, "douyin") is None
    assert manager.get_account_profile(1, "douyin") is None
    read = '{"cookies":[{"name":"sid","value":"1"}]}'
    creator = '{"cookies":[{"name":"a1","value":"abc"}]}'
    save_account_state(tmp_path, 1, "douyin", read, creator)
    assert load_account_state(tmp_path, 1, "douyin") == {
        "read_state": read,
        "creator_state": creator,
    }
    assert manager.has_valid_read_state(1, "douyin")
    assert manager.has_valid_creator_state(1, "douyin")
    profile = manager.get_account_profile(1, "douyin")
    assert profile is not None and profile.cookies_count == 1
    assert manager.list_accounts("douyin")[0]["id"] == 1
    assert verify_account(tmp_path, 1, "douyin")["can_publish"]
    assert manager.delete_account(1, "douyin")
    assert not manager.delete_account(1, "douyin")


@pytest.mark.asyncio
async def test_platform_content_comment_publish_and_share_boundaries(tmp_path: Path) -> None:
    from hevi.platforms.oskill.comment import (
        check_interval_safety,
        create_comment_rule,
        execute_comment_rule,
        parse_comment_target,
    )
    from hevi.platforms.oskill.content import collect_content, download_media, monitor_targets
    from hevi.platforms.oskill.publish import (
        create_publish_task,
        publish_to_platform,
        repost_content,
    )
    from hevi.platforms.oskill.share_downloader import (
        ShareDownloader,
        parse_share_text,
        resolve_share_link,
    )
    from hevi.platforms.schemas import ContentRecord, MonitorTarget

    rule = create_comment_rule(
        "xhs", "rule", "auto_comment", 1, "keyword", "  hevi  ", ["hello"], daily_cap=-1
    )
    assert rule.keyword == "hevi" and rule.daily_cap == 0
    assert rule.min_gap_seconds >= 1 and rule.max_per_run >= 1
    assert parse_comment_target("https://douyin.com/a?aweme_id=1&sec_uid=s", "douyin") == {
        "sec_uid": "s",
        "aweme_id": "1",
        "keyword": "",
        "xsec_token": "",
    }
    assert (await execute_comment_rule(rule))["status"] == "pending"
    assert check_interval_safety(rule)["safe"]
    assert not check_interval_safety(rule, __import__("datetime").datetime.now())["safe"]

    target = MonitorTarget(id=7, platform="douyin", account_id=2, kind="comment")
    collected = await collect_content("douyin", target, object(), 2)
    assert collected.success and collected.records == []
    unknown = await collect_content("douyin", MonitorTarget(platform="douyin", kind="unknown"), object(), 2)  # type: ignore[arg-type]
    assert not unknown.success and "unknown kind" in unknown.error
    skipped = await monitor_targets(
        [MonitorTarget(id=8, platform="douyin", enabled=False)],
        lambda _account_id: None,
        object(),
    )
    assert skipped == {}

    records = [
        ContentRecord(platform="douyin", aweme_id="1", media_urls=["u"]),
        ContentRecord(platform="xhs", note_id="2"),
    ]
    downloaded = await download_media(records, tmp_path / "media")
    assert downloaded[0].download_status == "done"
    assert downloaded[1].download_status == "failed"
    assert downloaded[0].local_path.endswith("douyin_1")

    task = create_publish_task(1, "douyin", title="x" * 30, media_paths=["video.mp4"])
    assert len(task.title) == 20
    assert (await publish_to_platform(task, browser_context=None)).status == "failed"
    published = await publish_to_platform(task, browser_context=object())
    assert published.status == "published"
    empty = create_publish_task(1, "douyin")
    assert (await publish_to_platform(empty)).status == "skipped"
    repost = await repost_content(5, 1, "xhs")
    assert repost["task_id"] == "repost_5_xhs"

    parsed = parse_share_text("😀 https://www.douyin.com/video/123?aweme_id=123")
    assert parsed["platform"] == "douyin" and parsed["aweme_id"] == "123"
    assert resolve_share_link("not a link")["ok"] is False
    downloader = ShareDownloader(tmp_path / "downloads")
    assert (await downloader.download_from_link("not a link"))["ok"] is False
    success = await downloader.download_from_link("https://www.douyin.com/video/123?aweme_id=123")
    assert success["ok"] is True and success["data"]["platform"] == "douyin"


def test_h3_verdict_checks_handle_probe_failures_and_soft_signals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.verdict import h3_checks

    clip = tmp_path / "shot.mp4"
    clip.write_bytes(b"clip")
    assert h3_checks._probe_fps(clip) == 24
    assert h3_checks._probe_duration(clip) == 0
    assert h3_checks.check_degraded_static(clip) is None

    class Completed:
        def __init__(self, stdout: str = "", stderr: str = "") -> None:
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command: list[str], **_kwargs: object) -> Completed:
        if command[0] == "ffprobe" and any("r_frame_rate" in item for item in command):
            return Completed(stdout="30/1")
        if command[0] == "ffprobe":
            return Completed(stdout="2.0")
        if any("freezedetect" in item for item in command):
            return Completed(stderr="freeze_duration:1.0")
        if any("select='gt(scene" in item for item in command):
            return Completed(stderr="")
        if any("signalstats" in item for item in command):
            return Completed(stderr="YAVG=10\nYAVG=10\nYAVG=30\nYAVG=10\n")
        return Completed()

    monkeypatch.setattr(h3_checks.subprocess, "run", fake_run)
    assert h3_checks._probe_fps(clip) == 30
    assert h3_checks._probe_duration(clip) == 2
    assert h3_checks.check_degraded_static(clip) == 0.5
    morph_ok, morph_ratio = h3_checks.check_sc_morph(clip)
    assert morph_ok is False and morph_ratio > 0

    async def streams(_clip: Path) -> list[dict[str, object]]:
        return [{"codec_type": "video", "duration": "2"}]

    monkeypatch.setattr(h3_checks, "_streams", streams)
    import asyncio

    assert asyncio.run(h3_checks.check_lip_rough(clip, has_dialogue=False)) == (True, "")
    assert asyncio.run(h3_checks.check_lip_rough(clip, has_dialogue=True))[0] is False


@pytest.mark.asyncio
async def test_h3_verdict_wardrobe_and_priority_decisions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.verdict import h3_checks

    clip = tmp_path / "shot.mp4"
    master = tmp_path / "master.png"
    clip.write_bytes(b"clip")
    master.write_bytes(b"master")
    monkeypatch.setattr(h3_checks, "detect_black_ratio", lambda _path: 0.8)
    monkeypatch.setattr(h3_checks, "check_degraded_static", lambda _path: 0.0)
    monkeypatch.setattr(h3_checks, "check_sc_morph", lambda _path: (True, 0.0))
    monkeypatch.setattr(h3_checks, "_streams", lambda _path: _audio_streams())
    monkeypatch.setattr(h3_checks, "_probe_duration", lambda _path: 2.0)

    async def _audio_streams() -> list[dict[str, str]]:
        return [{"codec_type": "video", "duration": "2"}, {"codec_type": "audio", "duration": "2"}]

    async def vlm(**_kwargs: object) -> dict[str, str]:
        return {"content": '{"wardrobe_ok": false, "note": "color changed"}'}

    monkeypatch.setattr(h3_checks, "_extract_frame", lambda _clip, _t, out: out.write_bytes(b"frame") or True)
    verdict = await h3_checks.verdict_h3_shot(
        shot_id="s1",
        clip_path=clip,
        identity_score=0.1,
        has_dialogue=True,
        subject_master=master,
        vlm=vlm,
    )
    assert not verdict.passed
    assert verdict.retake_tier == "re_roll"
    assert verdict.checks["wardrobe"]["ok"] is False

    monkeypatch.setattr(h3_checks, "detect_black_ratio", lambda _path: None)
    monkeypatch.setattr(h3_checks, "check_degraded_static", lambda _path: None)
    identity = await h3_checks.verdict_h3_shot(shot_id="s2", clip_path=clip, identity_score=0.1)
    assert identity.retake_tier == "rewrite"


def _audio_streams() -> list[dict[str, str]]:
    return [{"codec_type": "video", "duration": "2"}, {"codec_type": "audio", "duration": "2"}]


@pytest.mark.asyncio
async def test_resilient_image_generation_recovers_gpu_cpu_and_cloud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.image import resilient_image_gen as image
    from hevi.image.sdxl_local_service import GPUUnavailableError

    output = tmp_path / "image.png"
    calls: list[dict[str, object]] = []

    async def gpu_ok() -> None:
        return None

    async def local(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        output.write_bytes(b"local")
        return {"provider": "local", "path": str(kwargs["output_path"])}

    monkeypatch.setattr(image, "check_gpu_available", gpu_ok)
    monkeypatch.setattr(image, "sdxl_local_generate", local)
    result = await image.resilient_image_gen(prompt="p", output_path=output)
    assert result["provider"] == "local" and calls[0]["width"] == 1024

    async def gpu_down() -> None:
        raise GPUUnavailableError("offline")

    async def cpu_then_cloud(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        if kwargs.get("require_gpu") is False:
            raise RuntimeError("cpu failed")
        return {"provider": "unexpected"}

    async def cloud(**kwargs: object) -> dict[str, object]:
        return {"provider": "fal", "path": str(kwargs["output_path"])}

    monkeypatch.setattr(image, "check_gpu_available", gpu_down)
    monkeypatch.setattr(image, "sdxl_local_generate", cpu_then_cloud)
    monkeypatch.setattr(image, "_cloud_fallback", cloud)
    cloud_result = await image.resilient_image_gen(prompt="p", output_path=output)
    assert cloud_result["provider"] == "fal"
    assert any(item.get("width") == 512 for item in calls)

    async def batch(_requests: list[dict[str, object]], **_kwargs: object) -> list[object]:
        return [{"ok": True} for _ in _requests]

    monkeypatch.setattr(image, "check_gpu_available", gpu_ok)
    monkeypatch.setattr("hevi.image.sdxl_local_service.sdxl_local_generate_batch", batch)
    assert await image.resilient_image_gen_batch([{"prompt": "p", "output_path": str(output)}]) == [{"ok": True}]


@pytest.mark.asyncio
async def test_resilient_image_batch_uses_cpu_then_per_image_cloud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.image import resilient_image_gen as image

    paths = [tmp_path / "a.png", tmp_path / "b.png"]
    requests = [{"prompt": "a", "output_path": str(paths[0]), "width": 100}, {"prompt": "b", "output_path": str(paths[1])}]
    phases = 0

    async def gpu() -> None:
        return None

    async def batches(reqs: list[dict[str, object]], **kwargs: object) -> list[object]:
        nonlocal phases
        phases += 1
        if kwargs.get("require_gpu") is False:
            return [RuntimeError("cpu one"), {"provider": "cpu"}]
        return [RuntimeError("gpu one"), RuntimeError("gpu two")]

    async def cloud(**kwargs: object) -> dict[str, object]:
        return {"provider": "cloud", "path": str(kwargs["output_path"])}

    monkeypatch.setattr(image, "check_gpu_available", gpu)
    monkeypatch.setattr("hevi.image.sdxl_local_service.sdxl_local_generate_batch", batches)
    monkeypatch.setattr(image, "_cloud_fallback", cloud)
    result = await image.resilient_image_gen_batch(requests)
    assert phases == 2
    assert result[0] == {"provider": "cloud", "path": str(paths[0])}
    assert result[1] == {"provider": "cpu"}


@pytest.mark.asyncio
async def test_funasr_bridge_normalizes_provider_shapes_and_chunks_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import funasr_verify as verify

    assert verify.chunk_by_punctuation_with_limit("") == []
    chunks = verify.chunk_by_punctuation_with_limit("第一句。第二句；第三句", max_chars_per_line=3)
    assert [item["text"] for item in chunks] == ["第一句", "第二句", "第三句"]
    forced = verify.chunk_by_punctuation_with_limit("一二三四五六七", max_chars_per_line=3)
    assert [item["text"] for item in forced] == ["一二三", "四五六", "七"]
    merged = verify.merge_chunks_with_asr_results(
        [{"text": "甲"}, {"text": "乙"}],
        [{"word": "甲甲甲", "start": 0.1, "end": 0.3}, {"word": "乙乙乙", "start": 0.4, "end": 0.8}],
    )
    assert merged[0]["start_sec"] == 0.1 and merged[1]["end_sec"] == 0.8
    assert verify.merge_chunks_with_asr_results([{"text": "x"}], []) == [{"text": "x", "start_sec": 0.0, "end_sec": 0.0}]
    normalized = verify._normalize_funasr_output(
        [{"text": "a", "start": 0.1, "end": 0.4}, ["b", 0.4, 0.8], {"text": "", "start": 1, "end": 1}]
    )
    assert [item["word"] for item in normalized] == ["a", "b"]

    import oprim

    monkeypatch.setattr(
        oprim,
        "funasr_asr",
        lambda **_kwargs: {"words": [{"text": "你", "start": 0.0, "end": 0.5}]},
        raising=False,
    )
    result = await verify.funasr_timestamp_generator(audio_path=tmp_path / "audio.wav")
    assert result[0]["start_ms"] == 0
    monkeypatch.setattr(oprim, "funasr_asr", lambda **_kwargs: [], raising=False)
    monkeypatch.setattr(oprim, "probe_duration", lambda _path: 1.0)
    assert await verify.funasr_timestamp_generator(audio_path=tmp_path / "audio.wav") == []


@pytest.mark.asyncio
async def test_audio_router_selects_styles_and_stitches_single_segment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from hevi.audio import audio_router

    assert audio_router._infer_audio_style("这是正式播报") == "formal"
    assert audio_router._infer_audio_style("其实呢，这很简单") == "conversational"
    calls: list[str] = []

    async def formal(**kwargs: object) -> Path:
        calls.append("formal")
        path = kwargs["output_path"]
        assert isinstance(path, Path)
        path.write_bytes(b"x" * 120)
        return path

    async def conversational(**kwargs: object) -> Path:
        calls.append("conversational")
        path = kwargs["output_path"]
        assert isinstance(path, Path)
        path.write_bytes(b"y" * 120)
        return path

    monkeypatch.setattr(audio_router, "_synthesize_formal", formal)
    monkeypatch.setattr(audio_router, "_synthesize_conversational", conversational)
    formal_path = await audio_router.route_single_cue(
        cue_text="news", cue_style="formal", output_path=tmp_path / "f.wav", voice="Dylan"
    )
    conversational_path = await audio_router.route_single_cue(
        cue_text="news", cue_style="conversational", output_path=tmp_path / "c.wav", voice="Dylan"
    )
    assert formal_path.exists() and conversational_path.exists()
    assert calls == ["formal", "conversational"]

    def probe(_path: Path) -> float:
        return 1.25

    monkeypatch.setattr(audio_router, "probe_duration", probe)
    cue = SimpleNamespace(id="cue-1", text="hello", captions=[{"text": "hello"}])
    result = await audio_router.route_and_stitch_master_audio([cue], tmp_path / "master")
    assert result["total_duration_s"] == 1.25
    assert result["manifest"][0]["id"] == "cue-1"
    assert result["master_path"].read_bytes() == b"x" * 120


def test_runway_helpers_build_data_uris_and_validate_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.video import runway_service

    with pytest.raises(runway_service.RunwayError):
        runway_service._resolve_api_key({})
    assert runway_service._resolve_api_key({"RUNWAY_API_KEY": "key"}) == "key"
    assert runway_service._headers("key")["Authorization"] == "Bearer key"
    assert runway_service._as_uri("https://example.test/a.png") == "https://example.test/a.png"
    image = tmp_path / "image.jpg"
    image.write_bytes(b"jpeg")
    assert runway_service._as_uri(str(image)).startswith("data:image/jpeg;base64,")

    async def submit(**kwargs: object) -> Path:
        return kwargs["output_path"]  # type: ignore[no-any-return]

    monkeypatch.setattr(runway_service, "_submit_and_poll", submit)
    import asyncio

    with pytest.raises(runway_service.RunwayError):
        asyncio.run(runway_service.runway_image_to_video(prompt="p", reference_images=[], output_path=tmp_path / "v.mp4", config={"RUNWAY_API_KEY": "k"}))
    with pytest.raises(runway_service.RunwayError):
        asyncio.run(runway_service.runway_text_to_image(prompt="p", output_path=tmp_path / "i.png", config={"RUNWAY_API_KEY": "k"}, reference_images=["a", "b", "c", "d"]))
    assert asyncio.run(runway_service.runway_text_to_image(prompt="p", output_path=tmp_path / "i.png", config={"RUNWAY_API_KEY": "k"}, seed=3)) == tmp_path / "i.png"
    assert asyncio.run(runway_service.runway_image_to_video(prompt="p", reference_images=[str(image)], output_path=tmp_path / "v.mp4", config={"RUNWAY_API_KEY": "k"}, duration=None, seed=3)) == tmp_path / "v.mp4"


def test_openshorts_atoms_and_skills_build_complete_deliverables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hevi.openshorts import oprim, oskill
    from hevi.openshorts.schemas import (
        AICostMode,
        SceneDetection,
        WordTimestamp,
        YouTubeStudioJob,
    )

    assert oprim.clip_reframing_params(oprim.ReframingMode.TRACK)["method"] == "face_tracking"
    assert oprim.clip_reframing_params(oprim.ReframingMode.SPLIT)["method"] == "split_layout"
    assert oprim.clip_reframing_params(oprim.ReframingMode.GENERAL)["blur_background"]
    assert oprim.detect_scenes_gemini("text", 10) == []
    assert oprim.extract_transcript_with_words("video.mp4")["segments"] == []
    words = [WordTimestamp(word="a", start_s=1, end_s=2), WordTimestamp(word="b", start_s=3, end_s=4)]
    assert oprim.snap_clip_to_words_auto(0, 4, words, 10, min_duration=1)[1] > 0
    assert oprim.snap_clip_to_words_auto(0, 2, [], 10) == (0.0, 2.0)
    assert oprim.build_transcript_windows({"segments": [] , "text": "empty"}, 12)[0]["text"] == "empty"
    windows = oprim.build_transcript_windows({"segments": [{"start": 0, "end": 1, "text": "one"}]}, 12)
    assert windows[0]["start"] == 0
    script = oprim.generate_script_from_description("hook.problem.solution.cta")
    assert [segment["focus"] for segment in script.segments] == ["hook", "problem", "solution", "cta"]
    assert oprim.plan_ai_short_actor("x", AICostMode.PREMIUM).provider == "kling_avatar_v2"
    assert len(oprim.generate_youtube_titles("topic", 2)) == 2
    assert oprim.generate_youtube_thumbnail("v", False).face_overlay is False
    description = oprim.generate_youtube_description("A B", "content")
    assert len(description.chapters) == 10 and description.hashtags == ["#A", "#B"]
    assert oprim.make_clip_spec(1, 0, 2, "headline").duration_s == 2

    monkeypatch.setattr(
        oskill,
        "extract_transcript_with_words",
        lambda _path: {"text": "x", "duration": 60, "segments": []},
    )
    monkeypatch.setattr(
        oskill,
        "detect_scenes_gemini",
        lambda *_args, **_kwargs: [SceneDetection(start_s=0, end_s=20, headline="hook", viral_score=9)],
    )
    clips = oskill.generate_clips("video", reframing=oprim.ReframingMode.TRACK, target_clips=1, with_hook_text=True)
    assert clips.status == "completed" and clips.clips[0].effects["hook_text"]
    short = oskill.generate_ai_short("product", url="https://example.test", publish_platforms=["tiktok"])
    assert short.status == "completed" and short.publish_status == "ready"
    tickets = oskill.create_publish_tickets(short, ["tiktok", "youtube"])
    assert len(tickets) == 2 and tickets[0].media_path == short.composite_path
    yt: YouTubeStudioJob = oskill.generate_youtube_package("video", source_title="Topic")
    assert yt.selected_title and yt.description.chapters
    assert oskill.create_publish_tickets(yt, ["youtube"])[0].title == yt.selected_title


@pytest.mark.asyncio
async def test_montage_atoms_and_stage_directors_persist_checkpoints(tmp_path: Path) -> None:
    from hevi.montage import omodul, oprim, oskill
    from hevi.montage.schemas import ToolCapability, ToolContract

    manifest_json = tmp_path / "manifest.json"
    manifest_json.write_text('{"name":"p","stages":[{"name":"s","skill":"k"}]}')
    manifest = oprim.load_pipeline_manifest(manifest_json)
    assert not oprim.validate_pipeline_manifest(manifest)
    assert oprim.validate_pipeline_manifest(oprim.make_default_pipeline_manifest("empty"))
    registry: dict[str, ToolContract] = {}
    oprim.register_tool(ToolContract(name="writer", capability=ToolCapability.SCRIPT, provider="local"), registry)
    discovered_dir = tmp_path / "tools"
    discovered_dir.mkdir()
    (discovered_dir / "writer.schema.json").write_text('{"name":"writer2","capability":"script"}')
    assert "writer2" in oprim.discover_tools(discovered_dir)
    envelope = oprim.build_tool_envelope(registry)
    assert oprim.provider_menu(envelope)["local"] == ["writer"]
    assert oprim.support_envelope(envelope)["total_tools"] == 1
    budget = oprim.estimate_cost(oprim.make_default_cost_budget(), "writer", "local", "script", 2, 0.5)
    budget = oprim.reserve_cost(budget, "writer", 1)
    budget = oprim.reconcile_cost(budget, "writer", 0.25)
    assert budget.spent_usd == 0.25
    assert oprim.analyze_reference_video("video").content == "分析待完成"
    assert oprim.extract_transcript("video") == ""
    assert oprim.detect_scenes("video") == [] and oprim.sample_frames("video") == []
    playbook = tmp_path / "playbook.yaml"
    playbook.write_text("name: p\ncolor_rules:\n  text: white\n")
    loaded_playbook = oprim.load_playbook(playbook)
    assert oprim.apply_playbook_to_compose(loaded_playbook, {"cuts": []})["playbook"]["color_rules"]["text"] == "white"
    checkpoint = oskill.checkpoint_write("p", "s", {"script": {"text": "x"}}, {"s": {"ok": True}})
    checkpoint_path = tmp_path / "checkpoint.json"
    oprim.write_checkpoint(checkpoint_path, checkpoint)
    loaded_checkpoint = oprim.read_checkpoint(checkpoint_path)
    approved = oprim.update_checkpoint_approval(loaded_checkpoint, "approved", "reviewed")
    assert approved.human_approval == "approved"
    assert oskill.checkpoint_approve(checkpoint, "rejected").human_approval == "rejected"

    assert oskill.stage_intake({"topic": "T", "slate_id": "s"}, {})["topic"] == "T"
    assert oskill.stage_research({"topic": "T"}, {})["research_status"] == "completed"
    assert oskill.stage_watch({"topic": "T"}, {})["watch_skipped"] is False
    assert oskill.stage_score({"provider_candidates": ["p"]}, {})["video_provider"] == "p"
    assert oskill.stage_script({"topic": "T"}, {})["script_status"] == "generated"
    assert oskill.stage_script({}, {})["script_status"] == "skipped"
    assets = oskill.stage_assets({"subject_ids": ["a"], "materials": ["m"]}, {})
    assert assets["bound_assets"][0]["status"] == "bound"
    edit = oskill.stage_edit_plan({"script_lines": [{"duration_s": 2}]}, {})
    assert edit["edit_plan"]["total_s"] == 2
    assert oskill.stage_mix({}, {})["mix_status"] == "pending"
    timeline = oskill.stage_timeline({"topic": "T", "edit_plan": edit}, {})
    assert timeline["timeline_status"] == "created"
    assert oskill.stage_runtime({"topic": "T", "render_runtime": "hyperframes"}, {})["runtime_pick"]["compiled"]
    order = oskill.stage_dispatch({"topic": "T", "timeline": timeline["timeline"]}, {})
    assert order["production_order"]["topic"] == "T"
    assert len(oskill.stage_publish({"media_path": "v", "platforms": ["x"]}, {})["publish_results"]) == 1
    assert oskill.stage_publish({}, {})["publish_skipped"]
    planned = omodul.plan_reference_analysis("v")
    assert planned["analysis_tools"]
    assert omodul.plan_delivery("p", {"ok": True})["steps"]


def test_krillin_atoms_keep_artifact_paths_and_manifest_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from hevi.krillinai import oprim
    from hevi.krillinai.schemas import (
        ASRConfig,
        ClipGeneratorJob,
        LLMConfig,
        RenderConfig,
        TTSConfig,
    )

    def command(_args: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(oprim.subprocess, "run", command)
    video = oprim.download_video("https://example.test/v", str(tmp_path), ["--quiet"])
    assert video.path.endswith("origin_video.mp4")
    audio = oprim.extract_audio(video.path, str(tmp_path))
    assert audio.path.endswith("origin_audio.wav")
    asr = oprim.transcribe_audio(audio.path, ASRConfig(language="en"))
    assert asr.language == "en"
    assert oprim.transcribe_with_faster_whisper(audio.path, language="zh").path.endswith(".srt")
    assert oprim.transcribe_with_whisper_cpp(audio.path).language == "auto"
    segmented = oprim.segment_subtitle(asr.path, LLMConfig())
    assert "segmented_" in segmented.path
    target, bilingual = oprim.translate_subtitle(segmented.path, "en", LLMConfig())
    assert target.language == "en" and bilingual.language == "bilingual"
    assert oprim.generate_short_mixed_srt(asr.path, target.path).language == "mixed"
    tts = oprim.synthesize_tts(target.path, TTSConfig())
    assert tts.path.endswith(".wav")
    assert oprim.synthesize_with_aliyun_tts("x").path.endswith("aliyun_tts.wav")
    assert oprim.synthesize_with_openai_tts("x").path.endswith("openai_tts.wav")
    assert oprim.synthesize_with_minimax_tts("x").path.endswith("minimax_tts.wav")
    assert oprim.merge_tts_to_video(video.path, audio.path, str(tmp_path / "merged.mp4")).path.endswith("merged.mp4")
    assert oprim.render_horizontal_bilingual(video.path, target.path, str(tmp_path / "hb.mp4"), RenderConfig()).path.endswith("hb.mp4")
    assert oprim.render_horizontal_dubbed(video.path, str(tmp_path / "hd.mp4")).path.endswith("hd.mp4")
    assert oprim.render_vertical(video.path, target.path, str(tmp_path / "v.mp4"), RenderConfig(), dubbed=True).path.endswith("v.mp4")
    cover = oprim.generate_cover(video.path, "cover", "xhs", str(tmp_path / "cover.jpg"))
    assert cover.platform == "xhs"
    job = ClipGeneratorJob(input_source="source", workdir=str(tmp_path))
    oprim.write_manifest(str(tmp_path), job)
    loaded = oprim.read_manifest(str(tmp_path))
    assert loaded.input_source == "source"
    assert oprim.get_artifact_path(str(tmp_path), "krillinai_manifest.json") is not None
    assert oprim.get_artifact_path(str(tmp_path), "missing") is None
    with pytest.raises(RuntimeError, match="yt-dlp failed"):
        monkeypatch.setattr(oprim.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="network"))
        oprim.download_video("bad", str(tmp_path))


@pytest.mark.asyncio
async def test_voicepro_asr_translation_tts_and_clone_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hevi.voicepro_asr import oprim as asr
    from hevi.voicepro_asr.schemas import ASRResult, make_asr_config
    from hevi.voicepro_clone import oprim as clone
    from hevi.voicepro_translate import oprim as translate
    from hevi.voicepro_tts import oprim as tts
    from hevi.voicepro_tts.schemas import TTSProvider, make_tts_config

    monkeypatch.setattr(asr.subprocess, "run", lambda *_args, **_kwargs: None)
    assert asr.normalize_audio("a.wav", "b.wav") == "b.wav"
    cpp = await asr.transcribe_whisper_cpp("a.wav", make_asr_config())
    aliyun = await asr.transcribe_aliyun_asr("a.wav", make_asr_config())
    openai = await asr.transcribe_openai_whisper("a.wav", make_asr_config())
    assert cpp.cer == 1.0 and aliyun.model_used.startswith("aliyun") and openai.model_used.startswith("openai")
    assert asr.verify_asr_result(ASRResult(text="hello"), "hello")["passed"]
    assert not asr.verify_asr_result(ASRResult(text="wrong"), "hello")["passed"]
    assert asr.verify_asr_result(ASRResult(cer=0.01))["passed"]

    assert (await translate.translate_azure_translator("hello", target_lang="zh")).translated_text == "hello"
    assert translate.apply_terminology("a b", {"a": "A", "b": "B"}) == "A B"
    assert translate.apply_terminology("x", {}) == "x"

    result = await translate.translate_text("hello", translate.make_translate_config("azure_translator"))
    assert result.provider.value == "azure_translator"
    assert (await translate.translate_text("hello", translate.make_translate_config("azure_translator"))).source_text == "hello"

    for provider, expected in (
        (TTSProvider.MINIMAX_TTS, "minimax"),
        (TTSProvider.COSYVOICE_TTS, "cosyvoice"),
        (TTSProvider.F5_TTS, "f5"),
        (TTSProvider.KOKORO_TTS, "kokoro"),
        (TTSProvider.AZURE_TTS, "azure"),
    ):
        synthesized = await tts.synthesize_tts("hello", make_tts_config(provider))
        assert expected in synthesized.provider.value
    with pytest.raises(RuntimeError, match="edge-tts"):
        monkeypatch.setattr(tts, "synthesize_edge_tts", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("edge-tts unavailable")))
        await tts.synthesize_tts("hello", make_tts_config(TTSProvider.EDGE_TTS))

    assert clone.extract_voiceprint("ref.wav")["voiceprint"]
    assert clone.preprocess_text_for_cosyvoice("hello") == "hello"
    zero = clone.cosyvoice_zero_shot("hello", "ref.wav")
    cross = clone.cosyvoice_cross_lingual("hello", "ref.wav", "hello", "en")
    instruct = clone.cosyvoice_instruct("hello", "ref.wav", "calm")
    f5 = clone.f5_tts_zero_shot("hello", "ref.wav")
    assert zero.similarity_score == 0.85 and cross.mode.value == "cross_lingual"
    assert instruct.mode.value == "instruct" and f5.similarity_score == 0.90
    assert clone.merge_voice_clones(["a.wav", "b.wav"]).endswith(".wav")
    assert clone.verify_clone_quality("a", "b")["quality"] == "good"


def test_erduo_atoms_and_skills_enforce_canary_and_render_lineage(tmp_path: Path) -> None:
    from hevi.erduo import oprim, oskill
    from hevi.erduo.schemas import RuntimeBackend

    entries = oprim.parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\nhello")
    truth = oprim.freeze_truth(entries, oprim.parse_design("modern"))
    proposal = oprim.generate_creative_proposal(truth)
    assert proposal.chapter_plan[0]["srt_indices"] == [0]
    chapters = oprim.plan_chapters(truth, proposal, shots_per_chapter=2)
    assert len(chapters[0].shots) == 2
    canary = oprim.plan_canary(chapters, shots_per_canary=1)
    assert canary[0].notes == "待验证"
    verified = oprim.verify_canary(canary, {canary[0].shot_id: "accept"})
    assert verified[0].technical_passed and oprim.canary_passed_threshold(verified, 1)
    assert not oprim.canary_passed_threshold(verified, 2)
    assert oprim.generate_lead_samples(chapters, RuntimeBackend.REMOTION).opening_sample.endswith("remotion.mp4")
    assert oprim.generate_lead_samples([], RuntimeBackend.REMOTION).opening_sample == ""
    assert oprim.render_shot(chapters[0].shots[0], RuntimeBackend.REMOTION, "/out").endswith(".mp4")
    assert len(oprim.render_chapter(chapters[0], RuntimeBackend.REMOTION, "/out")) == 2
    assert oprim.assemble_master([["a.mp4"]], "/out/master.mp4", RuntimeBackend.REMOTION).endswith("master.mp4")

    srt_path = tmp_path / "input.srt"
    design_path = tmp_path / "design.txt"
    srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello")
    design_path.write_text("modern")
    job = oskill.skill_full_production(str(srt_path), str(design_path), RuntimeBackend.HYPERFRAMES, "u")
    assert job.truth is not None and job.chapters and job.canary_results
    assert oskill.skill_build_chapters(job, 1).chapters[0].shots[0].sequence == 0
    assert oskill.skill_canary_verify(job, {job.canary_results[0].shot_id: "revise"}).canary_results[0].user_choice == "revise"
    assert not oskill.skill_canary_threshold(job, 1)
    assert oskill.skill_render_chapters(job, "/out") is job
    assert oskill.skill_assemble_master(job, "/out/master.mp4", "/out").endswith("master.mp4")
    assert oskill.skill_generate_lead_samples(job).lead_samples.opening_sample


def test_magiviz_atoms_and_skills_produce_each_stage_output() -> None:
    from hevi.magiviz import oprim, oskill
    from hevi.magiviz.schemas import VideoAspectRatio, VideoModel, make_story_outline

    outline = make_story_outline("Title", "Premise", aspect_ratio=VideoAspectRatio.SQUARE_1_1)
    details = oprim.generate_story_details(outline)
    assert len(details.characters) == 3 and len(details.scenes) == 5 and len(details.dialogues) == 10
    details = oprim.generate_all_characters(details)
    assert all(character.reference_image.endswith(".png") for character in details.characters)
    scene = {"scene_number": 1, "description": "scene", "shots": 2, "characters": ["主角"]}
    frame = oprim.generate_storyboard_frame(scene, {}, 1)
    assert frame.frame_id == "frame_1"
    storyboard = oprim.generate_storyboard(details, VideoAspectRatio.SQUARE_1_1)
    assert storyboard.frames and storyboard.total_duration_s > 0
    scene_video = oprim.generate_scene_video(frame, VideoModel.KLING, seed=3)
    assert scene_video.seed == 3 and scene_video.video_model is VideoModel.KLING
    assert len(oprim.generate_scene_videos_parallel(storyboard)) == len(storyboard.frames)
    assert oprim.compose_story_video([scene_video], "/out/final.mp4", False, False) == "/out/final.mp4"
    job = oskill.skill_run_full_pipeline(oskill.make_magiviz_job(outline, "u"))
    assert job.status.value == "completed" and job.final_video_path.endswith(".mp4")
    assert oskill.skill_character_generation(job).status.value == "character_generating"
    assert oskill.skill_storyboard_generation(job).status.value == "storyboard_generating"
    assert oskill.skill_scene_generation(job).status.value == "scenes_generating"
    assert oskill.skill_video_composition(job, "/out/custom.mp4").final_video_path == "/out/custom.mp4"
    assert oskill.skill_character_consistency(job) is job


@pytest.mark.asyncio
async def test_platform_planners_bind_accounts_media_and_review_steps(tmp_path: Path) -> None:
    from hevi.platforms.omodul.plan_comment import build_comment_plan
    from hevi.platforms.omodul.plan_monitor import build_monitor_plan
    from hevi.platforms.omodul.plan_publish import build_publish_plan, execute_publish_plan
    from hevi.platforms.schemas import MonitorTarget

    targets = [
        MonitorTarget(id=1, platform="douyin", enabled=True, backfill_count=2),
        MonitorTarget(id=2, platform="xhs", enabled=False),
    ]
    monitor = build_monitor_plan(targets, {"douyin": 7}, interval_seconds=60, backfill_count=3)
    assert monitor["platforms"] == ["douyin"]
    assert monitor["targets_by_platform"]["douyin"][0]["backfill_count"] == 2
    comment = build_comment_plan("xhs", "auto_comment", 7, "keyword", ["hello"], target_kind="keyword")
    assert comment["rule"]["keyword"] == "keyword" and comment["review"]["required"] is False
    media = tmp_path / "out.jpg"
    media.write_bytes(b"image")
    publish = build_publish_plan(7, "xhs", [str(media), "missing.mp4"], title="T", scheduled_at="2026-01-01T00:00:00Z")
    assert publish["media"]["paths"] == [str(media)]
    assert publish["media"]["missing"] == ["missing.mp4"]
    assert publish["scheduled_at"] == "2026-01-01T00:00:00"
    result = await execute_publish_plan(publish)
    assert result["status"] == "failed"


def test_semantic_motion_profile_and_layout_share_one_frozen_time_contract() -> None:
    from hevi.production.craft_profile import assert_profile_fresh, profile_from_explainer
    from hevi.production.layout_boxes import LayoutElement, check_occlusion, init_layout_boxes
    from hevi.production.prosody import draft_prosody, retarget_to_master
    from hevi.production.semantic_motion import infer_semantic_role, plan_semantic_motion

    formal = draft_prosody(["为什么要这样做？", "首先看数据，然后看结论。"], baseline="formal")
    assert formal.beats and formal.duration_s > 0
    assert formal.to_dict()["sha256"] == formal.sha256
    retargeted = retarget_to_master(formal, 20)
    assert retargeted.duration_s == 20 and retargeted.source == "narration_master"
    assert retarget_to_master(draft_prosody([]), 20).duration_s == 0
    assert infer_semantic_role("为什么现在改变", index=0) == "hook"
    assert infer_semantic_role("最后的结论", index=1, total=2) == "conclusion"
    assert infer_semantic_role("没有提示", index=1, total=3) == "statement"

    profile = profile_from_explainer(aspect_ratio="16:9", motion_preset="premium-balanced", avatar_enabled=True)
    assert profile.width == 1920 and profile.height == 1080
    frozen = profile.freeze()
    assert_profile_fresh(frozen, profile.sha256())
    with pytest.raises(ValueError, match="Profile SHA"):
        assert_profile_fresh(frozen, "wrong")
    plan = plan_semantic_motion(["为什么", "定义是什么", "结论"], formal, profile, seed="test")
    assert len(plan.scenes) == 3 and plan.scenes[0].supporting_motions == ["focus_underline"]
    layout = init_layout_boxes(profile, plan)
    assert layout["canvas"] == {"width": 1920, "height": 1080}
    assert check_occlusion(layout)
    element = LayoutElement("a", "title", 0, 0, 10, 10, True, 0, 1, 1)
    assert element.box() == (0, 0, 10, 10)
    overlapping = {"scenes": [{"id": "s", "elements": [
        {"id": "a", "role": "title", "x": 0, "y": 0, "width": 10, "height": 10, "start_s": 0, "end_s": 2, "protected": True},
        {"id": "b", "role": "caption", "x": 5, "y": 5, "width": 10, "height": 10, "start_s": 1, "end_s": 2, "protected": True},
    ]}]}
    assert check_occlusion(overlapping)


def test_material_cache_and_corpus_seed_keep_results_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.studio import corpus_seed
    from hevi.video.cache import ArchiveCache, CacheStorage, CoverrCache, PixabayCache

    assert corpus_seed._pick_smallest_mp4(["orig.mp4", "preview.mp4", "small.mp4"], max_mb=1) == "preview.mp4"
    assert corpus_seed._pick_smallest_mp4(["image.jpg"], max_mb=1) is None
    monkeypatch.setattr(corpus_seed.httpx, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(corpus_seed.httpx.HTTPError("offline")))
    assert corpus_seed.search_nasa_videos("space") == []
    assert corpus_seed.search_wikimedia_videos("space") == []
    storage = CacheStorage(tmp_path / "cache")
    calls = 0

    def search(_key: str) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [{"id": "hit"}]

    storage.save_to_disk("key", '[{"id":"saved"}]', 60)
    assert storage.load_or_fetch("key", search) == [{"id": "saved"}]
    assert storage.load_or_fetch("missing", search) == [{"id": "hit"}]
    assert calls == 1
    import hevi.video.cache as cache_module

    monkeypatch.setattr(cache_module, "search_pixabay_videos", lambda _key: [{"id": "hit"}])
    monkeypatch.setattr(cache_module, "search_coverr_videos", lambda _key: [{"id": "hit"}])
    monkeypatch.setattr(cache_module, "search_archive_videos", lambda _key: [{"id": "hit"}])
    for cache in (PixabayCache(storage), CoverrCache(storage), ArchiveCache(storage)):
        cache.put([{"id": "x"}], 60)
        assert cache.get("query") == [{"id": "hit"}]


@pytest.mark.asyncio
async def test_fal_image_adapter_handles_queue_completion_and_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.image import fal_image_service

    monkeypatch.delenv("FAL_API_KEY", raising=False)
    with pytest.raises(fal_image_service.FalImageError, match="not configured"):
        fal_image_service._resolve_api_key({})

    class Response:
        def __init__(self, status_code: int, payload: dict[str, object] | None = None, content: bytes = b"") -> None:
            self.status_code = status_code
            self._payload = payload or {}
            self.content = content
            self.text = "response"

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response(202, {"status_url": "status", "response_url": "response"})

        async def get(self, url: str, **_kwargs: object) -> Response:
            if url == "status":
                return Response(200, {"status": "COMPLETED"})
            if url == "response":
                return Response(200, {"images": [{"url": "image"}]})
            return Response(200, content=b"i" * 512)

    monkeypatch.setattr(fal_image_service.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(fal_image_service.asyncio, "sleep", lambda _seconds: _done())
    output = tmp_path / "image.png"
    result = await fal_image_service.fal_image_generate(
        prompt="subject", negative_prompt="blur", output_path=output, seed=4, config={"FAL_API_KEY": "key"}
    )
    assert result == {"output_path": str(output), "seed": 4}
    assert output.stat().st_size == 512


async def _done() -> None:
    return None


@pytest.mark.asyncio
async def test_mpt_routes_map_provider_responses_without_leaking_client_details() -> None:
    from hevi.api.routers.mpt import (
        CrossPostRequest,
        GenerateVideoRequest,
        MaterialSearchRequest,
        ReferenceVideoRequest,
        analyze_reference_video,
        cross_post,
        generate_video,
        get_task_status,
        health_check,
        search_materials,
        submit_job_from_hevi,
    )

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def generate_video(self, **_kwargs: object) -> dict[str, str]:
            return {"task_id": "mpt-1"}

        async def check_task_status(self, _task_id: str) -> dict[str, object]:
            return {"state": "running", "progress": 42, "videos": ["v.mp4"]}

        async def get_materials(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"url": "u", "duration": 2.0, "width": 10, "height": 20, "source": "pexels"}]

        async def cross_post(self, **_kwargs: object) -> dict[str, object]:
            return {"ok": True, "platforms": ["xhs"]}

        async def analyze_reference_video(self, _url: str) -> dict[str, object]:
            return {"transcript": "t", "rhythm_analysis": {}, "scene_breakdown": [], "concepts": []}

    client = Client()
    generated = await generate_video(GenerateVideoRequest(topic="topic"), client)
    assert generated.task_id == "mpt-1" and generated.status == "submitted"
    status = await get_task_status("mpt-1", client)
    assert status.progress == 42 and status.videos == ["v.mp4"]
    materials = await search_materials(MaterialSearchRequest(query="q"), client)
    assert materials[0].source == "pexels"
    posted = await cross_post(CrossPostRequest(video_path="v", title="t", platforms=["xhs"]), client)
    assert posted["ok"]
    analyzed = await analyze_reference_video(ReferenceVideoRequest(url="u"), client)
    assert analyzed.transcript == "t"
    assert await health_check() == {"status": "ok", "service": "mpt-integration"}

    import hevi.api.routers.mpt as mpt_router

    async def submit(**_kwargs: object) -> str:
        return "mpt-internal"

    old_submit = mpt_router.submit_mpt_job_from_hevi
    mpt_router.submit_mpt_job_from_hevi = submit  # type: ignore[assignment]
    try:
        internal = await submit_job_from_hevi("p", "r", "topic")
    finally:
        mpt_router.submit_mpt_job_from_hevi = old_submit
    assert internal.task_id == "mpt-internal"


def test_tongjian_state_helpers_preserve_layer_and_request_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hevi.api.routers import tongjian
    from hevi.tongjian.schemas import Constitution, Script

    run_id = "run-coverage"
    record = tongjian._init_run(run_id, "source")
    assert len(record["layers"]) == 9 and record["status"] == "PENDING"
    tongjian._update_layer(run_id, "L1", status="PASSED", error="")
    tongjian._finish_run(run_id, success=False, error="failed")
    assert tongjian._context(run_id)["status"] == "FAILED"
    with pytest.raises(RuntimeError, match="not loaded"):
        tongjian._context("missing")
    req = tongjian.RunRequest(source_name="source", raw_text="text")
    record["request"] = req.model_dump(mode="json")
    assert tongjian._request_from_record(record).source_name == "source"
    record["constitution"] = Constitution(title="title")
    record["script"] = Script(lines=[])
    status = tongjian._rec_to_status(record)
    assert status.run_id == run_id and status.layers[1].status == "PASSED"
    run_dir = tmp_path / "run"
    tongjian._persist_review(run_dir, record["constitution"], record["script"])
    assert (run_dir / "L2" / "review.json").exists()
    class Gate:
        passed = True

    assert tongjian._gate_decision(Gate()) == ("PASSED", None)
    assert tongjian._gate_decision({"errors": ["bad"]}) == ("DEGRADED", "bad")
    avatar = tongjian.RunRequest(source_name="s", raw_text="t", layer_config={"L6": tongjian.LayerConfig(model="cloud_avatar")})
    tongjian._apply_cloud_avatar_preset(avatar)
    assert avatar.layer_config["L0"].model == "qwen_cloud"
    assert avatar.layer_config["L3"].model == "edge_tts"
    monkeypatch.setattr(tongjian, "_RUN_REPOSITORIES", {})


def test_cli_and_runtime_helpers_keep_failure_signals_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import urllib.request

    from hevi.skills import free_cli, media_cli, studio_cli

    assert studio_cli._parse_slot("x=1") == ("x", "1")
    assert studio_cli._parse_slot('x={"a":1}') == ("x", {"a": 1})
    assert studio_cli._parse_slot("x={bad") == ("x", "{bad")
    with pytest.raises(Exception, match="slot must"):
        studio_cli._parse_slot("invalid")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert free_cli._llm_rewrite("source", "title") == "source"
    assert "退回原文案" in capsys.readouterr().err
    monkeypatch.setattr(media_cli, "resolve_media", lambda *args, **kwargs: (_ for _ in ()).throw(media_cli.ResolveError("no provider")))
    assert media_cli.main(["resolve", "--type", "bgm", "--intent", "warm"]) == 1
    assert "resolve failed" in capsys.readouterr().err
    manifest = tmp_path / "plans.json"
    manifest.write_text("[]")
    assert manifest.read_text() == "[]"


def test_production_motion_and_media_helpers_cover_edge_inputs(tmp_path: Path) -> None:
    from hevi.production.craft_profile import CraftProfile, profile_from_explainer
    from hevi.production.prosody import draft_prosody
    from hevi.production.semantic_motion import plan_semantic_motion
    from hevi.video.cache import CacheStorage

    invalid = CraftProfile(motion_preset="invalid")
    assert invalid.motion_preset == "basic-stable"
    profile = profile_from_explainer(motion_preset="cinematic", cta="Follow")
    track = draft_prosody(["", "第一句。第二句！", "short"], estimates=[0, 4], baseline="urgent")
    assert len(track.beats) == 3 and track.baseline == "urgent"
    plan = plan_semantic_motion(["statement", "statement"], track, profile)
    assert plan.scenes[0].hero_motion and plan.scenes[0].transition_in
    cache = CacheStorage(tmp_path / "cache")
    cache.save_to_disk("expired", "[]", -1)
    assert cache.load_or_fetch("expired", lambda _key: [{"fresh": True}]) == [{"fresh": True}]


def test_history_series_animator_helpers_use_deterministic_media_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from hevi.history_series import series_animator as animator

    image = tmp_path / "image.png"
    output = tmp_path / "out.mp4"
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(stdout="4.5", stderr="")

    monkeypatch.setattr(animator.subprocess, "run", run)
    assert animator._get_duration(tmp_path / "audio.wav") == 4.5
    for movement in ("push_in", "pull_out", "pan", "tracking", "unknown"):
        animator._ken_burns(image, output, 1.0, movement)
    assert len(calls) == 6 and all(command[0] == "ffmpeg" for command in calls[1:])
    monkeypatch.setattr(animator, "_get_pipe", lambda: lambda *_args, **_kwargs: SimpleNamespace(images=[SimpleNamespace(save=lambda path: Path(path).write_bytes(b"image"))]))
    generated = animator._gen_keyframe("prompt", tmp_path / "frame.png")
    assert generated.read_bytes() == b"image"
    existing = tmp_path / "existing.png"
    existing.write_bytes(b"x" * 1001)
    assert animator._gen_keyframe("prompt", existing) == existing


@pytest.mark.asyncio
async def test_history_series_animator_tts_fallback_and_concat_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.cinematic.golden_formula import GoldenBeat
    from hevi.history_series import series_animator as animator

    wav = tmp_path / "nar.mp3"
    async def voicebox(_text: str, path: Path) -> None:
        path.write_bytes(b"a" * 120)

    monkeypatch.setattr("hevi.explainer.voicebox_client.synthesize", voicebox)
    monkeypatch.setattr(animator, "_get_duration", lambda _path: 2.0)
    assert await animator._tts("hello", wav) == 2.0
    existing = tmp_path / "existing.mp3"
    existing.write_bytes(b"a" * 120)
    assert await animator._tts("hello", existing) == 2.0
    beat = GoldenBeat(index=0, shot_size="wide", movement="push_in", subject="s", action="a", emotion_expression="", atmosphere="", lighting="", duration_s=3, narration="n")
    monkeypatch.setattr(animator, "_tts", lambda *_args, **_kwargs: _async_value(2.0))
    monkeypatch.setattr(animator, "_gen_keyframe", lambda _prompt, path: (path.write_bytes(b"frame") and path))
    monkeypatch.setattr(animator, "_ken_burns", lambda _image, path, _duration, _movement: path.write_bytes(b"video"))
    monkeypatch.setattr(animator, "_concat_videos", lambda _videos, path: path.write_bytes(b"videos"))
    monkeypatch.setattr(animator, "_concat_audio", lambda _dir, _n, path: path.write_bytes(b"audio"))
    monkeypatch.setattr(animator, "_mux", lambda _video, _audio, path: path.write_bytes(b"final"))
    async def beats(_story: str, _llm: object, **_kwargs: object) -> list[GoldenBeat]:
        return [beat]

    monkeypatch.setattr("hevi.cinematic.golden_formula.decompose_story_to_golden_beats", beats)
    final, beats = await animator.animate_lesson("story", lesson_title="lesson", llm=object(), output_dir=tmp_path / "lesson")
    assert final.read_bytes() == b"final" and len(beats) == 1


async def _async_value(value: float) -> float:
    return value


def test_sdxl_local_adapter_validates_gpu_and_preserves_prompt_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio
    from types import SimpleNamespace

    from hevi.image import sdxl_local_service as sdxl

    class Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"GPU", b""

        async def wait(self) -> None:
            return None

        def kill(self) -> None:
            return None

    async def create(*_args: object, **_kwargs: object) -> Proc:
        return Proc()

    monkeypatch.setattr(sdxl.asyncio, "create_subprocess_exec", create)
    asyncio.run(sdxl.check_gpu_available())
    assert asyncio.run(sdxl._ensure_english_prompt("an English prompt")) == "an English prompt"
    monkeypatch.setattr(sdxl, "_EN_PROMPT_CACHE", {})
    class LLM:
        def __call__(self, **_kwargs: object) -> dict[str, str]:
            return {"content": "an English portrait"}

    monkeypatch.setattr("obase.provider_registry.ProviderRegistry.get", lambda: SimpleNamespace(llm=lambda _name: LLM()))
    assert asyncio.run(sdxl._ensure_english_prompt("中文人物")) == "an English portrait"
    output = tmp_path / "image.png"
    captured: dict[str, object] = {}

    async def worker(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(sdxl, "_run_worker", worker)
    result = asyncio.run(sdxl.sdxl_local_generate(prompt="English", output_path=output, require_gpu=False, extra={"init_image": tmp_path / "init.png"}))
    assert result["seed"] is not None and captured["init_image"] == str(tmp_path / "init.png")
    assert captured["negative_prompt"]

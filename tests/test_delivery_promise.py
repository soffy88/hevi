"""delivery_promise 测试 —— 提案侧交付承诺分类 + 切点合规前门。

覆盖: 管线→承诺映射 / 用户意图覆盖 / validate_cuts 运动比与静帧降级拦截。
"""

from __future__ import annotations

from hevi.production.delivery_promise import (
    PromiseType,
    classify_from_brief,
)


def test_classify_cinematic_is_motion_led() -> None:
    promise = classify_from_brief("cinematic", {})
    assert promise.promise_type == PromiseType.MOTION_LED
    assert promise.motion_required is True


def test_classify_animated_explainer_is_data() -> None:
    promise = classify_from_brief("animated-explainer", {})
    assert promise.promise_type == PromiseType.DATA_EXPLAINER
    assert promise.motion_required is False


def test_classify_avatar_presenter() -> None:
    promise = classify_from_brief("talking-head", {})
    assert promise.promise_type == PromiseType.AVATAR_PRESENTER
    assert promise.motion_required is True


def test_classify_user_intent_downgrades_motion() -> None:
    promise = classify_from_brief("cinematic", {"motion_required": False})
    assert promise.promise_type == PromiseType.HYBRID
    assert promise.motion_required is False


def test_classify_has_footage_promotes_source_led() -> None:
    promise = classify_from_brief("cinematic", {"has_footage": True})
    assert promise.promise_type == PromiseType.SOURCE_LED
    assert promise.source_required is True


def test_unknown_pipeline_defaults_hybrid() -> None:
    promise = classify_from_brief("weird-pipeline", {})
    assert promise.promise_type == PromiseType.HYBRID


def test_validate_cuts_motion_led_pass() -> None:
    promise = classify_from_brief("cinematic", {})
    cuts = [
        {"source": "clip_1.mp4", "type": "video"},
        {"source": "clip_2.mp4", "type": "video"},
        {"source": "clip_3.mp4", "type": "video"},
    ]
    verdict = promise.validate_cuts(cuts)
    assert verdict["valid"] is True
    assert verdict["motion_ratio"] == 1.0


def test_validate_cuts_motion_led_blocks_still_fallback() -> None:
    promise = classify_from_brief("cinematic", {})
    cuts = [
        {"source": "shot_a.png", "type": "still"},
        {"source": "shot_b.png", "type": "still"},
        {"source": "card_1.png", "type": "text_card"},  # 幻灯片语法不算 motion
        {"source": "clip_1.mp4", "type": "video"},
    ]
    verdict = promise.validate_cuts(cuts)
    assert verdict["valid"] is False
    assert verdict["motion_ratio"] == 0.25
    assert any("运动比" in v for v in verdict["violations"])


def test_validate_cuts_approved_still_led_fallback() -> None:
    promise = classify_from_brief("cinematic", {})
    promise.approved_fallback = "still_led"
    cuts = [
        {"source": "shot_a.png", "type": "still"},
        {"source": "shot_b.png", "type": "still"},
        {"source": "card_1.png", "type": "text_card"},
    ]
    verdict = promise.validate_cuts(cuts)
    # 仍低于 motion 下限 → invalid; 但无静帧降级违规(已批准)
    assert verdict["valid"] is False
    assert not any("不允许静帧降级" in v for v in verdict["violations"])


def test_validate_cuts_empty() -> None:
    promise = classify_from_brief("cinematic", {})
    verdict = promise.validate_cuts([])
    assert verdict["valid"] is False


def test_to_dict_from_dict_roundtrip() -> None:
    promise = classify_from_brief("localization-dub", {"quality": "broadcast"})
    data = promise.to_dict()
    restored = type(promise).from_dict(data)
    assert restored.promise_type == promise.promise_type
    assert restored.quality_floor == "broadcast"

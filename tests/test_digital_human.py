"""3O §3 Task 3.2:digital_human 能力域(avatar_render / lipsync_driver / models)单测。"""

from __future__ import annotations

import pytest

from hevi.digital_human.lipsync_driver import (
    LipSyncCapability,
    LipSyncUnsupported,
    drive_lip_sync,
    ensure_lip_sync,
    lip_sync_capability,
)
from hevi.digital_human.models import Presenter


def test_lipsync_capability_known_provider():
    # veo3 声明原生 lip_sync(见 capability_guard PROVIDER_LIMITS)
    cap = lip_sync_capability("veo3")
    assert cap.provider == "veo3"
    # 能力矩阵存在即返回 native 布尔值(不抛)
    assert cap.native in (True, False)


def test_lipsync_unknown_provider_conservative():
    cap = lip_sync_capability("definitely_not_a_provider_xyz")
    assert cap.native is False
    assert cap.post_processing is False


def test_ensure_lip_sync_raises_for_unsupported():
    with pytest.raises(LipSyncUnsupported):
        ensure_lip_sync("definitely_not_a_provider_xyz", require=True)


def test_drive_lip_sync_records_decision(monkeypatch):
    # 原生支持路径:能力门禁通过 → 记录决策(供 decision_trail/可观测性消费)
    monkeypatch.setattr(
        "hevi.digital_human.lipsync_driver.lip_sync_capability",
        lambda p: LipSyncCapability(provider=p, native=True),
    )
    rec = drive_lip_sync("veo3", audio="a.wav", video="v.mp4")
    assert rec["provider"] == "veo3"
    assert rec["mode"] == "native"
    assert "note" in rec


def test_drive_lip_sync_raises_for_unsupported():
    with pytest.raises(LipSyncUnsupported):
        drive_lip_sync("definitely_not_a_provider_xyz", audio="a.wav", video="v.mp4")


def test_presenter_model_moved_to_digital_human():
    # Presenter 已收拢进 digital_human.models(配置面)
    assert Presenter.__tablename__ == "presenters"
    assert "lipsync" in Presenter.__table__.columns


def test_avatar_render_resolve_dimensions():
    from hevi.digital_human.avatar_render import resolve_dimensions

    assert resolve_dimensions("720P", "16:9") == (1280, 720)
    assert resolve_dimensions("720P", "9:16") == (720, 1280)  # 竖屏转置
    assert resolve_dimensions("1080P", "16:9") == (1920, 1080)
    assert resolve_dimensions("UNKNOWN", "16:9") == (1280, 720)  # 未知分档回退 720P

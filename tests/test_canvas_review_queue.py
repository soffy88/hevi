"""S7: ChatGPT review queue helpers (no database, no network)."""

from __future__ import annotations

import time

from hevi.canvas import graph_diff as gd
from hevi.canvas.review_queue import (
    chatgpt_enabled,
    collect_thumbnails,
    extract_sentence,
    make_thumb_token,
    review_providers,
    thumbnail_urls,
    verify_thumb_token,
)


def test_chatgpt_queue_defaults_on_and_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.delenv("HEVI_REVIEW_CHATGPT", raising=False)
    assert chatgpt_enabled() is True
    assert review_providers() == ["offline_rules", "chatgpt_queue"]
    monkeypatch.setenv("HEVI_REVIEW_CHATGPT", "0")
    assert chatgpt_enabled() is False
    assert review_providers() == ["offline_rules"]


def test_offline_rules_are_always_present() -> None:
    assert review_providers()[0] == "offline_rules"


def test_signed_thumbnail_token_roundtrip_and_expiry(monkeypatch) -> None:
    monkeypatch.setenv("HEVI_REVIEW_SIGN_SECRET", "test-secret")
    token = make_thumb_token("item-1", 2, int(time.time()) + 60)
    assert verify_thumb_token(token) == ("item-1", 2)
    expired = make_thumb_token("item-1", 2, int(time.time()) - 1)
    assert verify_thumb_token(expired) is None
    assert verify_thumb_token(token[:-1] + "x") is None


def test_thumbnail_urls_are_https_and_time_limited(monkeypatch) -> None:
    monkeypatch.setenv("HEVI_REVIEW_SIGN_SECRET", "test-secret")
    monkeypatch.setenv("HEVI_REVIEW_PUBLIC_BASE_URL", "https://hevi.kanpan.co")
    urls = thumbnail_urls("item-1", ["/tmp/a.jpg", "/tmp/b.jpg"])
    assert len(urls) == 2
    assert urls[0]["url"].startswith("https://hevi.kanpan.co/api/canvas/review/thumb/")
    assert urls[0]["expires_in_s"] == "900"


def test_collect_thumbnails_uses_configured_contact_sheet_and_ignores_missing(tmp_path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    node = {"config": {"review_thumbnails": [str(image), str(tmp_path / "missing.png")]}}
    review = {"signals": {"contact_sheet": str(image)}}
    found = collect_thumbnails(node, {"output": ""}, review)
    assert found == [str(image)]


def test_extract_sentence_prefers_output_then_config() -> None:
    node = {"config": {"content": "配置文本"}}
    assert extract_sentence(node, {"output": "节点输出"}) == "节点输出"
    assert extract_sentence(node, {}) == "配置文本"


def test_needs_redo_is_a_known_ui_status() -> None:
    assert gd.STATUS_NEEDS_REDO == "needs_redo"
    # needs_redo waits for a human: a dirty rerun does not silently take it.
    assert "needs_redo" not in gd._RUNNABLE_STATUSES

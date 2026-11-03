"""Contract tests for image.nano_banana_generate (Gemini API route).

Offline: the HTTP transport (``nano_banana._http_post``) is monkeypatched,
so no key and no network are needed. The cost gate and the missing-key
error are both asserted to fire BEFORE any transport call.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities import nano_banana
from hevi.capabilities.errors import CapabilityError

# 1x1 transparent PNG, base64.
_FAKE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAwMCAO+ip1sAAAAASUVORK5CYII="
)
_FAKE_PNG = base64.b64decode(_FAKE_PNG_B64)


def _interaction_reply() -> dict:
    return {"interaction": {"output_image": {"data": _FAKE_PNG_B64, "mime_type": "image/png"}}}


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("HEVI_NANO_BANANA_MODEL", raising=False)


def test_nano_banana_registered_and_described() -> None:
    assert "image.nano_banana_generate" in caps.names()
    cap = caps.get("image.nano_banana_generate")
    assert cap.params_schema["properties"]["prompt"]["minLength"] == 1
    assert "allow_paid" in cap.params_schema["properties"]
    assert cap.description


def test_rejects_missing_prompt_and_extra_params(tmp_path: Path) -> None:
    cap = caps.get("image.nano_banana_generate")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "out", duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"prompt": "x", "bogus": 1},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_cost_gate_blocks_before_key_and_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list = []

    def _boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("transport must not run behind the cost gate")

    monkeypatch.setattr(nano_banana, "_http_post", _boom)
    _clear_keys(monkeypatch)
    cap = caps.get("image.nano_banana_generate")
    # allow_paid absent (default False) -> refused.
    with pytest.raises(CapabilityError, match="allow_paid"):
        cap.render_safe(
            {"prompt": "a school plaque"},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    # allow_paid explicitly False -> refused.
    with pytest.raises(CapabilityError, match="allow_paid"):
        cap.render_safe(
            {"prompt": "a school plaque", "allow_paid": False},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    assert calls == []


def test_missing_key_errors_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list = []

    def _boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("transport must not run without a key")

    monkeypatch.setattr(nano_banana, "_http_post", _boom)
    _clear_keys(monkeypatch)
    cap = caps.get("image.nano_banana_generate")
    with pytest.raises(CapabilityError, match="GEMINI_API_KEY"):
        cap.render_safe(
            {"prompt": "a school plaque", "allow_paid": True},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    assert calls == []


def test_render_writes_png_and_passes_prompt_ratio_and_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[dict] = []

    def _fake(url, payload, api_key, timeout):
        captured.append(payload)
        assert api_key == "test-key-not-real"
        assert url == nano_banana.API_URL
        return _interaction_reply()

    monkeypatch.setattr(nano_banana, "_http_post", _fake)
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    cap = caps.get("image.nano_banana_generate")
    out_dir = tmp_path / "out"
    result = cap.render_safe(
        {"prompt": "ancient Chinese classroom", "allow_paid": True, "n": 2},
        out_dir,
        duration=1.0,
        aspect="16:9",
        seed=7,
    )
    assert len(captured) == 2  # n=2 -> two billed calls, one image each
    assert captured[0]["model"] == "gemini-nano-banana-2.1"  # default model
    assert captured[0]["input"] == "ancient Chinese classroom"
    assert captured[0]["response_format"]["aspect_ratio"] == "16:9"  # render aspect passthrough
    assert captured[0]["response_format"]["image_size"] == "1K"  # default size
    assert result.png == str(out_dir / "image_1.png")
    assert Path(result.png).read_bytes() == _FAKE_PNG
    assert (out_dir / "image_2.png").is_file()
    assert result.qa["image_count"] == 2
    assert result.qa["estimated_cost_usd"] == pytest.approx(0.0336 * 2)
    sidecar = json.loads(Path(result.qa["sidecar_json"]).read_text(encoding="utf-8"))
    assert sidecar["model"] == "gemini-nano-banana-2.1"
    assert "GEMINI_API_KEY" not in json.dumps(sidecar)
    assert "test-key-not-real" not in json.dumps(sidecar)


def test_explicit_aspect_ratio_overrides_render_aspect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[dict] = []

    def _fake(url, payload, api_key, timeout):
        captured.append(payload)
        return _interaction_reply()

    monkeypatch.setattr(nano_banana, "_http_post", _fake)
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")
    cap = caps.get("image.nano_banana_generate")
    cap.render_safe(
        {
            "prompt": "a wide classroom",
            "allow_paid": True,
            "aspect_ratio": "21:9",
            "image_size": "2K",
        },
        tmp_path / "out",
        duration=1.0,
        aspect="9:16",  # render aspect must NOT win over the param
        seed=1,
    )
    assert captured[0]["response_format"]["aspect_ratio"] == "21:9"
    assert captured[0]["response_format"]["image_size"] == "2K"


def test_chinese_text_template_added_only_when_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[dict] = []

    def _fake(url, payload, api_key, timeout):
        captured.append(payload)
        return _interaction_reply()

    monkeypatch.setattr(nano_banana, "_http_post", _fake)
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    cap = caps.get("image.nano_banana_generate")
    cap.render_safe(
        {"prompt": "a school hall", "allow_paid": True, "chinese_text": "私塾"},
        tmp_path / "out1",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert "私塾" in captured[0]["input"]
    assert "character for character" in captured[0]["input"]
    cap.render_safe(
        {"prompt": "a school hall", "allow_paid": True},
        tmp_path / "out2",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert "character for character" not in captured[1]["input"]


def test_model_env_override_and_invalid_model_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[dict] = []

    def _fake(url, payload, api_key, timeout):
        captured.append(payload)
        return _interaction_reply()

    monkeypatch.setattr(nano_banana, "_http_post", _fake)
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("HEVI_NANO_BANANA_MODEL", "gemini-3-pro-image")
    cap = caps.get("image.nano_banana_generate")
    cap.render_safe(
        {"prompt": "a poster", "allow_paid": True},
        tmp_path / "out1",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert captured[0]["model"] == "gemini-3-pro-image"
    # Param model beats the env override.
    cap.render_safe(
        {"prompt": "a poster", "allow_paid": True, "model": "gemini-3.1-flash-lite-image"},
        tmp_path / "out2",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert captured[1]["model"] == "gemini-3.1-flash-lite-image"
    # Invalid env value is refused before transport.
    monkeypatch.setenv("HEVI_NANO_BANANA_MODEL", "not-a-real-model")
    before = len(captured)
    with pytest.raises(CapabilityError, match="unknown model"):
        cap.render_safe(
            {"prompt": "a poster", "allow_paid": True},
            tmp_path / "out3",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    assert len(captured) == before


def test_lite_rejects_non_1k_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list = []

    def _boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("transport must not run for Lite 2K")

    monkeypatch.setattr(nano_banana, "_http_post", _boom)
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    cap = caps.get("image.nano_banana_generate")
    with pytest.raises(CapabilityError, match="1K"):
        cap.render_safe(
            {
                "prompt": "a poster",
                "allow_paid": True,
                "model": "gemini-3.1-flash-lite-image",
                "image_size": "2K",
            },
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    assert calls == []


def test_response_without_image_is_an_error_not_fake_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake(url, payload, api_key, timeout):
        return {"interaction": {}}

    monkeypatch.setattr(nano_banana, "_http_post", _fake)
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    cap = caps.get("image.nano_banana_generate")
    with pytest.raises(CapabilityError, match="no image data"):
        cap.render_safe(
            {"prompt": "a poster", "allow_paid": True},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    assert not (tmp_path / "out" / "image.png").exists()

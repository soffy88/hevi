"""Contract tests for the PixStag capability (CAPABILITY_CONTRACT.md).

Offline: the PixStag client layer is monkeypatched, so no key and no
network are needed.
"""

import base64
import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.video import pixstag_client


def test_pixstag_capability_registered_and_listable() -> None:
    assert "video.pixstag_generate" in caps.names()
    listed = [c.name for c in caps.list(kind="shot")]
    assert "video.pixstag_generate" in listed


def test_pixstag_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    assert "video.pixstag_generate" in by_name
    item = by_name["video.pixstag_generate"]
    assert item.get("description")
    schema = item.get("params_schema") or {}
    assert "prompt" in (schema.get("properties") or {})
    assert schema.get("required") == ["prompt"]


def test_pixstag_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("video.pixstag_generate")
    with pytest.raises(CapabilityError):  # missing required prompt
        cap.render_safe({}, tmp_path, duration=5.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):  # duration out of range
        cap.render_safe({"prompt": "x", "duration": 3}, tmp_path, duration=5.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):  # unsupported model
        cap.render_safe({"prompt": "x", "model": "nope"}, tmp_path, duration=5.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):  # additional property
        cap.render_safe({"prompt": "x", "bogus": 1}, tmp_path, duration=5.0, aspect="9:16", seed=1)


def test_pixstag_missing_key_surfaces_as_capability_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PIXSTAG_API_KEY", raising=False)
    cap = caps.get("video.pixstag_generate")
    with pytest.raises(CapabilityError) as excinfo:
        cap.render_safe({"prompt": "雨夜的小猫"}, tmp_path, duration=5.0, aspect="9:16", seed=1)
    assert "PIXSTAG_API_KEY" in str(excinfo.value)


def test_pixstag_api_error_passes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_generate(**kwargs):
        raise pixstag_client.PixStagError(
            "PixStag task T1 ended with status failed: code=INSUFFICIENT_CREDIT message=积分不足"
        )

    monkeypatch.setattr(pixstag_client, "generate_clip", fake_generate)
    monkeypatch.setenv("PIXSTAG_API_KEY", "dummy")
    cap = caps.get("video.pixstag_generate")
    with pytest.raises(CapabilityError) as excinfo:
        cap.render_safe({"prompt": "x"}, tmp_path, duration=5.0, aspect="9:16", seed=1)
    assert "INSUFFICIENT_CREDIT" in str(excinfo.value)


def test_pixstag_render_writes_clip_and_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_generate(*, output_path, **kwargs):
        captured.update(kwargs)
        captured["output_path"] = output_path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-mp4-bytes")
        return {
            "task_id": "T-123",
            "output_path": str(output_path),
            "model": kwargs.get("model", "MiniMax-H3"),
            "duration": kwargs.get("duration", 5),
            "ratio": kwargs.get("ratio", "9:16"),
            "resolution": kwargs.get("resolution", "720P"),
            "usage": {"total_seconds": 6},
            "credit_estimate": 5.0,
            "usd_estimate": 0.075,
            "poster_url": None,
            "last_frame_url": None,
        }

    def fake_me():
        return {"credit": 295, "credit_frozen": 5, "credit_valid_time": 1763014800}

    monkeypatch.setattr(pixstag_client, "generate_clip", fake_generate)
    monkeypatch.setattr(pixstag_client, "me", fake_me)
    monkeypatch.setenv("PIXSTAG_API_KEY", "dummy")

    frame = tmp_path / "first.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)

    cap = caps.get("video.pixstag_generate")
    out_dir = tmp_path / "out"
    result = cap.render_safe(
        {
            "prompt": "小猫推开家门，抬头看向镜头",
            "duration": 6,
            "first_frame_path": str(frame),
        },
        out_dir,
        duration=6.0,
        aspect="9:16",
        seed=11,
    )
    assert captured["prompt"] == "小猫推开家门，抬头看向镜头"
    assert captured["first_frame"] == str(frame)

    assert result.mp4 is not None
    clip = Path(result.mp4)
    assert clip.is_file() and clip.read_bytes() == b"fake-mp4-bytes"
    assert result.sha256
    assert result.duration_s == 6
    assert result.qa["task_id"] == "T-123"
    assert result.qa["credit_estimate"] == 5.0
    assert result.qa["balance"]["credit"] == 295
    assert result.qa["balance"]["credit_expires_at_utc"]

    sidecar = Path(result.qa["sidecar_json"])
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["task_id"] == "T-123"
    assert payload["usage"]["total_seconds"] == 6
    assert payload["balance"]["credit_frozen"] == 5

    clip.unlink()
    assert not clip.exists(), "contract: deleting the artifact must break verification"


def test_build_body_image_roles_and_base64(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    first.write_bytes(b"\xff\xd8\xff" + b"img" * 8)
    ref = tmp_path / "b.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"ref" * 8)

    body = pixstag_client.build_body(
        prompt="p", first_frame=first, reference_images=[ref], duration=8
    )
    assert body["model"] == "MiniMax-H3"
    assert body["duration"] == 8
    content = body["content"]
    assert content[0] == {"type": "text", "text": "p"}
    first_entry = content[1]
    assert first_entry["role"] == "first_frame"
    assert base64.b64decode(first_entry["image_url"]["url"]) == first.read_bytes()
    ref_entry = content[2]
    assert ref_entry["role"] == "reference_image"
    assert base64.b64decode(ref_entry["image_url"]["url"]) == ref.read_bytes()


def test_build_body_rejects_bad_inputs() -> None:
    with pytest.raises(pixstag_client.PixStagError):
        pixstag_client.build_body(prompt="p", duration=99)
    with pytest.raises(pixstag_client.PixStagError):
        pixstag_client.build_body(prompt="")
    with pytest.raises(pixstag_client.PixStagError):
        pixstag_client.build_body(prompt="p", ratio="3:2")


def test_encode_image_rejects_oversize(tmp_path: Path) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG" + b"0" * (3 * 1024 * 1024 + 10))
    with pytest.raises(pixstag_client.PixStagError):
        pixstag_client.encode_image(big)


def test_wait_task_failure_raises_with_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pixstag_client,
        "query_task",
        lambda task_id: {"status": "failed", "error": {"code": "E42", "message": "boom"}},
    )
    with pytest.raises(pixstag_client.PixStagError) as excinfo:
        pixstag_client.wait_task("T9", timeout_s=1.0, poll_interval_s=0.0)
    assert "E42" in str(excinfo.value) and "boom" in str(excinfo.value)


def test_missing_key_error_names_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIXSTAG_API_KEY", raising=False)
    with pytest.raises(pixstag_client.PixStagError) as excinfo:
        pixstag_client.me()
    assert "PIXSTAG_API_KEY" in str(excinfo.value)

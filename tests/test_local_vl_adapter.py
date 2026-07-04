"""C2: local Qwen-VL mllm adapter — image attachment + JSON extraction + unload.

Mocks ollama HTTP so it runs without a model. The e2e vision check (real ollama)
is done manually; this locks the wiring behaviors that must not regress.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

import hevi.providers.local_qwen_vl_adapter as vl


@pytest.fixture
def red_png(tmp_path: Path) -> Path:
    # 1x1 PNG (red) — content irrelevant; we only assert it's base64'd into the payload.
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
    )
    p = tmp_path / "frame.png"
    p.write_bytes(raw)
    return p


def _install_fake_post(
    monkeypatch: pytest.MonkeyPatch, capture: dict[str, Any], content: str
) -> None:
    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": content}}], "usage": {}}

    def fake_post(url: str, **kwargs: Any) -> _Resp:
        if url.endswith("/v1/chat/completions"):
            capture["payload"] = kwargs["json"]
        else:  # keep_alive unload
            capture.setdefault("unloaded", True)
        return _Resp()

    monkeypatch.setattr(vl.httpx, "post", fake_post)


def test_image_attached_as_base64_to_last_user_message(monkeypatch, red_png):
    cap: dict[str, Any] = {}
    _install_fake_post(monkeypatch, cap, '{"score": 0.8}')

    r = vl.local_qwen_vl_adapter(
        messages=[{"role": "system", "content": "eval"}, {"role": "user", "content": "frame:"}],
        image_paths=[str(red_png)],
    )
    content = r.get("content")

    parts = cap["payload"]["messages"][-1]["content"]
    assert isinstance(parts, list), "last user message should become multimodal parts"
    img_parts = [p for p in parts if p.get("type") == "image_url"]
    assert len(img_parts) == 1
    assert img_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert cap.get("unloaded") is True, "model must be unloaded (keep_alive:0) after call"
    assert json.loads(content)["score"] == 0.8


def test_json_extracted_from_markdown_fence(monkeypatch, red_png):
    cap: dict[str, Any] = {}
    _install_fake_post(
        monkeypatch, cap, 'Here is the result:\n```json\n{"score": 0.42}\n```\nDone.'
    )

    r = vl.local_qwen_vl_adapter(
        messages=[{"role": "user", "content": "x"}], image_paths=[str(red_png)]
    )
    assert json.loads(r.get("content"))["score"] == 0.42  # fence + prose stripped


def test_no_images_leaves_messages_plain(monkeypatch):
    cap: dict[str, Any] = {}
    _install_fake_post(monkeypatch, cap, '{"score": 1.0}')

    vl.local_qwen_vl_adapter(messages=[{"role": "user", "content": "hi"}]).get("content")
    assert cap["payload"]["messages"][-1]["content"] == "hi"  # untouched string, no parts

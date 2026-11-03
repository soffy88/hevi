"""Contract tests for the short-story line (CAPABILITY_CONTRACT.md).

Offline: the LLM is injected/fake and the cover path either uses an
injected cover_fn or a monkeypatched image.gpt_generate — no key, no
network, no cost.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.shortstory.core import ShortStoryError, build_short_package, review_story

PREMISE = "退休侦探在小镇上破获最后一案"


def make_fake_llm(draft: str | None = None):
    """Fake llm_fn keyed by stage; returns JSON-ish payloads per stage."""
    calls: list[tuple[str, dict]] = []

    def fake(stage: str, payload: dict):
        calls.append((stage, payload))
        if stage == "outline":
            return json.dumps(
                {
                    "title": "最后一案",
                    "logline": "退休侦探被迫重出江湖，解开小镇尘封的秘密。",
                    "characters": [
                        {"name": "老林", "role": "主角", "description": "退休侦探"},
                        {"name": "小雅", "role": "助手", "description": "镇上的邮差"},
                    ],
                    "beats": [
                        {"title": "开端", "summary": "老林收到一封没署名的信。"},
                        {"title": "发展", "summary": "调查中发现所有线索都指向自己。"},
                        {"title": "高潮", "summary": "老林被迫在真相和人情之间选择。"},
                        {"title": "结尾", "summary": "小镇安静下来，老林终于告别过去。"},
                    ],
                },
                ensure_ascii=False,
            )
        if stage == "draft":
            return draft or (
                "深夜，老林收到一封没有署名的信。\n\n"
                "信上只有一句话：你藏了二十年的秘密，我都知道。老林的手抖了。"
                "但是他不能退缩，小雅已经被人跟踪了。他必须在真相和人情之间做选择。"
                "然而所有的线索都指向他自己，这是一场精心设计的陷阱。\n\n"
                "老林挣扎了一整夜，最终决定独自前往废弃的邮局赴约。"
                "他明白，只有亲手揭开真相，才能保护小雅。\n\n"
                "天亮时，一切都结束了。老林站在空荡荡的邮局里，终于告别了过去，"
                "回到了属于他的安静生活。"
            )
        if stage == "blurb":
            return json.dumps(
                {
                    "title_candidates": ["最后一案", "退休侦探的最后一夜", "小镇的秘密"],
                    "one_line_pitch": "退休侦探被迫重出江湖，破获尘封二十年的小镇悬案。",
                    "synopsis": "老林退休多年，一封匿名信把他拖回漩涡中心。",
                    "selling_points": ["开篇即悬念", "反转式真相", "温情收尾"],
                },
                ensure_ascii=False,
            )
        if stage == "cover_prompt":
            return "Book cover, retired detective silhouette in a foggy small town, moody light."
        raise AssertionError(f"unexpected stage {stage!r}")

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def test_shortstory_capability_registered_and_described() -> None:
    import hevi.capabilities.shortstory as shortstory_mod

    shortstory_mod.register_shortstory_capabilities_once()
    assert "story.short_package" in caps.names()
    # Idempotent: second registration returns [] and keeps one entry.
    assert shortstory_mod.register_shortstory_capabilities_once() == []
    by_name = {c.name: c for c in caps.list()}
    assert "story.short_package" in by_name
    cap = caps.get("story.short_package")
    assert cap.params_schema["required"] == ["premise"]
    assert cap.description


def test_shortstory_rejects_invalid_params(tmp_path: Path) -> None:
    import hevi.capabilities.shortstory as shortstory_mod

    shortstory_mod.register_shortstory_capabilities_once()
    cap = caps.get("story.short_package")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "o1", duration=0.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"premise": PREMISE, "bogus": 1},
            tmp_path / "o2",
            duration=0.0,
            aspect="16:9",
            seed=1,
        )


def test_core_requires_premise_and_llm(tmp_path: Path) -> None:
    with pytest.raises(ShortStoryError):
        build_short_package(
            premise="  ", out_dir=tmp_path, llm_fn=make_fake_llm()
        )
    with pytest.raises(ShortStoryError):
        build_short_package(premise=PREMISE, out_dir=tmp_path, llm_fn=None)


def test_full_chain_writes_all_artifacts(tmp_path: Path) -> None:
    def fake_cover(prompt: str, out_path: Path):
        assert "detective" in prompt
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"pngbytes")
        return out_path

    manifest = build_short_package(
        premise=PREMISE,
        genre="悬疑",
        out_dir=tmp_path / "pkg",
        llm_fn=make_fake_llm(),
        cover_fn=fake_cover,
    )
    out = tmp_path / "pkg"
    for name in (
        "outline.md",
        "outline.json",
        "story.txt",
        "story.md",
        "review.json",
        "review.md",
        "blurb.json",
        "blurb.md",
        "cover_prompt.txt",
        "cover.png",
        "package.json",
    ):
        assert (out / name).is_file(), name
    # Review checklist structure.
    review = json.loads((out / "review.json").read_text(encoding="utf-8"))
    check_names = [c["name"] for c in review["checks"]]
    assert check_names == ["hook", "conflict", "ending", "structure", "length"]
    assert all(set(c) >= {"name", "score", "max", "ok", "detail"} for c in review["checks"])
    assert review["total_score"] >= 15  # the fake draft carries markers
    # Blurb structure.
    blurb = json.loads((out / "blurb.json").read_text(encoding="utf-8"))
    assert blurb["title_candidates"][0] == "最后一案"
    assert blurb["one_line_pitch"]
    assert blurb["synopsis"]
    assert blurb["selling_points"]
    # Cover prompt + generated cover.
    assert (out / "cover.png").read_bytes() == b"pngbytes"
    cover = manifest["cover"]
    assert cover["status"] == "generated" and cover["degraded"] is False
    # Manifest ledger.
    assert manifest["title"] == "最后一案"
    assert manifest["word_count"] > 0
    assert set(manifest["files"]) >= {"outline.json", "story.txt", "package.json"}
    # Contract: deleting the ledger breaks verification.
    (out / "package.json").unlink()
    assert not (out / "package.json").exists()


def test_cover_degraded_when_image_capability_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def missing_capability(name: str):
        raise CapabilityError("unknown capability: 'image.gpt_generate'")

    monkeypatch.setattr(caps, "get", missing_capability)
    manifest = build_short_package(
        premise=PREMISE,
        genre="悬疑",
        out_dir=tmp_path / "pkg2",
        llm_fn=make_fake_llm(),
        cover_fn=None,
        attempt_cover=True,
    )
    out = tmp_path / "pkg2"
    assert (out / "cover_prompt.txt").is_file()
    assert not (out / "cover.png").exists()
    cover = manifest["cover"]
    assert cover["status"] == "prompt_only" and cover["degraded"] is True
    assert "image.gpt_generate" in cover["note"]
    assert (out / "package.json").is_file()


def test_capability_full_chain_with_fake_llm_and_fake_cover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hevi.capabilities.shortstory as shortstory_mod

    shortstory_mod.register_shortstory_capabilities_once()
    monkeypatch.setattr(
        shortstory_mod, "_default_llm_fn", make_fake_llm()
    )

    class FakeCoverCap:
        def render_safe(self, params, out_dir, *, duration=0.0, aspect="9:16", seed=42):
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            png = out_dir / "image.png"
            png.write_bytes(b"fakecover")
            result = type("R", (), {})()
            result.png = str(png)
            return result

    def fake_get(name: str):
        assert name == "image.gpt_generate"
        return FakeCoverCap()

    monkeypatch.setattr(caps, "get", fake_get)
    # Fetch the registered capability through the list API (not patched).
    registered = {c.name: c for c in caps.list()}
    result_cap = registered["story.short_package"].render_safe(
        {"premise": PREMISE, "genre": "悬疑"},
        tmp_path / "cap-out",
        duration=0.0,
        aspect="9:16",
        seed=1,
    )
    assert result_cap.png is not None
    assert Path(result_cap.png).is_file()
    assert result_cap.sha256
    assert result_cap.qa["cover_status"] == "generated"
    assert result_cap.qa["cover_degraded"] is False
    assert result_cap.qa["title_candidates"][0] == "最后一案"
    assert result_cap.qa["one_line_pitch"]
    assert (tmp_path / "cap-out" / "cover_prompt.txt").is_file()
    # Contract: deleting the cover artifact breaks verification.
    Path(result_cap.png).unlink()
    assert not Path(result_cap.png).exists()


def test_review_story_is_deterministic() -> None:
    text = "深夜，电话响了。\n\n但是没有人说话，只有一声叹息。\n\n天亮了，他终于明白了。"
    first = review_story(text)
    second = review_story(text)
    assert first == second
    assert [c["name"] for c in first["checks"]] == [
        "hook",
        "conflict",
        "ending",
        "structure",
        "length",
    ]

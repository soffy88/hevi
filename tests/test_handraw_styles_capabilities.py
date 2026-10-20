"""Contract tests for the handraw-style capabilities (CAPABILITY_CONTRACT.md).

Offline: the Monid image backend is monkeypatched, so no key and no
network are needed.  Prompt snapshots are byte-identical to the upstream
library's own deterministic CLI (scripts/prompt_style.py) for the same
inputs -- verified against yang0/handraw-style v1.9.1.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.image import handraw_style as hs

FI001_ZH = "风格名称：Apple Minimalist Tech Product Commercial Photography。主题：银色无线头戴耳机。参考作者/风格名称：Apple / 苹果。"
FI001_EN = "Style name: Apple Minimalist Tech Product Commercial Photography. Theme: 银色无线头戴耳机. Reference author/style name: Apple / 苹果."
FI001_COLOR_ZH = "风格名称：Apple Minimalist Tech Product Commercial Photography。主题色：克莱因蓝（Klein Blue）。主题：银色无线头戴耳机。参考作者/风格名称：Apple / 苹果。"
FI027_TEXT_ZH = "风格名称：Wes Anderson Pastel Symmetry & Retro Whimsical Cinematic Aesthetic。主题：山间小镇的老式缆车站。参考作者/风格名称：Wes Anderson / 韦斯·安德森。【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。 如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，由你先设计画面隐喻（人类和非人类都行）再出图   。    文字参与构图，图文一体】"
SC001_FA001_ZH = "图型：上文下图社媒卡。主题：秋天的第一杯奶茶。排版要求：小红书社媒卡。排版采用上文下图结构：上方集中放置主题文字和简短补充文案，下方放置完整主图或场景图。上下内容保持清晰的阅读顺序，图文关系自然，整体构图简洁。风格名称：Playful Deadpan Doodle。参考作者/风格名称：Gemma Correll。【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。 如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，由你先设计画面隐喻（人类和非人类都行）再出图   。    文字参与构图，图文一体】"


def test_handraw_capabilities_registered_and_listable() -> None:
    names = caps.names()
    assert "image.handraw_styles" in names
    assert "image.styled_generate" in names
    listed = [c.name for c in caps.list(kind="shot")]
    assert "image.handraw_styles" in listed
    assert "image.styled_generate" in listed


def test_handraw_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in ("image.handraw_styles", "image.styled_generate"):
        assert expected in by_name
        assert by_name[expected].get("description"), expected


def test_index_counts_and_key_entries() -> None:
    assert hs.counts() == {"styles": 365, "layouts": 167, "colors": 36, "tones": 16}
    fi001 = hs.get_style("FI-001")
    assert fi001["generation_name"] == (
        "Apple Minimalist Tech Product Commercial Photography"
    )
    assert fi001["legacy_number"] == "332"
    fi027 = hs.get_style("FI-027")
    assert fi027["reference"] == "Wes Anderson / 韦斯·安德森"
    # Legacy numbers and sloppy ids resolve to the same entry.
    assert hs.get_style("332")["id"] == "FI-001"
    assert hs.get_style("fi-027")["id"] == "FI-027"


def test_catalogue_render_counts_and_filters(tmp_path: Path) -> None:
    cap = caps.get("image.handraw_styles")
    result = cap.render_safe({}, tmp_path, duration=1.0, aspect="16:9", seed=1)
    assert result.qa["counts"] == {
        "styles": 365,
        "layouts": 167,
        "colors": 36,
        "tones": 16,
    }
    payload = json.loads(Path(result.qa["catalogue_json"]).read_text(encoding="utf-8"))
    assert payload["returned"] == {
        "styles": 365,
        "layouts": 167,
        "colors": 36,
        "tones": 16,
    }
    assert "yang0" in payload["attribution"]

    result = cap.render_safe(
        {"section": "styles", "query": "Wes Anderson"},
        tmp_path / "q",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    payload = json.loads(Path(result.qa["catalogue_json"]).read_text(encoding="utf-8"))
    assert [s["id"] for s in payload["styles"]] == ["FI-027"]

    result = cap.render_safe(
        {"section": "styles", "category": "FI"},
        tmp_path / "c",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    payload = json.loads(Path(result.qa["catalogue_json"]).read_text(encoding="utf-8"))
    assert payload["returned"]["styles"] == 34
    assert all(s["category"] == "FI" for s in payload["styles"])


def test_assemble_prompt_snapshots() -> None:
    a = hs.assemble_prompt("FI-001", "银色无线头戴耳机")
    assert a["prompt_zh"] == FI001_ZH
    assert a["prompt_en"] == FI001_EN
    assert a["activation_source"] == "name+style"
    assert a["mode"] == "pure"

    b = hs.assemble_prompt("FI-027", "山间小镇的老式缆车站", mode="text")
    assert b["prompt_zh"] == FI027_TEXT_ZH

    c = hs.assemble_prompt("FA-001", "秋天的第一杯奶茶", layout_id="SC-001")
    assert c["prompt_zh"] == SC001_FA001_ZH
    assert c["mode"] == "text"  # a layout forces graphic-text mode

    d = hs.assemble_prompt("FI-001", "银色无线头戴耳机", color_id="C-01")
    assert d["prompt_zh"] == FI001_COLOR_ZH


def test_assemble_rejects_unknown_ids() -> None:
    with pytest.raises(hs.HandrawStyleError):
        hs.assemble_prompt("FI-999", "主题")
    with pytest.raises(hs.HandrawStyleError):
        hs.assemble_prompt("FI-001", "主题", layout_id="XX-999")
    with pytest.raises(hs.HandrawStyleError):
        hs.assemble_prompt("FI-001", "主题", color_id="C-99")


def test_styled_generate_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("image.styled_generate")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"style_id": "FI-001"},  # missing required theme
            tmp_path,
            duration=1.0,
            aspect="1:1",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"style_id": "FI-001", "theme": "x", "bogus": 1},
            tmp_path,
            duration=1.0,
            aspect="1:1",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"style_id": "FI-999", "theme": "x"},  # unknown style id
            tmp_path,
            duration=1.0,
            aspect="1:1",
            seed=1,
        )


def test_styled_generate_missing_monid_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    cap = caps.get("image.styled_generate")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"style_id": "FI-001", "theme": "银色无线头戴耳机"},
            tmp_path,
            duration=1.0,
            aspect="1:1",
            seed=1,
        )


def test_styled_generate_render_writes_image_and_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.image import gpt_image_service

    captured: dict[str, object] = {}

    async def fake_generate(*, prompt, output_path, size, quality, **_):
        captured["prompt"] = prompt
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return {"output_path": str(output_path), "cost": 0.0107}

    monkeypatch.setattr(gpt_image_service, "gpt_image_generate", fake_generate)
    cap = caps.get("image.styled_generate")
    result = cap.render_safe(
        {"style_id": "FI-001", "theme": "银色无线头戴耳机"},
        tmp_path,
        duration=1.0,
        aspect="1:1",
        seed=1,
    )
    assert result.png and Path(result.png).exists()
    assert result.qa["cost"] == 0.0107
    assert result.qa["activation_source"] == "name+style"
    assert captured["prompt"] == FI001_ZH
    sidecar = json.loads(Path(result.qa["sidecar_json"]).read_text(encoding="utf-8"))
    assert sidecar["style_id"] == "FI-001"
    assert sidecar["prompt_zh"] == FI001_ZH
    assert sidecar["prompt_en"] == FI001_EN
    assert sidecar["cost"] == 0.0107
    assert "yang0" in sidecar["attribution"]


def test_styled_generate_reference_style_uses_edit_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index = hs.load_index()
    ref_style = next(
        s for s in index["styles"] if s["activation"]["use_reference_image"]
    )
    if hs.reference_image_path(ref_style) is None:
        pytest.skip("upstream checkout / reference image absent")
    from hevi.image import gpt_image_service

    captured: dict[str, object] = {}

    async def fake_edit(*, image_paths, prompt, output_path, size, quality, **_):
        captured["image_paths"] = [str(p) for p in image_paths]
        captured["prompt"] = prompt
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return {"output_path": str(output_path), "cost": 0.023}

    monkeypatch.setattr(gpt_image_service, "gpt_image_edit", fake_edit)
    cap = caps.get("image.styled_generate")
    result = cap.render_safe(
        {"style_id": ref_style["id"], "theme": "山间小屋"},
        tmp_path,
        duration=1.0,
        aspect="1:1",
        seed=1,
    )
    assert result.qa["reference_attached"] is True
    assert len(captured["image_paths"]) == 1
    assert "仅用于参考画风" in str(captured["prompt"])
    sidecar = json.loads(Path(result.qa["sidecar_json"]).read_text(encoding="utf-8"))
    assert sidecar["reference_image"]["required"] is True
    assert sidecar["reference_image"]["attached"] is True

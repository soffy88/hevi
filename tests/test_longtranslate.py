"""Contract tests for the long-translation line (CAPABILITY_CONTRACT.md).

Offline: the translator is injected/fake — no key, no network, no cost.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.longtranslate.core import (
    LongTranslateError,
    check_glossary,
    split_into_chunks,
    translate_long,
)


def fake_translate(text: str, *, target_language: str, glossary: dict, context: str):
    """Deterministic fake: wraps the source and honours glossary terms."""
    assert target_language == "English"
    out = text.replace("星舰", "starship").replace("船长", "captain")
    return f"[EN] {out}"


def test_longtranslate_capability_registered_and_described() -> None:
    import hevi.capabilities.longtranslate as lt_mod

    lt_mod.register_longtranslate_capabilities_once()
    assert "text.translate_long" in caps.names()
    assert lt_mod.register_longtranslate_capabilities_once() == []
    cap = caps.get("text.translate_long")
    assert cap.params_schema["required"] == ["target_language"]
    assert cap.description


def test_longtranslate_rejects_invalid_params(tmp_path: Path) -> None:
    import hevi.capabilities.longtranslate as lt_mod

    lt_mod.register_longtranslate_capabilities_once()
    cap = caps.get("text.translate_long")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "o1", duration=0.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"text": "hello", "bogus": 1, "target_language": "English"},
            tmp_path / "o2",
            duration=0.0,
            aspect="16:9",
            seed=1,
        )
    # Both text and input_path is illegal at the render layer too.
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"text": "hello", "input_path": "x.txt", "target_language": "English"},
            tmp_path / "o3",
            duration=0.0,
            aspect="16:9",
            seed=1,
        )


def test_core_validation(tmp_path: Path) -> None:
    with pytest.raises(LongTranslateError):
        translate_long(
            text="",
            target_language="English",
            out_dir=tmp_path,
            translate_fn=fake_translate,
        )
    with pytest.raises(LongTranslateError):
        translate_long(
            text="你好",
            target_language="",
            out_dir=tmp_path,
            translate_fn=fake_translate,
        )
    with pytest.raises(LongTranslateError):
        translate_long(
            text="你好",
            target_language="English",
            out_dir=tmp_path,
            translate_fn=None,
        )
    with pytest.raises(LongTranslateError):
        translate_long(
            text="你好",
            target_language="English",
            glossary={"a": 1},  # type: ignore[dict-item]
            out_dir=tmp_path,
            translate_fn=fake_translate,
        )
    with pytest.raises(LongTranslateError):
        translate_long(
            text="你好",
            input_path=tmp_path / "in.txt",
            target_language="English",
            out_dir=tmp_path,
            translate_fn=fake_translate,
        )


def test_chunk_count_is_exact() -> None:
    paragraphs = ["字" * 100 for _ in range(5)]
    text = "\n\n".join(paragraphs)
    chunks = split_into_chunks(text, max_chars=250)
    # Each chunk packs 2 paragraphs (100 + 2 + 100 = 202 <= 250); 3 would be 304.
    assert len(chunks) == 3
    assert all(len(c) <= 250 for c in chunks)
    # Every paragraph survives exactly once.
    joined = "\n\n".join(chunks)
    assert joined == text


def test_translate_long_full_chain_and_bilingual(tmp_path: Path) -> None:
    paragraphs = [f"星舰的船长望着远方，这是第{i}段。" for i in range(5)]
    text = "\n\n".join(paragraphs)
    seen_contexts: list[str] = []

    def tracking_fake(text_: str, *, target_language: str, glossary: dict, context: str):
        seen_contexts.append(context)
        return fake_translate(
            text_, target_language=target_language, glossary=glossary, context=context
        )

    report = translate_long(
        text=text,
        target_language="English",
        source_language="简体中文",
        glossary={"星舰": "starship", "船长": "captain"},
        out_dir=tmp_path / "tr",
        translate_fn=tracking_fake,
        max_chars=60,
        overlap_chars=10,
    )
    out = tmp_path / "tr"
    # 5 paragraphs of 16 chars packed at <=60: 3 per chunk (52) -> 2 chunks.
    assert report["chunk_count"] == 2
    assert len(seen_contexts) == 2 and seen_contexts[0] == ""
    assert seen_contexts[1] == paragraphs[2][-10:]
    for name in ("translated.txt", "bilingual.md", "bilingual.json", "translation_report.json"):
        assert (out / name).is_file(), name
    translated = (out / "translated.txt").read_text(encoding="utf-8")
    assert "starship" in translated and "captain" in translated
    assert report["glossary_ok"] is True and report["glossary_warnings"] == []
    # Bilingual structure: one pair per chunk, source + translation side by side.
    bilingual = json.loads((out / "bilingual.json").read_text(encoding="utf-8"))
    assert bilingual["target_language"] == "English"
    assert bilingual["source_language"] == "简体中文"
    assert len(bilingual["pairs"]) == report["chunk_count"]
    for i, pair in enumerate(bilingual["pairs"]):
        assert pair["index"] == i
        assert pair["source"] and pair["translation"]
        assert "starship" in pair["translation"]
    md = (out / "bilingual.md").read_text(encoding="utf-8")
    assert "**原文**" in md and "**译文**" in md
    assert "## Segment 1" in md and "## Segment 2" in md
    # Contract: deleting the primary artifact breaks verification.
    (out / "translated.txt").unlink()
    assert not (out / "translated.txt").exists()


def test_glossary_check_warns_on_missing_target_term(tmp_path: Path) -> None:
    def lossy_translate(text: str, *, target_language: str, glossary: dict, context: str):
        # Translates 星舰 but drops 龙 entirely.
        return text.replace("星舰", "starship")

    warnings = check_glossary(
        "星舰与龙一起航行。", "starship sails.", {"星舰": "starship", "龙": "dragon"}
    )
    assert len(warnings) == 1
    assert warnings[0]["source_term"] == "龙"
    assert warnings[0]["target_term"] == "dragon"

    report = translate_long(
        text="星舰与龙一起航行，船长下令启程。",
        target_language="English",
        glossary={"星舰": "starship", "龙": "dragon"},
        out_dir=tmp_path / "tr2",
        translate_fn=lossy_translate,
    )
    assert report["glossary_ok"] is False
    assert [w["target_term"] for w in report["glossary_warnings"]] == ["dragon"]
    saved = json.loads(
        (tmp_path / "tr2" / "translation_report.json").read_text(encoding="utf-8")
    )
    assert saved["glossary_warnings"][0]["target_term"] == "dragon"


def test_capability_full_chain_with_fake_translator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hevi.capabilities.longtranslate as lt_mod

    lt_mod.register_longtranslate_capabilities_once()
    monkeypatch.setattr(lt_mod, "_default_translate_fn", fake_translate)

    registered = {c.name: c for c in caps.list()}
    result = registered["text.translate_long"].render_safe(
        {
            "text": "星舰的船长出发了。\n\n他们望着远方的星辰。",
            "target_language": "English",
            "source_language": "简体中文",
            "glossary": {"星舰": "starship"},
        },
        tmp_path / "cap-tr",
        duration=0.0,
        aspect="16:9",
        seed=1,
    )
    assert result.sha256
    assert result.qa["chunk_count"] == 1
    assert result.qa["glossary_ok"] is True
    assert Path(result.qa["translated_txt"]).is_file()
    assert Path(result.qa["bilingual_json"]).is_file()
    translated = Path(result.qa["translated_txt"])
    translated.unlink()
    assert not translated.exists()


def test_input_file_path(tmp_path: Path) -> None:
    src = tmp_path / "source.txt"
    src.write_text("星舰出发了。", encoding="utf-8")
    report = translate_long(
        input_path=src,
        target_language="English",
        out_dir=tmp_path / "tr3",
        translate_fn=fake_translate,
    )
    assert report["chunk_count"] == 1
    assert "starship" in (tmp_path / "tr3" / "translated.txt").read_text(encoding="utf-8")

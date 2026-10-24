"""preflight 编译器测试：三种输出、可审结构、不编造缺失字段。"""

import json

import pytest

from hevi.preflight import Beat, CharacterRef, DialogueLine, compile_beat


def _beat(**kw):
    base = dict(
        beat_id="b7", kind="dialogue", scene="LIMU",
        text="谁能把这根木头，从南门扛到北门，赏五十金。",
        characters=[CharacterRef(char_id="C_wei", sheet_path="char_weiyang.jpg")],
        first_frame="beat07.jpg", duration_s=8.0, aspect="16:9",
    )
    base.update(kw)
    return Beat(**base)


def test_veo_fast_sections_and_no_text():
    out = compile_beat(_beat(), "veo_fast")
    assert "no text" in out.prompt_text.lower()
    assert "char_weiyang.jpg" in out.prompt_text
    assert "8 seconds" in out.sections["output_spec"]
    assert out.estimated_cost["amount"] == 20
    d = json.loads(json.dumps(out.to_dict(), ensure_ascii=False))
    assert d["sections"]["character_lock"]


def test_omni_flash_window_10s():
    out = compile_beat(_beat(), "omni_flash")
    assert "10 seconds" in out.sections["output_spec"]
    assert out.estimated_cost["amount"] == 15


def test_svi_film_stream_five_second_segments():
    long_beat = _beat(
        text="一根三丈来高的大木头，就这么立在都城南门的空地上。"
             "赏钱从十金一路加到五十金，人群围着，议论着，却没人敢上手。"
             "直到一个汉子将信将疑地扛起木头，一步步搬到了北门。",
    )
    out = compile_beat(long_beat, "svi_film")
    stream = out.sections["prompt_stream"]
    assert len(stream) >= 2
    assert all(s["duration_s"] == 5.0 for s in stream)
    assert stream[0]["start_s"] == 0.0
    assert out.estimated_cost["currency"] == "local-gpu"


def test_compiler_does_not_invent_missing_character():
    beat = _beat(characters=[CharacterRef(char_id="C_wei")])
    out = compile_beat(beat, "veo_fast")
    assert any("无定妆" in w or "no sheet" in w.lower() for w in out.warnings)
    assert "C_wei" in out.prompt_text


def test_compiler_unknown_model_raises():
    with pytest.raises(ValueError):
        compile_beat(_beat(), "no_such_model")


def test_registry_capabilities_present():
    import hevi.capabilities as caps  # noqa: F401 - 导入即触发注册钩子

    for name in ("preflight.gate", "preflight.compile", "preflight.passrate"):
        assert name in caps.names()

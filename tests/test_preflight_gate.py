"""preflight 门禁测试：黑名单作用域、无文字声明、对白适配、预算门、首帧硬查。"""

import pytest
from PIL import Image

from hevi.preflight import (
    Beat,
    CharacterRef,
    DialogueLine,
    audit_prompt,
    budget_gate,
    check_first_frame,
    estimate_cost,
    fit_dialogue,
    run_gate,
)


def _beat(**kw):
    base = dict(beat_id="b1", kind="dialogue", scene="BIAN",
                text="只要能让国家强，就不必死守古法。")
    base.update(kw)
    return Beat(**base)


def test_modern_vocab_scoped_to_narrative_segments():
    bad = _beat(text="这事儿整得人内卷了。")
    assert any(f.code == "modern_vocab" and f.level == "FAIL"
               for f in audit_prompt(bad))
    echo = _beat(kind="modern_echo", text="今天的团队也在内卷。")
    assert not any(f.code == "modern_vocab" and f.level == "FAIL"
                   for f in audit_prompt(echo))


def test_banned_latin_terms_match_word_boundary_only():
    # 回测实抓：编译器 AUDIO 段的 "spoken" 不许触发黑名单 "OK"。
    assert not any(f.code == "modern_vocab" for f in audit_prompt(
        _beat(), "AUDIO SPOKEN DIALOGUE (Mandarin Chinese, clear steady pace)"))
    # 独立出现的 OK 照旧拦。
    assert any(f.code == "modern_vocab" for f in audit_prompt(_beat(text="这事 OK 了")))


def test_no_text_clause_required_when_prompt_supplied():
    beat = _beat()
    assert any(f.code == "no_text_missing" for f in audit_prompt(beat, "a man speaks"))
    assert not any(f.code == "no_text_missing" for f in audit_prompt(
        beat, "a man speaks, no text, no subtitles, no watermark"))


def test_character_ref_weak_warns_not_blocks():
    beat = _beat(characters=[CharacterRef(char_id="C_wei")])
    findings = audit_prompt(beat)
    assert any(f.code == "character_ref_weak" and f.level == "WARN" for f in findings)
    assert not any(f.level == "FAIL" and f.code == "character_ref_weak" for f in findings)
    sheet_beat = _beat(characters=[CharacterRef(char_id="C_wei", sheet_path="char_weiyang.jpg")])
    assert not any(f.code == "character_ref_weak" for f in audit_prompt(sheet_beat))


def test_dialogue_fit_thresholds():
    ok = _beat(text="谁能把这根木头，从南门扛到北门，赏五十金。")  # 21 字
    assert any(f.code == "dialogue_fit_ok" for f in fit_dialogue(ok, "veo_fast"))
    fast = _beat(text="治理天下，从来没有一条一成不变的老路。只要能让国家强，就不必死守古法。当年商汤、周武没照搬旧规矩")  # 43 字，5.4 字／秒
    assert any(f.level == "WARN" for f in fit_dialogue(fast, "veo_fast"))
    over = _beat(text="治理天下，从来没有一条一成不变的老路。只要能让国家强，就不必死守古法。当年商汤、周武没照搬旧规矩，照样得了天下。")  # 75 字
    assert any(f.code == "dialogue_over_window" and f.level == "FAIL"
               for f in fit_dialogue(over, "veo_fast"))
    narration = _beat(kind="narration", text="战国那会儿，秦国窝在最西边，又穷又弱。" * 5)
    assert not any(f.level == "FAIL" for f in fit_dialogue(narration, "veo_fast"))


def test_dialogue_fit_multi_speaker_lines():
    beat = _beat(
        dialogue_lines=[
            DialogueLine("C_gan", "话不能这么说。顺着百姓的老习惯去教化，不费劲就能成；守着旧法度去治理，官吏熟、百姓也安稳。你这一改，天下人非议论纷纷不可。"),
            DialogueLine("C_gong", "好。就照你说的办。"),
        ],
        text="",
    )
    assert any(f.code == "dialogue_over_window" for f in fit_dialogue(beat, "veo_fast"))


def test_budget_monthly_blocks_daily_only_warns():
    est = estimate_cost("veo_fast", 8.0)
    assert est["amount"] == 20
    assert any(f.level == "FAIL" for f in budget_gate(
        est, {"monthly_remaining": 10, "daily_remaining": 50}))
    assert any(f.code == "budget_daily_grant_exceeded" for f in budget_gate(
        {"model": "veo_fast", "clips": 4, "amount": 80, "currency": "credits"},
        {"monthly_remaining": 970, "daily_remaining": 50}))
    assert any(f.code == "budget_ok" for f in budget_gate(
        est, {"monthly_remaining": 970, "daily_remaining": 50}))
    assert any(f.code == "budget_no_ledger" for f in budget_gate(est, None))
    usd = estimate_cost("pixstag", 8.0)
    assert usd["currency"] == "USD"
    assert any(f.code == "budget_usd_manual" for f in budget_gate(usd, None))


def test_first_frame_missing_and_aspect(tmp_path):
    beat = _beat(first_frame=str(tmp_path / "nope.jpg"))
    findings, _ = check_first_frame(beat)
    assert any(f.code == "first_frame_not_found" and f.level == "FAIL" for f in findings)

    img = tmp_path / "frame.jpg"
    Image.new("RGB", (1280, 720), (200, 100, 50)).save(img)
    beat_ok = _beat(first_frame=str(img))
    findings, checklist = check_first_frame(beat_ok)
    assert not any(f.level == "FAIL" for f in findings)
    assert len(checklist) == 3  # 人工目视三项必出

    tall = tmp_path / "tall.jpg"
    Image.new("RGB", (720, 1280), (10, 10, 10)).save(tall)
    beat_bad = _beat(first_frame=str(tall))
    assert any(f.code == "aspect_mismatch" for f in check_first_frame(beat_bad)[0])


def test_run_gate_blocks_and_override(tmp_path):
    over = _beat(text="治理天下，从来没有一条一成不变的老路。只要能让国家强，就不必死守古法。当年商汤、周武没照搬旧规矩，照样得了天下。")
    report = run_gate(over, "veo_fast", ledger={"monthly_remaining": 970, "daily_remaining": 50})
    assert report.verdict == "FAIL" and report.blocked is True
    report2 = run_gate(over, "veo_fast", ledger={"monthly_remaining": 970, "daily_remaining": 50},
                       allow_override=True, override_reason="人工确认拆镜后重发")
    assert report2.blocked is False and report2.override_reason != ""
    with pytest.raises(ValueError):
        run_gate(over, "no_such_model")


def test_run_gate_unknown_model_raises():
    with pytest.raises(ValueError):
        run_gate(_beat(), "no_such_model")

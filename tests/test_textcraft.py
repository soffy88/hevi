"""Contract tests for the textcraft capabilities (style + humanize).

Offline and deterministic: style transfer uses an injected fake rewrite
function, so no LLM, no key and no network are involved.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
import hevi.capabilities.textcraft as textcraft_caps
from hevi.capabilities.errors import CapabilityError
from hevi.textcraft.humanize import count_cliches, humanize_text
from hevi.textcraft.style import (
    extract_style_profile,
    profile_distance,
    style_transfer,
)

textcraft_caps.register_textcraft_capabilities_once()

FORMAL_SAMPLE = (
    "在当今社会，科学技术的发展日新月异，其影响已经渗透到社会生活的各个方面，"
    "并且在很大程度上改变了人们的生产方式以及生活方式，这是一个长期而复杂的过程，"
    "需要各个方面的共同努力才能够实现预期目标。与此同时，相关研究也在不断深入，"
    "为后续的实践工作提供了坚实的理论基础和可靠的数据支持。"
)

COLLOQUIAL_SAMPLE = (
    "你回来啦！今天累不累呀？先坐下歇会儿吧。茶在桌上呢，自己倒啊。"
    "对了，楼下新开了一家小面馆，味道真不错！明天咱们去尝尝呗？"
    "他家的辣椒油香得很，我昨天吃了一碗，还想再去呢。"
)

CLICHE_SAMPLE = (
    "值得注意的是，随着科技的不断发展，人工智能正在发挥着至关重要的作用。"
    "总而言之，我们目前需要立即采取行动，购买相关设备。"
    "综上所述，这无疑是一个具有重要的意义的决定，让我们一起努力吧！！"
)


# ---------------------------------------------------------------- registration


def test_textcraft_capabilities_registered_and_listable() -> None:
    names = caps.names()
    for expected in ("text.style_extract", "text.style_transfer", "text.humanize"):
        assert expected in names
    listed = [c.name for c in caps.list(kind="text")]
    for expected in ("text.style_extract", "text.style_transfer", "text.humanize"):
        assert expected in listed


def test_textcraft_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in ("text.style_extract", "text.style_transfer", "text.humanize"):
        assert expected in by_name
        assert by_name[expected].get("description"), expected


# ------------------------------------------------------------- style profiling


def test_extract_profile_fields_complete() -> None:
    profile = extract_style_profile(FORMAL_SAMPLE)
    for key in (
        "version",
        "char_count",
        "sentence_count",
        "paragraph_count",
        "sentence_len",
        "paragraph_len",
        "punctuation_per_1000",
        "punctuation_ratio",
        "function_words_per_1000",
        "modal_particles_per_1000",
        "exclamation_ratio",
        "question_ratio",
        "char_ttr",
    ):
        assert key in profile, key
    for key in ("mean", "std", "min", "max"):
        assert key in profile["sentence_len"], key
    assert profile["sentence_count"] >= 2
    assert profile["char_count"] > 0


def test_extract_profile_rejects_empty() -> None:
    with pytest.raises(ValueError):
        extract_style_profile("   ")


def test_profiles_distinguish_formal_from_colloquial() -> None:
    formal = extract_style_profile(FORMAL_SAMPLE)
    colloquial = extract_style_profile(COLLOQUIAL_SAMPLE)
    # Formal prose: longer sentences, no modal particles, no exclamations.
    assert formal["sentence_len"]["mean"] > colloquial["sentence_len"]["mean"]
    assert colloquial["modal_particles_per_1000"] > formal["modal_particles_per_1000"]
    assert colloquial["exclamation_ratio"] > formal["exclamation_ratio"]
    assert profile_distance(formal, colloquial) > 0
    assert profile_distance(formal, formal) == 0.0


def test_style_transfer_uses_injected_fn() -> None:
    profile = extract_style_profile(COLLOQUIAL_SAMPLE)
    seen: dict[str, object] = {}

    def fake_rewrite(text: str, prof: dict) -> str:
        seen["text"] = text
        seen["profile"] = prof
        return text + "（仿写版）"

    out = style_transfer("原始文本。", profile, fake_rewrite)
    assert out == "原始文本。（仿写版）"
    assert seen["text"] == "原始文本。"
    assert seen["profile"] is profile


def test_style_transfer_without_fn_raises() -> None:
    profile = extract_style_profile(COLLOQUIAL_SAMPLE)
    with pytest.raises(ValueError):
        style_transfer("原始文本。", profile, None)


# ------------------------------------------------------------------- humanize


def test_humanize_reduces_cliches_quantitatively() -> None:
    before = count_cliches(CLICHE_SAMPLE)
    assert before >= 5
    polished, report = humanize_text(CLICHE_SAMPLE)
    assert count_cliches(polished) == 0
    assert report["cliche_before"] == before
    assert report["cliche_after"] == 0
    assert report["by_category"]["cliche"] == before
    assert report["changes_total"] >= report["by_category"]["cliche"]
    assert "值得注意的是" not in polished
    assert "总而言之" not in polished


def test_humanize_splits_long_sentences() -> None:
    long_text = (
        "他把这件事情的前因后果原原本本地讲了一遍，从最初的起因开始讲起，"
        "一直讲到最后的结局为止，中间没有停顿也没有遗漏任何一个细节，"
        "听得在场的所有人都连连点头表示完全理解了他的意思。"
    )
    polished, report = humanize_text(long_text, max_sentence_len=30)
    assert report["by_category"]["sentence_split"] >= 1
    assert report["sentence_count_after"] > report["sentence_count_before"]
    assert report["max_sentence_len_after"] < report["max_sentence_len_before"]
    # No information lost: every original clause still present in some form.
    for clause in ("前因后果", "最后的结局", "连连点头"):
        assert clause in polished


def test_humanize_is_deterministic_and_idempotent_on_clean_text() -> None:
    clean = "他推开门，屋里很安静。她坐在窗边看书，抬头笑了一下。"
    out1, report1 = humanize_text(clean)
    out2, _ = humanize_text(clean)
    assert out1 == out2
    assert report1["changes_total"] == 0
    assert out1 == clean


def test_humanize_rejects_empty() -> None:
    with pytest.raises(ValueError):
        humanize_text("")


# ------------------------------------------------------------ capability layer


def test_style_extract_render_writes_profile(tmp_path: Path) -> None:
    cap = caps.get("text.style_extract")
    out_dir = tmp_path / "extract"
    result = cap.render_safe(
        {"text": FORMAL_SAMPLE}, out_dir, duration=1.0, aspect="16:9", seed=1
    )
    profile_path = Path(result.qa["profile_json"])
    assert profile_path.is_file()
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    assert payload == extract_style_profile(FORMAL_SAMPLE)
    assert result.sha256

    from hevi.capabilities.registry import compute_sha256

    assert result.sha256 == compute_sha256(profile_path)

    profile_path.unlink()
    assert not profile_path.exists(), "contract: deleting the artifact must break verification"


def test_humanize_render_writes_text_and_report(tmp_path: Path) -> None:
    cap = caps.get("text.humanize")
    out_dir = tmp_path / "humanize"
    result = cap.render_safe(
        {"text": CLICHE_SAMPLE}, out_dir, duration=1.0, aspect="16:9", seed=1
    )
    text_path = Path(result.qa["humanized_txt"])
    report_path = Path(result.qa["report_json"])
    assert text_path.is_file() and report_path.is_file()
    polished = text_path.read_text(encoding="utf-8")
    assert count_cliches(polished) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["changes_total"] == result.qa["changes_total"]
    assert result.qa["cliche_after"] == 0

    text_path.unlink()
    assert not text_path.exists(), "contract: deleting the artifact must break verification"


def test_style_transfer_render_with_fake_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_rewrite(text: str, profile: dict) -> str:
        return f"[{profile['sentence_count']}句风格]{text}"

    monkeypatch.setattr(textcraft_caps, "_REWRITE_FN", fake_rewrite)
    cap = caps.get("text.style_transfer")
    out_dir = tmp_path / "transfer"
    result = cap.render_safe(
        {"text": "要改写的句子。", "sample_text": COLLOQUIAL_SAMPLE},
        out_dir,
        duration=1.0,
        aspect="9:16",
        seed=5,
    )
    rewritten_path = Path(result.qa["rewritten_txt"])
    profile_path = Path(result.qa["profile_json"])
    assert rewritten_path.is_file() and profile_path.is_file()
    expected_profile = extract_style_profile(COLLOQUIAL_SAMPLE)
    assert rewritten_path.read_text(encoding="utf-8") == (
        f"[{expected_profile['sentence_count']}句风格]要改写的句子。"
    )
    assert json.loads(profile_path.read_text(encoding="utf-8")) == expected_profile
    assert result.qa["rewrite_backend"] == "fake_rewrite"

    rewritten_path.unlink()
    assert not rewritten_path.exists(), "contract: deleting the artifact must break verification"


def test_style_transfer_without_backend_raises_capability_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(textcraft_caps, "_REWRITE_FN", None)
    # No key either: the default Monid backend must stay out of this test
    # even on machines where a real key is in the environment.
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    cap = caps.get("text.style_transfer")
    with pytest.raises(CapabilityError) as excinfo:
        cap.render_safe(
            {"text": "句子。", "sample_text": COLLOQUIAL_SAMPLE},
            tmp_path / "transfer2",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    # The error names both routes: the injection point and the missing key.
    assert "set_rewrite_fn" in str(excinfo.value)
    assert "MONID_API_KEY" in str(excinfo.value)


def test_textcraft_rejects_invalid_params(tmp_path: Path) -> None:
    extract = caps.get("text.style_extract")
    with pytest.raises(CapabilityError):
        extract.render_safe({}, tmp_path / "a", duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        extract.render_safe(
            {"text": "x", "bogus": 1}, tmp_path / "b", duration=1.0, aspect="16:9", seed=1
        )

    humanize = caps.get("text.humanize")
    with pytest.raises(CapabilityError):
        humanize.render_safe(
            {"text": "x", "max_sentence_len": 3},  # below schema minimum
            tmp_path / "c",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )

    transfer = caps.get("text.style_transfer")
    with pytest.raises(CapabilityError):
        transfer.render_safe(
            {"text": "只有正文，没有样本也没有 profile。"},
            tmp_path / "d",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


# ------------------------------------------- default Monid backend (offline)


def test_style_transfer_default_backend_when_key_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No injection + MONID_API_KEY set -> Monid chat performs the rewrite."""
    from hevi.audio import monid_client

    seen: dict = {}

    async def fake_run_endpoint(provider, endpoint, *, body=None, **_kwargs):
        seen["provider"] = provider
        seen["endpoint"] = endpoint
        seen["body"] = body
        return ({"choices": [{"message": {"content": "改写后的口语版。"}}]}, 0.0004)

    monkeypatch.setattr(textcraft_caps, "_REWRITE_FN", None)
    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_client, "run_endpoint", fake_run_endpoint)

    cap = caps.get("text.style_transfer")
    out_dir = tmp_path / "transfer-default"
    result = cap.render_safe(
        {"text": "要改写的正式句子。", "sample_text": COLLOQUIAL_SAMPLE},
        out_dir,
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    rewritten_path = Path(result.qa["rewritten_txt"])
    assert rewritten_path.is_file()
    assert rewritten_path.read_text(encoding="utf-8") == "改写后的口语版。"
    assert result.qa["rewrite_backend"] == "_default_rewrite_fn"
    # Same route as story.film_from_prompt (blockrun chat, gpt-4o-mini).
    assert seen["provider"] == "blockrun.ai"
    assert seen["endpoint"] == "/api/v1/chat/completions"
    assert seen["body"]["model"] == "gpt-4o-mini"
    # The user message carries the style instructions + the source text.
    user_content = seen["body"]["messages"][-1]["content"]
    assert "要改写的正式句子。" in user_content


def test_style_transfer_injected_fn_wins_over_default_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import monid_client

    async def forbidden_run_endpoint(*_args, **_kwargs):
        raise AssertionError("default backend must not run when injected")

    def fake_rewrite(text: str, profile: dict) -> str:
        return "注入版改写。"

    monkeypatch.setattr(textcraft_caps, "_REWRITE_FN", fake_rewrite)
    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_client, "run_endpoint", forbidden_run_endpoint)

    cap = caps.get("text.style_transfer")
    result = cap.render_safe(
        {"text": "原文。", "sample_text": COLLOQUIAL_SAMPLE},
        tmp_path / "transfer-injected",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert (
        Path(result.qa["rewritten_txt"]).read_text(encoding="utf-8") == "注入版改写。"
    )
    assert result.qa["rewrite_backend"] == "fake_rewrite"

"""CosyVoice 参考音契约(cosy-ref-v1)回归测试。

根因: 生产路径(explainer 旁白 / voice_platform API / 各产品线 TTS)只把文本发给
/api/ai/cosyvoice, 而 CosyVoice zero_shot/cross_lingual/instruct 都需要参考音,
验收能过只是因为 acceptance proxy 在中间注入了参考音。这里锁定:
  * 纯文本请求 → 客户端自动带上仓库内置默认参考音 builtin:zh_default + prompt_text
  * 显式 voice_ref / ref_text 原样透传
  * 无参考音 → 显式 sft(配置了 spk_id)或清晰的 CosyVoiceContractError, 不打引擎
  * 引擎侧把 builtin: 解析为仓库内置 wav, 无参考音的行明确 422
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hevi.audio.cosyvoice_service import (
    AiEngineError,
    CosyVoiceContractError,
    cosyvoice_synthesize,
    resolve_cosy_script,
)
from hevi.voicepro.oprim.cosy_mode import (
    BUILTIN_VOICE_REFS,
    builtin_voice_ref,
    mode_requires_prompt_text,
    mode_requires_voice_ref,
    validate_cosy_row,
)
from hevi.voicepro.oskill.cosy_payload import bind_cosy_reference, resolve_cosy_reference
from hevi.voicepro.schemas import COSY_CONTRACT_VERSION, CosyContractError, CosyReference

REPO = Path(__file__).resolve().parents[1]
DEFAULT_TRANSCRIPT = BUILTIN_VOICE_REFS["zh_default"]["transcript"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HEVI_COSY_INFERENCE_MODE",
        "HEVI_COSY_DEFAULT_VOICE_REF",
        "HEVI_COSY_DEFAULT_REF_TEXT",
        "HEVI_COSY_BUILTIN_REF",
        "HEVI_COSY_SFT_SPEAKER",
    ):
        monkeypatch.delenv(name, raising=False)


def _fake_client() -> tuple[object, AsyncMock]:
    fake = AsyncMock()
    fake.post = AsyncMock(return_value=httpx.Response(200, content=b"RIFFfake"))
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    return patch("hevi.audio.cosyvoice_service.httpx.AsyncClient", return_value=fake), fake


async def _send(script: list[object], tmp_path: Path, **kwargs: object) -> dict:
    patcher, fake = _fake_client()
    with patcher:
        await cosyvoice_synthesize(script=script, output_path=tmp_path / "o.wav", **kwargs)
    return fake.post.await_args.kwargs["json"]


# ── 客户端: 纯文本 → 默认参考音 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_plain_text_request_gets_builtin_default_voice_ref(tmp_path: Path) -> None:
    body = await _send([SimpleNamespace(text="大家好,欢迎收看。")], tmp_path)
    row = body["script"][0]
    assert row["voice_ref"] == "builtin:zh_default"
    assert row["ref_text"] == DEFAULT_TRANSCRIPT
    assert row["prompt_text"] == DEFAULT_TRANSCRIPT
    assert row["inference_mode"] == "zero_shot"
    assert row["ref_source"] == "builtin"
    assert row["text"] == "大家好,欢迎收看。"  # 文本不加 CV3 前缀(引擎 worker 统一加)
    assert body["config"]["contract"] == COSY_CONTRACT_VERSION
    assert validate_cosy_row(row) == []


@pytest.mark.asyncio
async def test_default_voice_alias_and_env_mode_still_get_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEVI_COSY_INFERENCE_MODE", "zero_shot")
    body = await _send([SimpleNamespace(text="你好", voice_id="cosyvoice_default")], tmp_path)
    row = body["script"][0]
    assert row["voice_ref"] == "builtin:zh_default"
    assert row["inference_mode"] == "zero_shot"
    assert "voice_id" not in row


@pytest.mark.asyncio
async def test_explicit_voice_ref_is_passed_through(tmp_path: Path) -> None:
    body = await _send(
        [SimpleNamespace(text="第二段", voice_ref="/models/ref.wav", ref_text="参考转录")],
        tmp_path,
    )
    row = body["script"][0]
    assert row["voice_ref"] == "/models/ref.wav"
    assert row["ref_text"] == "参考转录"
    assert row["inference_mode"] == "zero_shot"
    assert row["ref_source"] == "request"


@pytest.mark.asyncio
async def test_explicit_voice_ref_without_transcript_uses_cross_lingual(tmp_path: Path) -> None:
    body = await _send([SimpleNamespace(text="hello", voice_ref="/models/ref.wav")], tmp_path)
    row = body["script"][0]
    assert row["voice_ref"] == "/models/ref.wav"
    assert row["inference_mode"] == "cross_lingual"
    assert "ref_text" not in row


@pytest.mark.asyncio
async def test_explicit_zero_shot_without_transcript_is_rejected(tmp_path: Path) -> None:
    patcher, fake = _fake_client()
    with patcher, pytest.raises(CosyVoiceContractError, match="ref_text"):
        await cosyvoice_synthesize(
            script=[
                SimpleNamespace(text="hi", voice_ref="/models/ref.wav", inference_mode="zero_shot")
            ],
            output_path=tmp_path / "o.wav",
        )
    fake.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_voice_id_resolves_to_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "hevi.audio.cosyvoice_service._catalog_lookup",
        lambda vid: ("/assets/yang-mi.wav", "目录转录") if vid == "yang-mi" else None,
    )
    body = await _send([SimpleNamespace(text="你好", voice_id="yang-mi")], tmp_path)
    row = body["script"][0]
    assert row["voice_ref"] == "/assets/yang-mi.wav"
    assert row["ref_text"] == "目录转录"
    assert row["ref_source"] == "catalog"


@pytest.mark.asyncio
async def test_identity_pack_voice_is_used(tmp_path: Path) -> None:
    body = await _send(
        [SimpleNamespace(text="臣有本奏")],
        tmp_path,
        config={
            "identity_voice": {
                "voice_ref_audio": "/pack/voice_8s.wav",
                "voice_ref_text": "李斯,冷峻。",
            }
        },
    )
    row = body["script"][0]
    assert row["voice_ref"] == "/pack/voice_8s.wav"
    assert row["ref_text"] == "李斯,冷峻。"
    assert row["ref_source"] == "identity"


# ── 无参考音: sft fallback / 清晰错误 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_no_reference_and_no_sft_raises_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEVI_COSY_BUILTIN_REF", "0")
    patcher, fake = _fake_client()
    with patcher, pytest.raises(CosyVoiceContractError, match="需要参考音") as info:
        await cosyvoice_synthesize(
            script=[SimpleNamespace(text="hi")], output_path=tmp_path / "o.wav"
        )
    fake.post.assert_not_awaited()
    # 既是 AiEngineError(调用方降级逻辑照常)又是 ValueError(API → 422)
    assert isinstance(info.value, AiEngineError)
    assert isinstance(info.value, ValueError)


@pytest.mark.asyncio
async def test_no_reference_falls_back_to_explicit_sft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEVI_COSY_BUILTIN_REF", "0")
    monkeypatch.setenv("HEVI_COSY_SFT_SPEAKER", "中文女")
    body = await _send([SimpleNamespace(text="你好")], tmp_path)
    row = body["script"][0]
    assert row["inference_mode"] == "sft"
    assert row["spk_id"] == "中文女"
    assert "voice_ref" not in row
    assert row["ref_source"] == "sft"


def test_explicit_sft_without_speaker_is_rejected() -> None:
    with pytest.raises(CosyVoiceContractError, match="spk_id"):
        resolve_cosy_script([{"text": "x", "inference_mode": "sft"}])


def test_strict_unknown_voice_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hevi.audio.cosyvoice_service._catalog_lookup", lambda _vid: None)
    with pytest.raises(CosyVoiceContractError, match="未知 CosyVoice 音色"):
        resolve_cosy_script([{"text": "x", "voice_id": "nobody"}], config={"strict_voice": True})
    # 非 strict(explainer 旁白): 未知音色回落内置默认参考音
    rows = resolve_cosy_script([{"text": "x", "voice_id": "Dylan"}])
    assert rows[0]["voice_ref"] == "builtin:zh_default"


def test_env_default_reference_beats_builtin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_COSY_DEFAULT_VOICE_REF", "/opt/refs/host.wav")
    monkeypatch.setenv("HEVI_COSY_DEFAULT_REF_TEXT", "主持人参考")
    row = resolve_cosy_script([{"text": "x"}])[0]
    assert (row["voice_ref"], row["ref_text"], row["ref_source"]) == (
        "/opt/refs/host.wav",
        "主持人参考",
        "env",
    )


# ── oprim / oskill 纯逻辑 ────────────────────────────────────────────────


def test_contract_validation_rules() -> None:
    assert mode_requires_voice_ref("zero_shot")
    assert mode_requires_voice_ref("cross_lingual")
    assert mode_requires_voice_ref("instruct")
    assert not mode_requires_voice_ref("sft")
    assert mode_requires_prompt_text("zero_shot")
    assert not mode_requires_prompt_text("cross_lingual")
    assert validate_cosy_row({"text": "x", "inference_mode": "zero_shot"}) == [
        "zero_shot 模式缺 voice_ref(参考音)",
        "zero_shot 模式缺 ref_text/prompt_text(参考音转录)",
    ]
    assert validate_cosy_row({"text": "x", "inference_mode": "instruct"}) == [
        "instruct 模式缺 voice_ref(参考音)"
    ]
    assert validate_cosy_row({"text": "x", "inference_mode": "sft"}) == [
        "sft 模式缺 spk_id(CosyVoice 内置说话人)"
    ]
    assert validate_cosy_row({"text": "x"}) == ["inference_mode 未解析(契约要求客户端显式给出)"]
    assert (
        "未知内置参考音"
        in validate_cosy_row(
            {"text": "x", "inference_mode": "cross_lingual", "voice_ref": "builtin:nope"}
        )[0]
    )


def test_resolver_priority_and_bind() -> None:
    assert builtin_voice_ref(None) == ("builtin:zh_default", DEFAULT_TRANSCRIPT)
    ref = resolve_cosy_reference(voice_ref="/a.wav", voice_id="yang-mi", allow_builtin=True)
    assert ref == CosyReference(source="request", voice_ref="/a.wav", ref_text=None)
    ref = resolve_cosy_reference(voice_ref="builtin:zh_default")
    assert ref.source == "builtin" and ref.ref_text == DEFAULT_TRANSCRIPT
    with pytest.raises(CosyContractError, match="未知内置参考音"):
        resolve_cosy_reference(voice_ref="builtin:nope")
    bound = bind_cosy_reference(
        row={"text": "x", "instruct_text": "用激动的语气"},
        reference=resolve_cosy_reference(),
    )
    assert bound["inference_mode"] == "instruct"
    assert bound["voice_ref"] == "builtin:zh_default"


# ── 引擎侧: builtin 解析 + 无参考音明确 422 ──────────────────────────────


def test_builtin_reference_asset_ships_in_repo() -> None:
    ref_dir = REPO / "services" / "gen_engine" / "assets" / "voice_refs"
    wav = ref_dir / "zh_default.wav"
    assert wav.is_file() and wav.stat().st_size > 10_000
    assert wav.read_bytes()[:4] == b"RIFF"
    assert (ref_dir / "zh_default.txt").read_text(encoding="utf-8").strip() == DEFAULT_TRANSCRIPT
    dockerignore = (REPO / ".dockerignore").read_text(encoding="utf-8")
    assert "!services/gen_engine/assets/voice_refs/*.wav" in dockerignore


def test_engine_resolves_builtin_reference_and_rejects_missing() -> None:
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    from services.gen_engine.ai_routes import _cosy_line_ready, _normalize_cosy_script

    rows = _normalize_cosy_script(
        [{"text": "你好", "voice_ref": "builtin:zh_default", "inference_mode": "zero_shot"}]
    )
    assert Path(rows[0]["voice_ref"]).is_file()
    assert rows[0]["ref_text"] == DEFAULT_TRANSCRIPT
    assert _cosy_line_ready(rows[0])
    assert not _cosy_line_ready({"text": "只有文本"})
    assert _cosy_line_ready({"text": "x", "inference_mode": "sft", "spk_id": "中文女"})
    with pytest.raises(HTTPException) as info:
        _normalize_cosy_script([{"text": "x", "voice_ref": "builtin:../../etc/passwd"}])
    assert info.value.status_code == 422
    cv3 = _normalize_cosy_script(
        [
            {
                "text": "x",
                "voice_ref": "/r.wav",
                "prompt_text": "You are a helpful assistant.<|endofprompt|>参考",
            }
        ]
    )
    assert cv3[0]["ref_text"] == "参考"


@pytest.mark.asyncio
async def test_engine_endpoint_rejects_text_only_line_with_clear_422(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    from services.gen_engine import ai_routes

    model_dir = tmp_path / "cosy"
    model_dir.mkdir()
    (model_dir / "cosyvoice3.yaml").write_text("x", encoding="utf-8")
    monkeypatch.setenv("COSYVOICE_MODEL_DIR", str(model_dir))
    with pytest.raises(HTTPException) as info:
        await ai_routes.synthesize_cosyvoice({"script": [{"text": "只有文本"}], "config": {}})
    assert info.value.status_code == 422
    assert "cosy-ref-v1" in str(info.value.detail)


# ── 生产调用方 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explainer_voiceover_sends_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.explainer.schemas import Storyboard
    from hevi.explainer.voiceover import synthesize_storyboard

    monkeypatch.setenv("HEVI_EXPLAINER_TTS_PROVIDER", "cosyvoice")
    monkeypatch.setattr("hevi.explainer.voiceover.asr_verification_enabled", lambda: False)
    monkeypatch.setattr("hevi.explainer.voiceover.probe_duration", lambda _path: 2.0)
    storyboard = Storyboard(
        topic="测试",
        segments=[
            {
                "id": "hook",
                "sceneType": "hook",
                "narration": "第一句。",
                "props": {"title": "t", "subtitle": "s", "items": [{"emoji": "💡", "label": "x"}]},
            }
        ],
    )
    patcher, fake = _fake_client()
    with patcher:
        await synthesize_storyboard(storyboard, tmp_path, voice="cosyvoice_default")
    row = fake.post.await_args.kwargs["json"]["script"][0]
    assert row["voice_ref"] == "builtin:zh_default"
    assert row["inference_mode"] == "zero_shot"


@pytest.mark.asyncio
async def test_voice_platform_engine_adapter_sends_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio.task_adapter import _synthesize_with_engine

    patcher, fake = _fake_client()
    with patcher:
        await _synthesize_with_engine(
            "cosyvoice",
            line=SimpleNamespace(text="平台合成"),
            output_path=tmp_path / "a.wav",
            config={
                "engine": "cosyvoice",
                "voice": "",
                "reference_audio": "",
                "reference_text": "",
            },
            emotion=None,
        )
    row = fake.post.await_args.kwargs["json"]["script"][0]
    assert row["voice_ref"] == "builtin:zh_default"

    monkeypatch.setattr("hevi.audio.cosyvoice_service._catalog_lookup", lambda _vid: None)
    with pytest.raises(CosyVoiceContractError, match="未知 CosyVoice 音色"):
        await _synthesize_with_engine(
            "cosyvoice",
            line=SimpleNamespace(text="平台合成"),
            output_path=tmp_path / "b.wav",
            config={"engine": "cosyvoice", "voice": "alloy"},
            emotion=None,
        )

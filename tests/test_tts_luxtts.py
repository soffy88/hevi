"""LuxTTS 引擎 + 注册表接线回归测试（mock HTTP，不联网）。

锁定：
  * synthesize 走 POST /tts，payload 带 text/voice/speed，wav 落盘
  * available() 探活 /health 的 ok:true 才算可用
  * **trust_env=False**：宿主机 http_proxy(本机 7890) 会把 tailnet 100.x 吃掉
    返回 502；no_proxy 写了 100.64.0.0/10 但 httpx 不解析 CIDR，必须显式绕开
  * 默认引擎是 piper：EngineConfig() 不传参 → "piper"（不改默认直播配置）
  * HEVI_LIVE_TTS=luxtts 在选择 luxtts 时包了 LuxTTSWithFallback
  * 服务不可达 / 合成期抖动 → 自动回退 fallback 引擎代合（直播不中断）
"""

from __future__ import annotations

import io
import json
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import hevi.live_host.oprim.tts_luxtts as luxtts_mod
from hevi.live_host.oprim.registry import EngineRegistry
from hevi.live_host.oprim.tts_luxtts import LuxTTS, LuxTTSWithFallback
from hevi.live_host.schemas import EngineConfig

Handler = Callable[[httpx.Request], httpx.Response]


def _wav_bytes(sr: int = 48000, frames: int = 4800) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


@pytest.fixture
def patch_transport(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], None]:
    """把 tts_luxtts 模块内的 ``httpx`` 名字换成走 MockTransport 的替身。

    只替换模块级名字（不动共享的 httpx 模块本体），因此测试内的 httpx.MockTransport
    仍是真身，不会自指递归。同时记录 trust_env，供 proxy 坑回归断言。
    """
    seen: dict = {"client_kwargs": None}

    def _client(*args, **kwargs):
        seen["client_kwargs"] = kwargs
        return httpx.Client(*args, **kwargs)

    def _get(url: str, **kwargs) -> httpx.Response:
        seen["get_kwargs"] = kwargs
        return httpx.get(url, **kwargs)

    def apply(handler: Handler) -> None:
        fake = SimpleNamespace(
            Client=lambda *a, **kw: _client(transport=httpx.MockTransport(handler), *a, **kw),
            get=lambda url, **kw: _get(url, transport=httpx.MockTransport(handler), **kw),
        )
        monkeypatch.setattr(luxtts_mod, "httpx", fake)

    # 挂上断言入口，用例可直接读 seen
    apply.seen = seen  # type: ignore[attr-defined]
    return apply  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HEVI_LIVE_TTS", "HEVI_LIVE_LUXTTS_URL", "HEVI_LIVE_LUXTTS_VOICE"):
        monkeypatch.delenv(name, raising=False)


# ── LuxTTS 原子 ────────────────────────────────────────────────


def test_synthesize_posts_tts_and_writes_wav(
    tmp_path: Path, patch_transport: Callable[[Handler], None]
) -> None:
    wav = _wav_bytes()
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, content=wav)

    patch_transport(handler)
    out = LuxTTS(base_url="http://tts.test:8795", voice="soffy", speed=1.25).synthesize(
        "你好呀", tmp_path / "o.wav"
    )

    assert out == tmp_path / "o.wav" and out.exists()
    assert seen["url"] == "http://tts.test:8795/tts"
    assert seen["json"] == {"text": "你好呀", "voice": "soffy", "speed": 1.25}
    assert out.read_bytes()[:4] == b"RIFF"
    assert out.stat().st_size == len(wav)


def test_synthesize_bypasses_http_proxy(
    tmp_path: Path, patch_transport: Callable[[Handler], None]
) -> None:
    """tailnet 100.x 必须 trust_env=False，否则被宿主机 7890 代理吞成 502。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_wav_bytes())

    seen = patch_transport.seen  # type: ignore[attr-defined]
    patch_transport(handler)
    LuxTTS(base_url="http://100.119.113.90:8795").synthesize("你好呀", tmp_path / "o.wav")

    assert seen["client_kwargs"]["trust_env"] is False
    assert "timeout" in seen["client_kwargs"]


def test_available_requires_health_ok_true(patch_transport: Callable[[Handler], None]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"ok": True, "voices": ["soffy", "en_male"]})

    seen = patch_transport.seen  # type: ignore[attr-defined]
    patch_transport(handler)
    assert LuxTTS(base_url="http://tts.test:8795").available() is True
    assert seen["get_kwargs"]["trust_env"] is False


def test_available_false_when_health_not_ok(patch_transport: Callable[[Handler], None]) -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False})

    patch_transport(handler)
    assert LuxTTS(base_url="http://tts.test:8795").available() is False


def test_available_false_when_unreachable() -> None:
    # 端口没人听 → ConnectError → False（不可达不应影响默认引擎）
    assert LuxTTS(base_url="http://127.0.0.1:59999").available() is False


def test_synthesize_raises_on_http_error(
    tmp_path: Path, patch_transport: Callable[[Handler], None]
) -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream dead")

    patch_transport(handler)
    with pytest.raises(RuntimeError, match="LuxTTS 合成失败 HTTP 500"):
        LuxTTS(base_url="http://tts.test:8795").synthesize("x", tmp_path / "o.wav")


def test_synthesize_raises_on_empty_body(
    tmp_path: Path, patch_transport: Callable[[Handler], None]
) -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    patch_transport(handler)
    with pytest.raises(RuntimeError, match="未产出音频"):
        LuxTTS(base_url="http://tts.test:8795").synthesize("x", tmp_path / "o.wav")


def test_defaults_are_female_voice_and_tailnet_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("HEVI_LIVE_LUXTTS_URL", "HEVI_LIVE_LUXTTS_VOICE"):
        monkeypatch.delenv(name, raising=False)
    eng = LuxTTS()
    assert eng.base_url == "http://100.119.113.90:8795"
    assert eng.voice == "soffy"  # 女声；en_male 不作小雅候选
    assert eng.name == "luxtts"


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_LIVE_LUXTTS_URL", "http://tts.test:9999")
    monkeypatch.setenv("HEVI_LIVE_LUXTTS_VOICE", "en_male")
    eng = LuxTTS()
    assert eng.base_url == "http://tts.test:9999"
    assert eng.voice == "en_male"


def test_base_url_trailing_slash_stripped() -> None:
    assert LuxTTS(base_url="http://tts.test:8795/").base_url == "http://tts.test:8795"


# ── 回退包装 ──────────────────────────────────────────────────


class _StubEngine:
    name = "stub"

    def __init__(self, ok: bool = True, data: bytes = b"RIFFfallback") -> None:
        self.ok = ok
        self.data = data
        self.calls: list[str] = []

    def available(self) -> bool:
        return self.ok

    def synthesize(self, text: str, output_path: str | Path) -> Path:
        self.calls.append(text)
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.data)
        return p


def test_fallback_used_when_primary_unreachable(tmp_path: Path) -> None:
    primary = LuxTTS(base_url="http://127.0.0.1:59999")  # 无人监听
    fb = _StubEngine()
    wrapped = LuxTTSWithFallback(primary, fb)

    out = wrapped.synthesize("你好呀", tmp_path / "o.wav")
    assert out.read_bytes() == b"RIFFfallback"
    assert fb.calls == ["你好呀"]
    assert wrapped.available() is True  # fallback 兜底，整体仍可用
    assert wrapped.name == "luxtts_fallback"


def test_fallback_clears_stale_output_before_fallback_writes(
    tmp_path: Path,
) -> None:
    """上一次失败可能留下半截 wav；回退前必须清掉，别把残file交给 lipsync。"""
    out = tmp_path / "o.wav"
    out.write_bytes(b"STALE" * 40)
    wrapped = LuxTTSWithFallback(LuxTTS(base_url="http://127.0.0.1:59999"), _StubEngine())

    result = wrapped.synthesize("你好呀", out)
    assert result.read_bytes() == b"RIFFfallback"


def test_primary_used_when_reachable(
    tmp_path: Path, patch_transport: Callable[[Handler], None]
) -> None:
    wav = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, content=wav)

    patch_transport(handler)
    fb = _StubEngine()
    out = LuxTTSWithFallback(LuxTTS(base_url="http://tts.test:8795"), fb).synthesize(
        "你好呀", tmp_path / "o.wav"
    )

    assert out.read_bytes()[:4] == b"RIFF" and out.stat().st_size == len(wav)
    assert fb.calls == []  # 没回退


def test_fallback_after_primary_raises_mid_synthesis(
    tmp_path: Path, patch_transport: Callable[[Handler], None]
) -> None:
    """合成期抖动（health 过但 POST 500）也要回退，不让直播断。"""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        state["n"] += 1
        return httpx.Response(500, text="boom")

    patch_transport(handler)
    fb = _StubEngine()
    wrapped = LuxTTSWithFallback(LuxTTS(base_url="http://tts.test:8795"), fb)
    out = wrapped.synthesize("你好呀", tmp_path / "o.wav")

    assert out.read_bytes() == b"RIFFfallback"
    assert fb.calls == ["你好呀"]
    assert state["n"] == 1  # 只试了一次 primary，没反复打已经挂掉的服务


def test_fallback_probes_again_after_outage_recovers(
    tmp_path: Path, patch_transport: Callable[[Handler], None]
) -> None:
    """服务恢复后应重新走 primary，不永久钉死在 fallback。"""
    up = {"v": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": up["v"]})
        if not up["v"]:
            return httpx.Response(500, text="down")
        return httpx.Response(200, content=_wav_bytes())

    patch_transport(handler)
    fb = _StubEngine()
    wrapped = LuxTTSWithFallback(LuxTTS(base_url="http://tts.test:8795"), fb)

    # 1) 挂 → 回退
    assert wrapped.synthesize("a", tmp_path / "a.wav").read_bytes() == b"RIFFfallback"
    # 2) 恢复了 → 重新用 primary
    up["v"] = True
    out = wrapped.synthesize("b", tmp_path / "b.wav")
    assert out.read_bytes()[:4] == b"RIFF" and out.stat().st_size > 44
    assert fb.calls == ["a"]


# ── 注册表 / 配置接线 ────────────────────────────────────────


def test_default_config_is_piper_not_luxtts() -> None:
    # 默认直播配置不改：未设 HEVI_LIVE_TTS → piper
    cfg = EngineConfig()
    assert cfg.tts == "piper"
    assert EngineRegistry(cfg).get("tts").name == "piper"
    assert "luxtts" not in str(cfg.to_dict()).replace("piper", "").split("piper")[0]


def test_registry_luxtts_is_wrapped_with_piper_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEVI_LIVE_TTS", "luxtts")
    cfg = EngineConfig()
    assert cfg.tts == "luxtts"
    eng = EngineRegistry(cfg).get("tts")
    assert isinstance(eng, LuxTTSWithFallback)
    assert eng.primary.name == "luxtts"
    assert eng.fallback.name == "piper"


def test_env_selects_luxtts_voice_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_LIVE_TTS", "luxtts")
    monkeypatch.setenv("HEVI_LIVE_LUXTTS_URL", "http://tts.test:9999")
    monkeypatch.setenv("HEVI_LIVE_LUXTTS_VOICE", "soffy")
    cfg = EngineConfig()
    assert cfg.luxtts_base_url == "http://tts.test:9999"
    assert cfg.luxtts_voice == "soffy"
    eng = EngineRegistry(cfg).get("tts")
    assert eng.primary.base_url == "http://tts.test:9999"
    assert eng.primary.voice == "soffy"


def test_explicit_tts_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_LIVE_TTS", "luxtts")
    assert EngineConfig(tts="piper").tts == "piper"


def test_explicit_luxtts_url_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_LIVE_LUXTTS_URL", "http://from-env:1")
    assert EngineConfig(luxtts_base_url="http://explicit:2").luxtts_base_url == "http://explicit:2"


def test_to_dict_carries_luxtts_fields() -> None:
    d = EngineConfig(tts="luxtts").to_dict()
    assert d["tts"] == "luxtts"
    assert d["luxtts_voice"] == "soffy"
    assert d["luxtts_base_url"] == "http://100.119.113.90:8795"


def test_registry_select_hot_switches_to_luxtts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_LIVE_TTS", "luxtts")
    cfg = EngineConfig()
    reg = EngineRegistry(cfg)
    reg.select("tts", "piper")
    assert reg.get("tts").name == "piper"
    reg.select("tts", "luxtts")
    assert cfg.tts == "luxtts"
    assert reg.get("tts").name == "luxtts_fallback"


def test_unknown_still_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest as _pytest

    monkeypatch.setenv("HEVI_LIVE_TTS", "luxtts")
    with _pytest.raises(KeyError):
        EngineRegistry(EngineConfig()).select("tts", "nope")


def test_stub_engines_are_not_used_by_registry() -> None:
    """registry 只从 factories 造引擎；防误把测试 stub 接进生产路径。"""
    reg = EngineRegistry(EngineConfig(tts="luxtts"))
    assert type(reg.get("tts")).__name__ == "LuxTTSWithFallback"


# ── 与 live loop 的调用面 ─────────────────────────────────────


def test_engine_satisfies_speak_call_site(tmp_path: Path) -> None:
    """skill_speak 只要 synthesize(text, path)->Path；包一层也满足。"""
    import inspect

    sig = inspect.signature(LuxTTSWithFallback.synthesize)
    assert list(sig.parameters) == ["self", "text", "output_path"]

"""F5-TTS 模型目录与多说话人台词解析。

对齐 Voice-Pro `abus_tts_f5_models.json` + `{spk1} line` 对话格式。
3O 归属(待上游): `oprim.f5_catalog`。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from hevi.voicepro.schemas import F5ModelSpec, SpeakerTurn

_DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "data" / "f5_models.json"
_CONV = re.compile(r"^\{(\w+)\}\s*(.*)$")
_LANG_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fi", ("finnish", "suomi")),
    ("fr", ("french", "francais")),
    ("hi", ("hindi",)),
    ("it", ("italian", "italiano")),
    ("ja", ("japanese", "ja_", "/ja")),
    ("ru", ("russian",)),
    ("es", ("spanish", "espanol")),
    ("zh", ("chinese", "zh")),
    ("en", ("f5-tts", "e2-tts")),
)


def infer_language(name: str) -> str:
    blob = name.lower()
    for lang, tokens in _LANG_HINTS:
        if any(token in blob for token in tokens):
            return lang
    return ""


def _spec_from_entry(name: str, raw: dict[str, object]) -> F5ModelSpec:
    return F5ModelSpec(
        name=name,
        model_path=str(raw.get("model_path") or ""),
        vocab_path=str(raw.get("vocab_path") or ""),
        config=dict(raw.get("config") or {}),  # type: ignore[arg-type]
        language=str(raw.get("language") or infer_language(name)),
    )


@lru_cache(maxsize=4)
def load_catalog(path: str | None = None) -> dict[str, F5ModelSpec]:
    catalog_path = Path(path) if path else _DEFAULT_CATALOG
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"F5 catalog must be an object: {catalog_path}")
    return {name: _spec_from_entry(name, raw or {}) for name, raw in data.items()}  # type: ignore[arg-type]


def list_models(path: str | None = None) -> list[str]:
    return list(load_catalog(path).keys())


def get_model(name: str, path: str | None = None) -> F5ModelSpec:
    catalog = load_catalog(path)
    if name not in catalog:
        raise KeyError(f"F5 model not in catalog: {name}")
    return catalog[name]


def pick_model_for_language(lang: str, path: str | None = None) -> F5ModelSpec:
    catalog = load_catalog(path)
    key = (lang or "").strip().lower()
    for spec in catalog.values():
        if spec.language == key:
            return spec
    # 默认 v1(Voice-Pro 单人页默认)
    if "SWivid/F5-TTS_v1" in catalog:
        return catalog["SWivid/F5-TTS_v1"]
    return next(iter(catalog.values()))


def parse_conversation(text: str) -> list[SpeakerTurn]:
    """`{spk1} hello` / `{spk2} hi` → 轮次。无标记则整段一个 host。"""
    turns: list[SpeakerTurn] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _CONV.match(stripped)
        if match:
            turns.append(SpeakerTurn(speaker=match.group(1), message=match.group(2).strip()))
        elif turns:
            prev = turns[-1]
            joined = f"{prev.message} {stripped}".strip()
            turns[-1] = SpeakerTurn(speaker=prev.speaker, message=joined)
        else:
            turns.append(SpeakerTurn(speaker="host", message=stripped))
    return turns

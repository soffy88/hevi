"""常用音色目录:名人参考音可检索、解析为 Cosy/F5 的 voice_ref。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG = Path(__file__).resolve().parent / "data" / "celeb_voices.json"
_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


@dataclass
class VoiceSpec:
    voice_id: str
    display: str
    language: str
    folder: str
    stem: str
    aliases: list[str] = field(default_factory=list)
    transcript: str = ""
    audio_path: str = ""
    image_path: str = ""

    @property
    def local(self) -> bool:
        return bool(self.audio_path) and Path(self.audio_path).exists()

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["local"] = self.local
        return body


def load_voice_index(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        return {}
    text = index_path.read_text(encoding="utf-8")
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def apply_index_transcripts(voices: list[VoiceSpec], index: dict[str, Any]) -> None:
    by_stem: dict[str, str] = {}
    for block in index.values():
        files = (block or {}).get("files") if isinstance(block, dict) else None
        if not files:
            continue
        for item in files:
            if not isinstance(item, dict):
                continue
            audio = str(item.get("audio_file") or "")
            stem = Path(audio).stem or str(item.get("display_name") or "")
            transcript = str(item.get("transcript") or "").strip()
            if stem and transcript:
                by_stem[stem.lower()] = transcript
    for spec in voices:
        hit = by_stem.get(spec.stem.lower()) or by_stem.get(spec.display.lower())
        if hit:
            spec.transcript = hit


def asset_root(override: str | Path | None = None) -> Path:
    import os

    if override:
        return Path(override)
    env = os.environ.get("HEVI_ASSET_ROOT", "").strip()
    return Path(env or "data/workspace/assets")


def pack_dir(pack: str = "celebrities30s", *, root: Path | None = None) -> Path:
    base = (root or asset_root()) / pack
    nested = base / pack
    if (nested / "Chinese").is_dir() or (nested / "English").is_dir():
        return nested
    return base


@lru_cache(maxsize=4)
def _raw_catalog(path: str | None = None) -> list[dict[str, Any]]:
    catalog_path = Path(path) if path else _CATALOG
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    return list(data.get("voices") or [])


def _first_existing(directory: Path, stem: str, exts: tuple[str, ...]) -> str:
    for ext in exts:
        candidate = directory / f"{stem}{ext}"
        if candidate.exists():
            return str(candidate)
    return ""


def _hydrate(raw: dict[str, Any], root: Path) -> VoiceSpec:
    folder = root / str(raw.get("folder") or "")
    stem = str(raw.get("stem") or raw.get("display") or "")
    return VoiceSpec(
        voice_id=str(raw["id"]),
        display=str(raw.get("display") or raw["id"]),
        language=str(raw.get("language") or ""),
        folder=str(raw.get("folder") or ""),
        stem=stem,
        aliases=[str(item) for item in (raw.get("aliases") or [])],
        transcript=str(raw.get("transcript") or ""),
        audio_path=_first_existing(folder, stem, _AUDIO_EXTS),
        image_path=_first_existing(folder, stem, _IMAGE_EXTS),
    )


def list_voices(
    *,
    language: str | None = None,
    local_only: bool = False,
    root: Path | None = None,
    catalog_path: str | None = None,
) -> list[VoiceSpec]:
    dest = pack_dir(root=root)
    items = [_hydrate(raw, dest) for raw in _raw_catalog(catalog_path)]
    index_path = dest / "celebrities30s.json5"
    if index_path.exists():
        apply_index_transcripts(items, load_voice_index(index_path))
    if language:
        key = language.strip().lower()
        alias = {"zh-cn": "zh", "cn": "zh", "eng": "en", "kor": "ko", "jpn": "ja"}
        key = alias.get(key, key)
        items = [item for item in items if item.language == key]
    if local_only:
        items = [item for item in items if item.local]
    return items


def find_voice(
    name: str,
    *,
    root: Path | None = None,
    catalog_path: str | None = None,
) -> VoiceSpec | None:
    needle = (name or "").strip().lower()
    if not needle:
        return None
    for spec in list_voices(root=root, catalog_path=catalog_path):
        names = [spec.voice_id, spec.display, spec.stem, *spec.aliases]
        if any(needle == item.lower() for item in names if item):
            return spec
    return None


def resolve_voice(name: str, *, root: Path | None = None) -> VoiceSpec:
    spec = find_voice(name, root=root)
    if spec is None:
        raise KeyError(f"unknown voice: {name}")
    if not spec.local:
        raise FileNotFoundError(
            f"voice '{spec.display}' not pulled; call asset.pull pack=celebrities30s"
        )
    return spec

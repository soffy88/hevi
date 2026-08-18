"""常用资产包:HuggingFace zip / 本地拷贝 / 公开域种子片。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

from hevi.studio.assets import bind_asset
from hevi.studio.voices import (
    apply_index_transcripts,
    asset_root,
    list_voices,
    load_voice_index,
    pack_dir,
)

logger = logging.getLogger(__name__)

_PACKS = Path(__file__).resolve().parent / "data" / "asset_packs.json"
FetchFn = Callable[[str, str, Path], Path]
_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a"}
_FONT_EXTS = {".ttf", ".otf"}


def list_packs(path: str | None = None) -> dict[str, dict[str, Any]]:
    pack_path = Path(path) if path else _PACKS
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    return {str(key): dict(value) for key, value in data.items()}


def _default_fetch(repo: str, filename: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download

        cached = hf_hub_download(repo_id=repo, filename=filename)
        shutil.copy(cached, dest)
        return dest
    except Exception as exc:
        logger.info("hf_hub_download failed, try HTTPS: %s", exc)
    url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
    urlretrieve(url, dest)
    return dest


@dataclass
class PackResult:
    pack: str
    dest: str
    pulled: int = 0
    kind: str = ""
    voices: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack": self.pack,
            "dest": self.dest,
            "pulled": self.pulled,
            "kind": self.kind,
            "voices": self.voices,
            "items": self.items,
            "reason": self.reason,
        }


def _flatten_nested_pack(dest: Path, pack: str) -> None:
    """zip 顶层多一层同名目录时提到 dest 下。"""
    nested = dest / pack
    markers = ("Chinese", "English", "clips", "mp3")
    if not any((nested / name).exists() for name in markers):
        return
    for child in nested.iterdir():
        target = dest / child.name
        if target.exists():
            continue
        child.rename(target)
    with contextlib.suppress(OSError):
        nested.rmdir()


def _bind(kind: str, label: str, payload: dict[str, Any], asset_id: str) -> None:
    bind_asset(kind, line_id="asset_pack", label=label, payload=payload, asset_id=asset_id)


def _pull_hf_zip(
    pack: str,
    spec: dict[str, Any],
    dest: Path,
    *,
    fetch_fn: FetchFn | None,
    force: bool,
) -> PackResult:
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / str(spec["filename"])
    has_files = any(dest.rglob("*.mp3")) or any(dest.rglob("*.wav")) or any(dest.rglob("*.json"))
    if force or not has_files:
        (fetch_fn or _default_fetch)(str(spec["repo"]), str(spec["filename"]), zip_path)
        if zip_path.exists():
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(dest)
            _flatten_nested_pack(dest, pack)
    if spec.get("index_file"):
        return _index_celebrities(pack, spec, dest)
    return _index_loose_files(pack, spec, dest)


def _index_celebrities(pack: str, spec: dict[str, Any], dest: Path) -> PackResult:
    index_name = str(spec.get("index_file") or "")
    index_path = dest / index_name
    if index_name and not index_path.exists():
        nested = dest / pack / index_name
        if nested.exists():
            index_path = nested
    index = load_voice_index(index_path) if index_name else {}
    catalog_root = dest / pack if (dest / pack / "Chinese").is_dir() else dest
    voices = list_voices(root=catalog_root.parent)
    apply_index_transcripts(voices, index)
    rows: list[dict[str, Any]] = []
    for voice in voices:
        if not voice.local:
            continue
        _bind("voice", voice.display, voice.to_dict(), f"voice:{voice.voice_id}")
        rows.append(voice.to_dict())
    return PackResult(pack=pack, dest=str(dest), pulled=len(rows), kind="voice", voices=rows)


def _index_loose_files(pack: str, spec: dict[str, Any], dest: Path) -> PackResult:
    kind = str(spec.get("kind") or "material")
    items: list[dict[str, Any]] = []
    for path in sorted(dest.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _AUDIO_EXTS | _FONT_EXTS | {".json"}:
            continue
        if path.name.endswith(".zip"):
            continue
        payload = {"path": str(path), "pack": pack, "suffix": path.suffix}
        asset_kind = "voice" if path.suffix.lower() in _AUDIO_EXTS else kind
        if asset_kind not in {"voice", "font", "bgm", "motion", "material"}:
            asset_kind = "material"
        _bind(asset_kind, path.stem, payload, f"{pack}:{path.name}")
        items.append(payload)
    return PackResult(
        pack=pack,
        dest=str(dest),
        pulled=len(items),
        kind=kind,
        items=items,
        voices=items if kind == "voice" else [],
    )


def _resolve_copy_files(spec: dict[str, Any]) -> list[Path]:
    roots = [Path(item) for item in (spec.get("roots") or [])]
    include = [str(item) for item in (spec.get("include") or ["*"])]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in include:
            if "/" in pattern or "*" in pattern:
                found.extend(p for p in root.glob(pattern) if p.is_file())
            else:
                hit = root / pattern
                if hit.is_file():
                    found.append(hit)
        if found:
            break
    return found


def _pull_copy(pack: str, spec: dict[str, Any], dest: Path) -> PackResult:
    dest.mkdir(parents=True, exist_ok=True)
    files = _resolve_copy_files(spec)
    if not files:
        return PackResult(
            pack=pack,
            dest=str(dest),
            kind=str(spec.get("kind") or "material"),
            reason="copy source missing",
        )
    items: list[dict[str, Any]] = []
    for src in files:
        rel = src.name
        target = dest / "clips" / src.name if src.parent.name == "clips" else dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or src.stat().st_mtime > target.stat().st_mtime:
            shutil.copy2(src, target)
        payload = {"path": str(target), "source": str(src), "pack": pack}
        kind = str(spec.get("kind") or "material")
        _bind(kind, target.stem, payload, f"{pack}:{target.name}")
        items.append(payload)
    mirror = str(spec.get("mirror") or "")
    if mirror:
        mirror_dir = Path(mirror)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            src = Path(item["path"])
            if src.suffix.lower() in _AUDIO_EXTS:
                shutil.copy2(src, mirror_dir / src.name)
    return PackResult(
        pack=pack,
        dest=str(dest),
        pulled=len(items),
        kind=str(spec.get("kind") or "material"),
        items=items,
    )


def _pull_corpus_seed(pack: str, spec: dict[str, Any], dest: Path) -> PackResult:
    from hevi.studio.corpus_seed import seed_open_corpus

    dest.mkdir(parents=True, exist_ok=True)
    queries = list(spec.get("queries") or [])
    try:
        added = asyncio.run(
            seed_open_corpus(
                dest,
                queries,
                max_each=int(spec.get("max_each") or 2),
                max_mb=int(spec.get("max_mb") or 25),
            )
        )
    except RuntimeError:
        # already in an event loop
        added = []
        reason = "event loop running; call seed_open_corpus directly"
        return PackResult(pack=pack, dest=str(dest), kind="corpus", reason=reason)
    for rec in added:
        _bind("corpus", str(rec.get("title") or rec.get("clip_id")), rec, str(rec.get("clip_id")))
    return PackResult(
        pack=pack,
        dest=str(dest),
        pulled=len(added),
        kind="corpus",
        items=added,
        reason="" if added else "no clips downloaded",
    )


def pull_pack(
    pack: str = "celebrities30s",
    *,
    root: Path | str | None = None,
    fetch_fn: FetchFn | None = None,
    force: bool = False,
) -> PackResult:
    packs = list_packs()
    spec = packs.get(pack)
    if spec is None:
        raise KeyError(f"unknown pack: {pack}")
    dest = pack_dir(pack, root=Path(root) if root else asset_root())
    dest.mkdir(parents=True, exist_ok=True)
    source = str(spec.get("source") or "hf_zip")
    if source == "copy":
        return _pull_copy(pack, spec, dest)
    if source == "archive_seed":
        return _pull_corpus_seed(pack, spec, dest)
    return _pull_hf_zip(pack, spec, dest, fetch_fn=fetch_fn, force=force)

"""media_use 真实 provider 链组装(3O 内化 Round 3g)。

把 media_use.resolve_media 的 provider 链接上 hevi 真实零件(此前 CLI 明示
"agent 注入真实 provider 链后调用" = 一直没接):

  local   bgm/sfx → hevi.audio.bgm_library.BGMLibrary(同步,文件库)
          grade/lut → hevi.motion.color_grade 预设/.cube 目录
  stock   image/video → Pexels/Pixabay/Coverr/Archive 检索 + 本地冻结缓存
  generate voice → edge-tts 同步包装(子进程/缓存;失败降级 None)

全部 provider 都是 (intent) -> Path | None,内部 try/except 保证单点失败不阻断链。
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import httpx

from hevi.sourcing.media_use import MediaProviders

logger = logging.getLogger(__name__)


def _bgm_local(intent: str) -> Path | None:
    """BGM 本地库:按 mood 关键词/路径命中。"""
    try:
        from hevi.audio.bgm_library import BGMLibrary

        library = BGMLibrary()
        return library.select_bgm(intent.strip() or None)
    except Exception as e:
        logger.warning("media_providers.bgm: %s", e)
        return None


def _sfx_local(intent: str) -> Path | None:
    """SFX 本地库:按名称关键词命中。"""
    try:
        from hevi.audio.bgm_library import BGMLibrary

        library = BGMLibrary()
        for token in intent.replace(" ", "").split("/"):
            hit = library.get_sfx(token)
            if hit is not None:
                return hit
        return None
    except Exception as e:
        logger.warning("media_providers.sfx: %s", e)
        return None


def _voice_generate(intent: str) -> Path | None:
    """voice → edge-tts 合成(同步包装;失败降级 None)。"""
    try:
        from edge_tts import Communicate

        out = Path(tempfile.gettempdir()) / f"hevi_voice_{abs(hash(intent)) % 100000}.mp3"
        if out.exists():
            return out
        # 缓存路径不存在才合成;语言按 CJK 启发
        language = "zh-CN" if any("\u4e00" <= ch <= "\u9fff" for ch in intent) else "en-US"
        voice = "zh-CN-XiaoxiaoNeural" if language == "zh-CN" else "en-US-JennyNeural"

        async def _synth() -> None:
            comm = Communicate(intent[:200], voice)
            await comm.save(str(out))

        import asyncio

        asyncio.run(_synth())
        return out if out.exists() else None
    except Exception as e:
        logger.warning("media_providers.voice: %s", e)
        return None


def _grade_local(intent: str) -> Path | None:
    """grade → 内置分级预设(无文件,返回一个伪 manifest 供下游读参数)。"""
    try:
        from hevi.motion.color_grade import grade_preset_by_name

        for preset in ("neutral", "warm_film", "cool_tech", "retro_dv", "bw_cinema"):
            if preset in intent:
                grade_preset_by_name(preset)
                out = Path(tempfile.gettempdir()) / f"hevi_grade_{preset}.json"
                import json

                out.write_text(
                    json.dumps(grade_preset_by_name(preset).to_dict(), ensure_ascii=False)
                )
                return out
        return None
    except Exception as e:
        logger.warning("media_providers.grade: %s", e)
        return None


def _lut_local(intent: str) -> Path | None:
    """lut → 用户/目录 .cube(本地 assets/luts/*.cube 检索)。"""
    lut_dir = Path("assets/luts")
    if not lut_dir.exists():
        return None
    for cube in lut_dir.glob("*.cube"):
        if any(token in cube.stem for token in intent.replace(" ", "").split("/") if token):
            return cube
    return None


def _image_stock(intent: str) -> Path | None:
    """image → Pexels 检索并下载为本地冻结文件。

    ``stock_search`` 面向异步 API/许可证数据库；media-use 是同步 provider 契约，
    因此这里直接使用 Pexels search 接口，并把远程结果落入统一缓存。不能只把
    ``src`` URL 交给下游，否则产物会依赖远端可用性。
    """
    try:
        api_key = _configured_value("PEXELS_API_KEY")
        if not api_key:
            return None

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(
                "https://api.pexels.com/v1/search",
                params={"query": intent, "per_page": 10},
                headers={"Authorization": api_key},
            )
            response.raise_for_status()
            photos = response.json().get("photos", [])
            for photo in photos:
                src = photo.get("src") if isinstance(photo, dict) else None
                if not isinstance(src, dict):
                    continue
                image_url = next(
                    (
                        src.get(name)
                        for name in ("large2x", "large", "original", "medium")
                        if isinstance(src.get(name), str) and src.get(name)
                    ),
                    "",
                )
                if image_url:
                    cached = _download_cached(image_url, _cache_dir(), ".jpg", client)
                    if cached is not None:
                        _write_source_manifest(
                            cached,
                            {
                                "provider": "pexels",
                                "asset_id": photo.get("id"),
                                "source_page": photo.get("url"),
                                "photographer": photo.get("photographer"),
                            },
                        )
                        return cached
        return None
    except Exception as e:
        logger.warning("media_providers.image: %s", e)
        return None


def _configured_value(name: str) -> str:
    """Read a provider value from the process environment.

    The API/CLI loads ``.env`` before composing providers. Avoid importing the
    full Pydantic settings object here: its fail-fast JWT validation is correct
    for the API process but would make an optional stock provider terminate a
    standalone media resolve command.
    """

    return os.getenv(name, "").strip()


def _cache_dir() -> Path:
    configured = os.getenv("MATERIAL_CACHE_DIR", "").strip()
    return Path(configured or "data/material_cache")


def _download_cached(
    url: str,
    cache_dir: Path,
    suffix: str,
    client: httpx.Client,
) -> Path | None:
    """Download one remote asset atomically and return only a non-empty path."""

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    target = cache_dir / f"{digest}{suffix}"
    if target.is_file() and target.stat().st_size > 0:
        return target
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes(65536):
                    handle.write(chunk)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            return None
        tmp.replace(target)
        return target if target.is_file() and target.stat().st_size > 0 else None
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("media download failed (%s): %s", url, exc)
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        return None


def _write_source_manifest(path: Path, metadata: dict[str, object]) -> None:
    """Persist non-secret stock provenance beside a frozen asset."""

    manifest = path.with_suffix(path.suffix + ".source.json")
    tmp = manifest.with_suffix(manifest.suffix + ".part")
    try:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        previous: dict[str, object] = {}
        if manifest.is_file():
            with suppress(OSError, ValueError, json.JSONDecodeError):
                raw = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    previous = raw
        enriched = {
            **metadata,
            "downloaded_at": previous.get(
                "downloaded_at", datetime.now(UTC).isoformat(timespec="seconds")
            ),
            "sha256": digest,
            "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "size": path.stat().st_size,
            "local_artifact_id": digest,
            "local_path": str(path.resolve()),
        }
        tmp.write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
        tmp.replace(manifest)
    except (TypeError, ValueError, OSError) as exc:
        logger.warning("stock provenance write failed (%s): %s", path, exc)
        with suppress(OSError):
            tmp.unlink(missing_ok=True)


def _video_stock(intent: str) -> Path | None:
    """Search stock sources and freeze the first usable video locally."""

    try:
        from hevi.video.material_corpus import (
            dedupe,
            ensure_cached,
            rank_by_keywords,
            search_all,
        )

        pexels_key = _configured_value("PEXELS_API_KEY")
        pixabay_key = _configured_value("PIXABAY_API_KEY")
        coverr_key = _configured_value("COVERR_API_KEY")
        lowered = intent.lower()
        target_aspect = (
            "9:16" if any(token in lowered for token in ("9:16", "竖", "portrait")) else ""
        )
        if any(token in lowered for token in ("16:9", "横", "landscape")):
            target_aspect = "16:9"

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            items = search_all(
                intent,
                pexels_key=pexels_key,
                pixabay_key=pixabay_key,
                coverr_key=coverr_key,
                include_archive=True,
                per_source=5,
                client=client,
            )
            ranked = rank_by_keywords(dedupe(items), intent, target_aspect=target_aspect)
            for item in ranked:
                cached = ensure_cached(item, _cache_dir(), client=client)
                if cached.cached_path:
                    path = Path(cached.cached_path)
                    if path.is_file() and path.stat().st_size > 0:
                        _write_source_manifest(
                            path,
                            {
                                "provider": item.source,
                                "asset_id": item.id,
                                "source_page": item.page_url,
                                "title": item.title,
                                "width": item.width,
                                "height": item.height,
                                "duration_s": item.duration_s,
                            },
                        )
                        return path
        return None
    except Exception as exc:
        logger.warning("media_providers.video: %s", exc)
        return None


def default_providers() -> MediaProviders:
    """真实 provider 链(local 为主,stock/generate 按环境可用性)。"""
    return {
        "bgm": {"local": _bgm_local},
        "sfx": {"local": _sfx_local},
        "voice": {"generate": _voice_generate},
        "grade": {"local": _grade_local},
        "lut": {"local": _lut_local},
        "image": {"stock": _image_stock},
        "video": {"stock": _video_stock},
    }

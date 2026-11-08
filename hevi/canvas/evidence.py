"""Real-material evidence sourcing for the koubo canvas graph.

One evidence node per sentence asks for a photo that illustrates that sentence:

1. Pexels photo search (the same ``hevi.collage_broll.assets`` request path used
   by S2, only extended to keep the photo's real provenance);
2. if Pexels is unavailable, a Playwright screenshot of a relevant public page
   (reusing ``hevi.motion.page_capture.capture_page_assets``);
3. if both fail, the segment is skipped and reported as ``warn`` (yellow) with
   the reason — never a fake picture labelled as Pexels.

The card footer therefore names the real source: the Pexels photographer or the
page domain.  Relevance is judged by ``judge_relevance``: a vision/LLM backend
when one is supplied, otherwise the photo's own alt text/tags.  Undecidable is
``None`` (yellow), not a silent pass.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

# Chinese sentence → English stock query.  Pexels indexes English; a direct
# Chinese query returns little.  This small map covers the demo topics, then
# falls back to the topic and finally to a neutral query.
_QUERY_MAP: tuple[tuple[str, str], ...] = (
    ("人工智能", "artificial intelligence technology"),
    ("AI", "artificial intelligence technology"),
    ("视频", "video production camera"),
    ("剪辑", "video editing timeline"),
    ("创作", "creative work desk"),
    ("未来", "futuristic technology"),
    ("科技", "technology circuit"),
    ("电脑", "laptop computer desk"),
    ("手机", "smartphone in hand"),
    ("网络", "network data server"),
    ("数据", "data analytics screen"),
    ("工作", "person working office"),
    ("学习", "student studying books"),
    ("咖啡", "coffee cup table"),
    ("城市", "city skyline street"),
    ("自然", "nature landscape"),
    ("山", "mountain landscape"),
    ("海", "ocean sea waves"),
    ("猫", "orange cat sitting"),
    ("狗", "dog portrait"),
    ("音乐", "music studio headphones"),
    ("旅行", "travel landscape road"),
    ("美食", "food cooking table"),
    ("运动", "running sport outdoor"),
    ("人", "portrait person thinking"),
    ("办公室", "modern office workspace"),
    ("工厂", "factory industrial machine"),
    ("汽车", "car on road"),
    ("太空", "space stars galaxy"),
    ("地球", "planet earth from space"),
)

_STOPWORDS = frozenset(
    ["the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "is", "are", "was", "were", "be", "been", "this", "that", "from", "as", "it", "its", "into", "about", "over", "under", "very", "just"]
)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", (text or "").lower())
        if token not in _STOPWORDS
    }


def query_for_sentence(sentence: str, topic: str = "") -> str:
    """Deterministic English stock query for a Chinese/English sentence."""
    text = f"{sentence} {topic}".strip()
    lowered = text.lower()
    for needle, query in _QUERY_MAP:
        if needle.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])", lowered):
                return query
        elif needle.lower() in lowered:
            return query
    # ASCII words already in the sentence are a usable query.
    ascii_words = re.findall(r"[A-Za-z]{3,}", text)
    if ascii_words:
        return " ".join(ascii_words[:4]).lower()
    return "abstract background texture"


def source_label(meta: dict[str, Any]) -> str:
    """Footer text that names the real source (never a generic stock claim)."""
    provider = str(meta.get("provider") or "")
    if provider == "pexels":
        photographer = str(meta.get("photographer") or "").strip()
        if photographer:
            return f"来源：Pexels · 摄影 {photographer} · 本片口播讲稿"
        return "来源：Pexels · 本片口播讲稿"
    if provider == "web":
        domain = str(meta.get("domain") or "").strip()
        if domain:
            return f"来源：网页截图 {domain} · 本片口播讲稿"
        return "来源：网页截图 · 本片口播讲稿"
    return "来源：未取得外部素材 · 本片口播讲稿"


def _vision_relevance(sentence: str, image_path: str, backend: Any) -> bool | None:
    if backend is None or not hasattr(backend, "available") or not backend.available():
        return None
    prompt = (
        "Look at the supplied image. Does it plausibly illustrate the sentence "
        "below? Answer with strict JSON only: "
        '{"relevant": true|false, "reason": "short"}\n\n'
        f"Sentence: {sentence}"
    )
    try:
        result = backend.run(image_path, prompt, timeout_s=120)
    except Exception:
        return None
    raw = getattr(result, "raw", None)
    if isinstance(raw, dict) and "relevant" in raw:
        return bool(raw.get("relevant"))
    text = str(getattr(result, "text", "") or "")
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            if "relevant" in data:
                return bool(data["relevant"])
        except Exception:
            pass
    return None


def judge_relevance(
    sentence: str,
    item: dict[str, Any],
    *,
    vision_backend: Any = None,
) -> bool | None:
    """True / False / None (cannot judge offline) for one evidence item."""
    image_path = str(item.get("path") or "")
    if image_path and vision_backend is not None:
        verdict = _vision_relevance(sentence, image_path, vision_backend)
        if verdict is not None:
            return verdict
    meta = item.get("meta") or {}
    query = str(item.get("query") or "")
    haystack = " ".join(
        str(part) for part in (meta.get("alt"), meta.get("title"), meta.get("tags"))
    )
    hay_tokens = _tokens(haystack)
    query_tokens = _tokens(query)
    if not hay_tokens or not query_tokens:
        return None
    if hay_tokens & query_tokens:
        return True
    # A well-described photo that shares nothing with the query is the only
    # offline signal we trust as "not relevant".
    if len(hay_tokens) >= 3:
        return False
    return None


def _web_screenshot(query: str, out_path: Path) -> dict[str, Any] | None:
    """Screenshot a public search page that matches the sentence query."""
    from hevi.motion.page_capture import capture_page_assets

    url = "https://en.wikipedia.org/w/index.php?search=" + quote(query)
    executable = (
        os.environ.get("HEVI_PLAYWRIGHT_CHROME", "").strip()
        or os.environ.get("HEVI_LIVLIV_CHROME", "").strip()
        or None
    )
    try:
        asset = capture_page_assets(
            url,
            out_path.parent,
            viewport=(1080, 1920),
            device_scale_factor=1.0,
            fullpage=False,
            timeout_ms=20_000,
            executable_path=executable,
            launch_args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
    except Exception:
        return None
    shot = Path(asset.fullpage_path)
    if not shot.is_file() or shot.stat().st_size == 0:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_bytes(shot.read_bytes())
    except OSError:
        return None
    return {
        "path": str(out_path),
        "provider": "web",
        "query": query,
        "url": url,
        "domain": urlparse(url).netloc,
        "alt": "",
        "tags": "",
        "license": "web page screenshot (fair-use reference frame)",
    }


def fetch_for_sentence(
    sentence: str,
    *,
    topic: str = "",
    out_dir: Path,
    pick: int = 0,
    allow_web: bool = True,
    query: str | None = None,
) -> dict[str, Any]:
    """Return one evidence item; ``ok=False`` means skip the segment."""
    q = query or query_for_sentence(sentence, topic)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{pick}" if pick else ""
    photo_path = out_dir / f"evidence{suffix}.jpg"
    meta: dict[str, Any] | None = None
    try:
        from hevi.collage_broll.assets import pexels_photo_meta

        meta = pexels_photo_meta(q, photo_path, "portrait", per_page=8, pick=pick)
    except Exception:
        meta = None
    if meta is None and allow_web:
        meta = _web_screenshot(q, out_dir / f"evidence_web{suffix}.png")
    if meta is None:
        return {
            "ok": False,
            "path": "",
            "query": q,
            "sentence": sentence,
            "skipped_reason": "Pexels/网页截图均未取得可用素材",
            "meta": {},
            "source_label": source_label({}),
        }
    item = {
        "ok": True,
        "path": str(meta.get("path") or ""),
        "query": q,
        "sentence": sentence,
        "meta": meta,
        "source_label": source_label(meta),
        "skipped_reason": "",
    }
    item["relevant"] = judge_relevance(sentence, item)
    return item

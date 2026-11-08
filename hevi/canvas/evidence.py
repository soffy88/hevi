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

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

# Scene fallback: Chinese → English stock query.  Pexels indexes English; a
# direct Chinese query returns little.  Subject nouns are handled separately
# below so that "橘猫趴在海边" searches a cat on a beach, not just a beach.
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
    ("键盘", "keyboard typing desk"),
    ("街道", "city street morning"),
    ("清晨", "morning sunlight street"),
    ("深夜", "night city lights"),
    ("机器人", "humanoid robot"),
    ("工厂", "factory industrial machine"),
    ("汽车", "car on road"),
    ("太空", "space stars galaxy"),
    ("地球", "planet earth from space"),
)

# The sentence's subject decides *what* the picture is of; the scene only
# qualifies it.  Longest keys are matched first ("橘猫" before "猫").
_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("橘猫", "orange cat"),
    ("小猫", "kitten"),
    ("猫", "cat"),
    ("小狗", "puppy"),
    ("狗", "dog"),
    ("机器人", "robot"),
    ("女孩", "girl"),
    ("男孩", "boy"),
    ("女人", "woman"),
    ("男人", "man"),
    ("老人", "elderly person"),
    ("孩子", "child"),
    ("学生", "student"),
    ("老师", "teacher"),
    ("厨师", "chef"),
    ("司机", "driver"),
    ("舞者", "dancer"),
    ("医生", "doctor"),
    ("主播", "presenter"),
)

_SCENES: tuple[tuple[str, str], ...] = (
    ("海边", "beach"),
    ("海滩", "beach"),
    ("沙滩", "beach"),
    ("森林", "forest"),
    ("实验室", "laboratory"),
    ("办公室", "modern office"),
    ("办公", "office desk"),
    ("厨房", "kitchen"),
    ("课堂", "classroom"),
    ("街道", "city street"),
    ("城市", "city skyline"),
    ("太空", "space galaxy"),
    ("地球", "planet earth"),
    ("清晨", "morning sunlight"),
    ("早晨", "morning sunlight"),
    ("深夜", "night city lights"),
    ("夜晚", "night city lights"),
    ("咖啡", "coffee cup"),
    ("键盘", "keyboard typing"),
    ("工厂", "factory"),
    ("汽车", "car road"),
    ("山", "mountain"),
    ("雪", "snow"),
    ("雨", "rain"),
    ("阳光", "sunlight"),
    ("太阳", "sunlight"),
    ("晒", "sunlight"),
    ("浪", "ocean waves"),
    ("书", "books"),
    ("海", "ocean sea"),
    ("夜", "night city"),
    ("街", "street"),
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


def _tokens_cn(text: str) -> list[str]:
    """Chinese tokens: jieba when installed, otherwise the raw sentence."""
    try:
        import jieba

        return [token for token in jieba.cut(str(text or "")) if token.strip()]
    except Exception:
        return [str(text or "")]


def _first_hit(
    text: str, table: tuple[tuple[str, str], ...], *, exclude: str = ""
) -> tuple[str, str] | None:
    """Earliest (then longest) table key contained in ``text``."""
    best: tuple[int, int, str, str] | None = None
    for needle, english in table:
        if exclude and needle in exclude:
            continue
        idx = text.find(needle)
        if idx < 0:
            continue
        score = (idx, -len(needle))
        if best is None or score < (best[0], best[1]):
            best = (idx, -len(needle), needle, english)
    if best is None:
        return None
    return best[2], best[3]


def subject_and_scene(sentence: str) -> tuple[str, str]:
    """Return ``(subject_en, scene_en)`` extracted by rules (+ jieba).

    The subject is the noun the sentence is *about* (an animal, a person, a
    robot); the scene only qualifies it.  This is what stops "橘猫趴在海边"
    from searching only for waves.
    """
    text = str(sentence or "")
    if not text:
        return "", ""
    tokens = _tokens_cn(text)
    # jieba can split/keep words differently; search both the raw sentence and
    # the token stream (positions from the raw string win).
    joined = "|".join(tokens)
    subject_hit = _first_hit(text, _SUBJECTS) or _first_hit(joined, _SUBJECTS)
    subject_en = subject_hit[1] if subject_hit else ""
    rest = text.replace(subject_hit[0], " ", 1) if subject_hit else text
    scene_hit = _first_hit(rest, _SCENES) or _first_hit(
        joined.replace(subject_hit[0], " ", 1) if subject_hit else joined, _SCENES
    )
    scene_en = scene_hit[1] if scene_hit else ""
    return subject_en, scene_en


def query_plan(sentence: str, topic: str = "") -> tuple[str, str]:
    """Return ``(query, subject_en)``; subject + scene wins over either alone."""
    subject_en, scene_en = subject_and_scene(sentence)
    if subject_en and scene_en:
        return f"{subject_en} {scene_en}", subject_en
    if subject_en:
        return subject_en, subject_en
    if scene_en:
        return scene_en, ""
    for text in (sentence, topic):
        lowered = str(text or "").strip().lower()
        if not lowered:
            continue
        for needle, query in _QUERY_MAP:
            if needle.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])", lowered):
                    return query, ""
            elif needle.lower() in lowered:
                return query, ""
    ascii_words = re.findall(r"[A-Za-z]{3,}", f"{sentence} {topic}")
    if ascii_words:
        return " ".join(ascii_words[:4]).lower(), ""
    return "abstract background texture", ""


def query_for_sentence(sentence: str, topic: str = "") -> str:
    """Deterministic English stock query for a Chinese/English sentence.

    Subject + scene when both are present ("橘猫"/"海边" → "orange cat beach");
    the sentence itself wins over the topic, so a casual topic word (e.g.
    "AI") cannot hijack every sentence's evidence.
    """
    return query_plan(sentence, topic)[0]


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
    subject = str(item.get("subject") or "")
    haystack = " ".join(
        str(part) for part in (meta.get("alt"), meta.get("title"), meta.get("tags"))
    )
    hay_tokens = _tokens(haystack)
    query_tokens = _tokens(query)
    subject_tokens = _tokens(subject)
    if not hay_tokens or not query_tokens:
        return None
    # Subject hits weigh more than scene hits: a photo of the right animal on
    # the wrong beach is still on-topic, a generic beach for a cat sentence is
    # not.  When we know the subject, a scene-only match is not enough.
    if subject_tokens:
        if subject_tokens & hay_tokens:
            return True
        if len(hay_tokens) >= 2:
            return False
        return None
    if query_tokens & hay_tokens:
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
    planned_query, planned_subject = query_plan(sentence, topic)
    q = query if query is not None else planned_query
    subject = planned_subject
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # The cache key must include the query: node ids repeat across graphs and
    # share one output root, so a path-only cache would serve the first graph's
    # photo for a later, different sentence.
    key = hashlib.sha1(q.encode("utf-8")).hexdigest()[:12]
    suffix = f"_{pick}" if pick else ""
    photo_path = out_dir / f"evidence_{key}{suffix}.jpg"
    meta: dict[str, Any] | None = None
    try:
        from hevi.collage_broll.assets import pexels_photo_meta

        meta = pexels_photo_meta(q, photo_path, "portrait", per_page=8, pick=pick)
    except Exception:
        meta = None
    if meta is None and allow_web:
        meta = _web_screenshot(q, out_dir / f"evidence_web_{key}{suffix}.png")
    if meta is None:
        return {
            "ok": False,
            "path": "",
            "query": q,
            "subject": subject,
            "sentence": sentence,
            "skipped_reason": "Pexels/网页截图均未取得可用素材",
            "meta": {},
            "source_label": source_label({}),
        }
    item = {
        "ok": True,
        "path": str(meta.get("path") or ""),
        "query": q,
        "subject": subject,
        "sentence": sentence,
        "meta": meta,
        "source_label": source_label(meta),
        "skipped_reason": "",
    }
    item["relevant"] = judge_relevance(sentence, item)
    return item

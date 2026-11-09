"""Multi-language subtitles for the series line.

Translation prefers the project's registered text LLM (``llm_pick``), not a
weak free translator.  A caller can inject a translator or an LLM.  When no LLM
is registered the source text is kept and the track is marked ``untranslated``
— never silently fabricated.  Timing (start/end) is copied from the primary
track, so the two lines stay aligned.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any


def _chars_per_second(target: str) -> float:
    return 9.0 if target.lower().startswith("en") else 7.0


def translate_lines(
    texts: list[str],
    target: str,
    *,
    llm: Any = None,
    glossary: dict[str, str] | None = None,
    durations: list[float] | None = None,
) -> dict[str, Any]:
    if not texts:
        return {"lines": [], "provider": "none", "translated": True, "status": "empty"}
    if llm is None:
        try:
            from hevi.providers.llm_pick import resolve_text_llm

            llm = resolve_text_llm()
        except Exception:
            llm = None
    if llm is None:
        return {"lines": list(texts), "provider": "unavailable", "translated": False,
                "status": "llm_unavailable"}
    terms = "\n".join(f"- {k} -> {v}" for k, v in (glossary or {}).items())
    cps = _chars_per_second(target)
    limits = []
    for i, text in enumerate(texts):
        dur = float((durations or [len(text) / cps])[i] if durations and i < len(durations) else len(text) / cps)
        limits.append(f"{i}: max {max(8, int(dur * cps))} chars")
    prompt = (
        f"Translate each numbered subtitle line to {target}. Keep names, tone and meaning. "
        "Respect the length budget so the line can be read in its time slot. "
        "Return JSON only, an object mapping string keys to translated strings; no commentary.\n"
        + (f"Terminology:\n{terms}\n" if terms else "")
        + "Length budget:\n" + "\n".join(limits) + "\n"
        + "\n".join(f"{i}: {text}" for i, text in enumerate(texts))
    )
    response: Any = llm(messages=[{"role": "user", "content": prompt}], temperature=0.1)
    if inspect.isawaitable(response):
        response = _await(response)
    content = response.get("content") if isinstance(response, dict) else str(response)
    if isinstance(content, list):
        content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    raw = str(content or "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        raise RuntimeError("translation LLM returned no JSON object")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise RuntimeError("translation LLM must return a JSON object")
    out = [str(payload.get(str(i)) or "").strip() for i in range(len(texts))]
    if any(not line for line in out):
        raise RuntimeError("translation LLM returned incomplete lines")
    return {"lines": out, "provider": "hevi_llm", "translated": True, "status": "ok"}


def _await(value: Any) -> Any:
    """Run an awaitable from synchronous code without touching a running loop."""
    import asyncio
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, value).result()


def apply_bilingual(
    edit: dict[str, Any],
    target: str,
    *,
    llm: Any = None,
    glossary: dict[str, str] | None = None,
) -> dict[str, Any]:
    rows = edit.get("subtitles") or []
    texts = [str(row.get("text") or "") for row in rows]
    durations = [max(0.5, float(row.get("end_s") or 0) - float(row.get("start_s") or 0)) for row in rows]
    result = translate_lines(texts, target, llm=llm, glossary=glossary, durations=durations)
    for row, line in zip(rows, result["lines"], strict=False):
        row["secondary"] = line
    edit["secondary_language"] = target
    edit["translation"] = {"provider": result["provider"], "status": result["status"],
                           "translated": result["translated"]}
    return edit


def write_srt(edit: dict[str, Any], out_path: Path, *, lang: str = "primary") -> Path:
    def fmt(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = round((t - int(t)) * 1000)
        if ms == 1000:
            s += 1
            ms = 0
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, row in enumerate(edit.get("subtitles") or [], start=1):
        text = str(row.get("secondary") if lang == "secondary" else row.get("text") or "")
        lines.append(f"{i}\n{fmt(float(row['start_s']))} --> {fmt(float(row['end_s']))}\n{text}\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path

"""词级 transcript → takes_packed.md（LLM 剪辑主阅读面）。

对标 video-use：把多源词级 ASR 压成短语级 markdown，按静音/说话人断句，
避免把原始 JSON / 全帧丢给模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.assembly.edit_craft import SILENCE_PHRASE_BREAK_S, Word


@dataclass(frozen=True)
class Phrase:
    start: float
    end: float
    speaker: str
    text: str


def words_from_transcript_json(data: dict[str, Any]) -> list[Word]:
    """兼容多种 transcript JSON 形态 → Word 列表。"""
    words: list[Word] = []
    # 形态 A: {"words": [{"word","start","end"}, ...]}
    raw_words = data.get("words")
    if isinstance(raw_words, list) and raw_words:
        for w in raw_words:
            if not isinstance(w, dict):
                continue
            text = str(w.get("word") or w.get("text") or "").strip()
            if not text:
                continue
            words.append(
                Word(word=text, start=float(w["start"]), end=float(w["end"]))
            )
        return words

    # 形态 B: {"segments": [{"start","end","text","words":[...]}, ...]}
    for seg in data.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        seg_words = seg.get("words")
        if isinstance(seg_words, list) and seg_words:
            for w in seg_words:
                if not isinstance(w, dict):
                    continue
                text = str(w.get("word") or w.get("text") or "").strip()
                if not text:
                    continue
                words.append(
                    Word(word=text, start=float(w["start"]), end=float(w["end"]))
                )
        else:
            text = str(seg.get("text") or "").strip()
            if text:
                words.append(
                    Word(
                        word=text,
                        start=float(seg.get("start") or 0),
                        end=float(seg.get("end") or 0),
                    )
                )
    return words


def pack_phrases(
    words: list[Word],
    *,
    speakers: list[str] | None = None,
    silence_break_s: float = SILENCE_PHRASE_BREAK_S,
) -> list[Phrase]:
    """词序列 → 短语列表。静音 ≥ silence_break_s 或说话人变化则断句。"""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w.start)
    phrases: list[Phrase] = []
    buf: list[Word] = [ordered[0]]
    spk = (speakers[0] if speakers else "S0") if speakers is None or len(speakers) != len(ordered) else speakers[0]
    cur_spk = spk

    def _flush(buf_words: list[Word], speaker: str) -> None:
        if not buf_words:
            return
        text = "".join(w.word for w in buf_words)
        # 英文词间补空格的简单启发
        if any(c.isascii() and c.isalpha() for c in text):
            text = " ".join(w.word for w in buf_words)
        phrases.append(
            Phrase(
                start=buf_words[0].start,
                end=buf_words[-1].end,
                speaker=speaker,
                text=text.strip(),
            )
        )

    for i in range(1, len(ordered)):
        prev, cur = ordered[i - 1], ordered[i]
        next_spk = (
            speakers[i]
            if speakers is not None and len(speakers) == len(ordered)
            else cur_spk
        )
        gap = cur.start - prev.end
        if gap >= silence_break_s or next_spk != cur_spk:
            _flush(buf, cur_spk)
            buf = [cur]
            cur_spk = next_spk
        else:
            buf.append(cur)
    _flush(buf, cur_spk)
    return phrases


def format_takes_packed(
    takes: dict[str, list[Phrase]],
    *,
    durations: dict[str, float] | None = None,
) -> str:
    """多 take 短语 → takes_packed.md 文本。"""
    lines: list[str] = ["# takes_packed", ""]
    for name, phrases in takes.items():
        dur = durations.get(name) if durations else None
        if dur is None and phrases:
            dur = phrases[-1].end
        n = len(phrases)
        header = f"## {name}"
        if dur is not None:
            header += f"  (duration: {dur:.1f}s, {n} phrases)"
        else:
            header += f"  ({n} phrases)"
        lines.append(header)
        for p in phrases:
            lines.append(
                f"  [{p.start:06.2f}-{p.end:06.2f}] {p.speaker} {p.text}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def pack_transcript_file(
    transcript_path: Path,
    *,
    take_name: str | None = None,
    silence_break_s: float = SILENCE_PHRASE_BREAK_S,
) -> list[Phrase]:
    """读单个 transcript JSON → 短语列表。"""
    import json

    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    words = words_from_transcript_json(data)
    return pack_phrases(words, silence_break_s=silence_break_s)


def pack_edit_dir(
    edit_dir: Path,
    *,
    silence_break_s: float = SILENCE_PHRASE_BREAK_S,
) -> Path:
    """扫描 edit_dir/transcripts/*.json → 写 takes_packed.md。"""
    import json

    td = edit_dir / "transcripts"
    takes: dict[str, list[Phrase]] = {}
    durations: dict[str, float] = {}
    if td.is_dir():
        for p in sorted(td.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            words = words_from_transcript_json(data)
            name = p.stem
            takes[name] = pack_phrases(words, silence_break_s=silence_break_s)
            if "duration" in data:
                durations[name] = float(data["duration"])
            elif words:
                durations[name] = words[-1].end

    out = edit_dir / "takes_packed.md"
    out.write_text(format_takes_packed(takes, durations=durations), encoding="utf-8")
    return out

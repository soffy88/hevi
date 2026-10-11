"""Pure caption/typography planning: ASS documents, kinetic word plan,
caption chunking.  Strings in, strings out."""

from __future__ import annotations

import re

FONT = "Noto Sans CJK SC"
Event = tuple[float, float, str, str]  # (start_s, end_s, style, text-with-override-tags)


def ass_time(s: float) -> str:
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def ass_styles(width: int, height: int) -> dict[str, str]:
    h = height
    return {
        "Cap": f"{FONT},{int(h * 0.058)},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{int(h * 0.06)},1",
        "Title": f"{FONT},{int(h * 0.09)},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,2,0,1,4,2,5,60,60,60,1",
        "Kicker": f"{FONT},{int(h * 0.035)},&H0000C8FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,4,0,1,2,0,5,60,60,60,1",
        "Lower": f"{FONT},{int(h * 0.05)},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,14,0,1,70,70,{int(h * 0.1)},1",
    }


def build_ass(*, width: int, height: int, events: list[Event], styles: dict[str, str] | None = None) -> str:
    base = ass_styles(width, height)
    base.update(styles or {})
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    head += "".join(f"Style: {k},{v}\n" for k, v in base.items())
    head += "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    body = "".join(
        f"Dialogue: 0,{ass_time(a)},{ass_time(b)},{st},,0,0,0,,{_escape(tx)}\n" for a, b, st, tx in events if b > a
    )
    return head + body


def _escape(text: str) -> str:
    # newlines inside an event would break the ASS line format
    return text.replace("\r", "").replace("\n", r"\N")


def caption_events(cues: list[tuple[float, float, str]], style: str = "Cap") -> list[Event]:
    return [(a, b, style, t) for a, b, t in cues]


_CLAUSE = re.compile(r"[^，,。．.！!？?；;：:、\s]+")


def kinetic_words(texts: list[str], *, max_chars: int = 8) -> list[str]:
    """Narration -> short punchy clauses for kinetic typography."""
    words: list[str] = []
    for t in texts:
        for c in _CLAUSE.findall(t):
            c = c.strip()
            while len(c) > max_chars:
                words.append(c[:max_chars])
                c = c[max_chars:]
            if c:
                words.append(c)
    return words


KINETIC_ANIMS = (
    r"{\an5\fscx260\fscy260\alpha&HFF&\t(0,220,\fscx100\fscy100\alpha&H00&)}",
    "MOVE",  # filled with frame-size-dependent move()
    r"{\an5\fscy0\t(0,250,\fscy100)}",
    r"{\an5\frz-12\fscx40\fscy40\t(0,300,\frz0\fscx100\fscy100)}",
)


def kinetic_events(
    *, words: list[str], cues: list[tuple[float, float, str]], total: float, width: int, height: int
) -> list[Event]:
    """Distribute words over the narration timeline proportionally to their
    character offset in the spoken text, so each word lands while it is said."""
    if not words:
        return []
    spoken = "".join(c[2] for c in cues)
    starts: list[float] = []
    pos = 0
    for w in words:
        idx = spoken.find(w, pos)
        if idx < 0:
            idx = pos
        pos = idx + len(w)
        # map character index -> time inside the cue that contains it
        acc = 0
        t0 = cues[-1][0]
        for a, b, text in cues:
            if idx < acc + len(text):
                frac = (idx - acc) / max(1, len(text))
                t0 = a + frac * (b - a)
                break
            acc += len(text)
        starts.append(t0)
    ev: list[Event] = []
    longest = max(range(len(words)), key=lambda k: len(words[k]))
    for k, w in enumerate(words):
        a = starts[k]
        b = starts[k + 1] if k + 1 < len(words) else total - 0.2
        b = max(b, a + 0.5)
        anim = KINETIC_ANIMS[k % 4]
        if anim == "MOVE":
            anim = r"{\an5\move(%d,%d,%d,%d,0,300)}" % (width + 400, height // 2, width // 2, height // 2)
        big = k == longest or k == len(words) - 1 or k % 3 == 0
        style = "Title" if big else "Kicker"
        ev.append((a, b, style, anim + r"{\fs%d\bord5}" % (int(height * (0.15 if big else 0.1))) + w))
    return ev


def word_chunks(words: list[tuple[float, float, str]], *, size: int = 4) -> list[tuple[float, float, str]]:
    out = []
    for c in range(0, len(words), size):
        chunk = words[c : c + size]
        out.append((chunk[0][0], chunk[-1][1], "".join(w[2] for w in chunk).strip()))
    return out


__all__ = [
    "Event",
    "FONT",
    "ass_styles",
    "ass_time",
    "build_ass",
    "caption_events",
    "kinetic_events",
    "kinetic_words",
    "word_chunks",
]

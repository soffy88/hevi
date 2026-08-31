"""真 ASS 双语字幕 —— 对照 xiaohu(中文大、原文小;SRT 做不到字号反差)。"""

from __future__ import annotations

from hevi.ingest.video_transcript import TranscriptSegment

_CJK_FONT = "Noto Sans CJK SC"


def _ass_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    cs = round(seconds * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return (text or "").replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def cues_to_ass(
    pairs: list[tuple[TranscriptSegment, TranscriptSegment]] | list[TranscriptSegment],
    *,
    bilingual: bool = True,
    font: str = _CJK_FONT,
    primary_size: int = 48,
    secondary_size: int = 28,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """写出 ASS。bilingual=True 时 pairs 为 (译文, 原文);否则单语 primary。"""
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Primary,{font},{primary_size},&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,40,40,48,1\n"
        f"Style: Secondary,{font},{secondary_size},&H00AAAAAA,&H000000FF,&H00000000,"
        "&H80000000,0,0,0,0,100,100,0,0,1,1,0,2,40,40,18,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    for item in pairs:
        if isinstance(item, TranscriptSegment):
            primary, secondary = item, None
        else:
            primary, secondary = item
        start = _ass_ts(primary.start)
        end = _ass_ts(primary.end)
        events.append(
            f"Dialogue: 0,{start},{end},Primary,,0,0,0,,{_escape(primary.text)}"
        )
        if bilingual and secondary is not None and secondary.text.strip():
            events.append(
                f"Dialogue: 0,{start},{end},Secondary,,0,0,0,,{_escape(secondary.text)}"
            )
    return header + "\n".join(events) + ("\n" if events else "")

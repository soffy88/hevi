"""译制/说话人/口播粗剪/ASS —— 对照 xiaohu / VidBee / OpenStoryline。"""

from __future__ import annotations

from hevi.ingest.ass_captions import cues_to_ass
from hevi.ingest.speakers import label_speakers
from hevi.ingest.speech_rough_cut import rough_cut
from hevi.ingest.subtitle_polish import apply_glossary, polish_segments
from hevi.ingest.video_localize import ffmpeg_burn_args, plan_localize
from hevi.ingest.video_transcript import TranscriptSegment
from hevi.ingest.words import interpolate_words, lock_cues_to_words, split_cues_by_pause


def test_interpolate_and_split_cues_by_pause():
    words = interpolate_words("其实没人告诉你。真相很简单。", 0.0, 4.0)
    assert len(words) >= 8
    cues = split_cues_by_pause(list(words), pause_s=0.01, max_chars=8)
    assert len(cues) >= 2
    assert all(c.end > c.start for c in cues)


def test_glossary_and_polish():
    segs = [TranscriptSegment(0.0, 1.0, "open cloud code and ncp.")]
    out = polish_segments(segs)
    assert "Claude Code" in out[0].text
    assert "MCP" in out[0].text
    assert apply_glossary("Hevi ncp", {"hevi": "Hevi"}) == "Hevi MCP"


def test_ass_bilingual_has_two_styles(tmp_path):
    src = TranscriptSegment(0.0, 1.2, "The secret is MCP.")
    zh = TranscriptSegment(0.0, 1.2, "秘密就是 MCP")
    text = cues_to_ass([(zh, src)], bilingual=True)
    assert "Style: Primary" in text
    assert "Style: Secondary" in text
    assert text.count("Dialogue:") == 2
    assert "秘密就是 MCP" in text


def test_label_speakers_alternates_on_pause():
    segs = [
        TranscriptSegment(0.0, 1.0, "你好"),
        TranscriptSegment(2.5, 3.5, "还好"),
        TranscriptSegment(3.6, 4.2, "继续"),
    ]
    labeled = label_speakers(segs, pause_s=0.8)
    assert labeled[0].speaker == "SPEAKER_00"
    assert labeled[1].speaker == "SPEAKER_01"
    assert labeled[2].speaker == "SPEAKER_01"


def test_rough_cut_drops_filler_only():
    segs = [
        TranscriptSegment(0.0, 0.4, "嗯"),
        TranscriptSegment(0.5, 1.5, "其实没人说"),
        TranscriptSegment(1.6, 2.0, "那个"),
    ]
    kept, dropped = rough_cut(segs)
    assert len(dropped) == 2
    assert len(kept) == 1
    assert "没人" in kept[0].text


def test_plan_localize_writes_ass_without_video(tmp_path):
    segs = [TranscriptSegment(0.0, 2.0, "其实没人告诉你这个秘密。")]
    plan = plan_localize(segs, bilingual=True, work_dir=tmp_path)
    assert plan.bilingual is False
    assert "no translation" in plan.notes[0]
    assert (tmp_path / "subtitles.ass").exists()
    assert "Dialogue:" in plan.ass_text
    args = ffmpeg_burn_args("in.mp4", plan.ass_path, tmp_path / "out.mp4", watermark="hevi")
    assert args[0] == "-y"
    assert "-vf" in args
    assert "drawtext" in args[args.index("-vf") + 1]


def test_lock_cues_to_words_snaps():
    words = interpolate_words("hello world today", 1.0, 4.0)
    cues = [TranscriptSegment(0.9, 4.2, "hello world today")]
    locked = lock_cues_to_words(cues, list(words))
    assert locked[0].start <= 1.0
    assert locked[0].end >= 4.0

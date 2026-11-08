"""Layer2 oskill：纯函数技能（无 IO / 无外部进程），可单测。"""

from hevi.avcraft.oskill.highlight import (
    candidate_windows,
    highlights_to_timeline,
    score_highlights,
)
from hevi.avcraft.oskill.moderation import moderation_prescreen
from hevi.avcraft.oskill.motion import motion_search, motion_spec_to_ffmpeg, shot_vocab_inject, vocab_line
from hevi.avcraft.oskill.reframe import crop_size, per_frame_x, pick_targets, smooth_crop_path
# oskill/shotprompt.py is DEFERRED at admission (2026-11-04): its fate is
# a separate owner decision and it stays out of this tree. Callers in
# omodul/sequence_plan.py and omodul/storyboard_enrich.py lazy-import it,
# so importing this package never touches the deferred module.
from hevi.avcraft.oskill.subtitle import (
    repair_breaks,
    segment_sentences,
    to_ass,
    to_srt,
    translate_cues,
)
from hevi.avcraft.oskill.timeline import (
    apply_ops,
    build_pause_timeline,
    keep_ranges,
    load_timeline,
    map_time,
    merge_cut_signals,
    render_cues,
    save_timeline,
    set_region_keep,
    split_clips_at,
    timeline_from_cues,
    timeline_set_keep,
)

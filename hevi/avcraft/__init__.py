"""avcraft —— hevi 自有音视频剪辑/字幕能力（3O 分层：obase / oskill / omodul）。

能力思路借鉴（只借鉴算法思路，未拷贝任何上游代码，见 UPSTREAM-3O.md）：
Auto-Editor（停顿剪辑）、VideoCaptioner / VideoLingo（ASR→断句→翻译→双语字幕）、
BaoCut（可编辑时间线）。全部 CPU、本地、零付费 API。
"""

__all__ = ["pause_cut", "bilingual_subtitles"]


__manifest__ = {
    "spec": "HELIOS_3O_SPEC_v3_0",
    "version": "1.0.0",
    "layers": {
        "obase": [
            "asr_runtime", "llm_local", "media", "motion_catalog",
            "shot_table", "text_layer", "timeline_io", "vision",
        ],
        "oskill": [
            "highlight", "moderation", "motion", "reframe",
            "subtitle", "timeline",
        ],
        "omodul": [
            "bilingual_subs", "edit_session", "highlight_clips",
            "pause_cut", "reframe_vertical", "sequence_plan",
            "storyboard_enrich", "title_card",
        ],
    },
    # Deferred at admission; see the disclosure at the top of
    # UPSTREAM-3O.md. Not importable from this tree.
    "deferred": ["oskill.shotprompt"],
}

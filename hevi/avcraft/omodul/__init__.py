"""Layer3 omodul：模块编排（obase IO + oskill 纯函数），对外入口（惰性导入，避免 -m 运行警告）。"""

__all__ = ["pause_cut", "export_timeline", "bilingual_subtitles", "init_session", "export_session",
           "record_take", "highlight_clips", "reframe_vertical",
           "title_card_compose", "storyboard_enrich"]  # sequence_plan 与子模块同名，请 from ...omodul.sequence_plan import sequence_plan


def __getattr__(name):
    if name in ("pause_cut", "export_timeline"):
        from hevi.avcraft.omodul import pause_cut as m

        return getattr(m, name)
    if name == "bilingual_subtitles":
        from hevi.avcraft.omodul.bilingual_subs import bilingual_subtitles

        return bilingual_subtitles
    if name in ("init_session", "export_session"):
        from hevi.avcraft.omodul import edit_session as m

        return getattr(m, name)
    if name == "record_take":
        from hevi.avcraft.omodul import sequence_plan as m

        return getattr(m, name)
    if name == "highlight_clips":
        from hevi.avcraft.omodul.highlight_clips import highlight_clips

        return highlight_clips
    if name == "reframe_vertical":
        from hevi.avcraft.omodul.reframe_vertical import reframe_vertical

        return reframe_vertical
    if name == "title_card_compose":
        from hevi.avcraft.omodul.title_card import title_card_compose

        return title_card_compose
    if name == "storyboard_enrich":
        from hevi.avcraft.omodul.storyboard_enrich import storyboard_enrich

        return storyboard_enrich
    raise AttributeError(name)

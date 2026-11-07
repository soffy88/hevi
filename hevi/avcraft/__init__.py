"""avcraft —— hevi 自有音视频剪辑/字幕能力（3O 分层：obase / oskill / omodul）。

能力思路借鉴（只借鉴算法思路，未拷贝任何上游代码，见 UPSTREAM-3O.md）：
Auto-Editor（停顿剪辑）、VideoCaptioner / VideoLingo（ASR→断句→翻译→双语字幕）、
BaoCut（可编辑时间线）。全部 CPU、本地、零付费 API。
"""

__all__ = ["pause_cut", "bilingual_subtitles"]

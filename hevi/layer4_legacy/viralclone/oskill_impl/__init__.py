"""ViralClone skill layer."""

from hevi.layer4_legacy.viralclone.oskill_impl.anchoring import (
    align_segments_to_word_timestamps,
    build_ass_subtitles,
    build_timeline_from_anchors,
)
from hevi.layer4_legacy.viralclone.oskill_impl.breakdown_math import (
    classify_sentence_semantic_role,
    compute_rhythm_stats,
    detect_subtitle_box_from_frames,
)
from hevi.layer4_legacy.viralclone.oskill_impl.diversity import (
    compute_frame_phash,
    compute_variant_diversity_matrix,
    evaluate_variant_pair_diversity,
)
from hevi.layer4_legacy.viralclone.oskill_impl.product_card import (
    composite_product_card_frame,
    remove_product_background,
    render_product_card_animation_frames,
)
from hevi.layer4_legacy.viralclone.oskill_impl.watermark import (
    compute_watermark_spec,
    detect_overlay_in_frame,
    measure_ass_glyph_bbox,
    verify_implicit_watermark_metadata,
    verify_watermark_in_frame,
)

__all__ = [
    "align_segments_to_word_timestamps",
    "build_ass_subtitles",
    "build_timeline_from_anchors",
    "classify_sentence_semantic_role",
    "compute_frame_phash",
    "compute_rhythm_stats",
    "compute_variant_diversity_matrix",
    "compute_watermark_spec",
    "composite_product_card_frame",
    "detect_overlay_in_frame",
    "detect_subtitle_box_from_frames",
    "evaluate_variant_pair_diversity",
    "measure_ass_glyph_bbox",
    "remove_product_background",
    "render_product_card_animation_frames",
    "verify_implicit_watermark_metadata",
    "verify_watermark_in_frame",
]

"""ViralClone exterior shim package."""

from hevi.viralclone.adapter import (
    breakdown_reference_video,
    compile_viral_template,
    draft_template_from_breakdown,
    produce_product_card_video,
    produce_viralclone,
    render_viral_variants,
)
from hevi.layer4_legacy.viralclone.omodul_impl import (
    reference_breakdown,
    compile_and_render_template,
    produce_product_asset,
    generate_variant_matrix,
)

__all__ = [
    "breakdown_reference_video",
    "compile_viral_template",
    "draft_template_from_breakdown",
    "produce_product_card_video",
    "produce_viralclone",
    "render_viral_variants",
    "reference_breakdown",
    "compile_and_render_template",
    "produce_product_asset",
    "generate_variant_matrix",
]

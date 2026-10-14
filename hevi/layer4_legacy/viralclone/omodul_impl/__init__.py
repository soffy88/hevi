"""ViralClone omodul layer."""

from hevi.layer4_legacy.viralclone.omodul_impl.breakdown import reference_breakdown
from hevi.layer4_legacy.viralclone.omodul_impl.compiler import compile_and_render_template
from hevi.layer4_legacy.viralclone.omodul_impl.product import produce_product_asset
from hevi.layer4_legacy.viralclone.omodul_impl.runtime import produce_viralclone
from hevi.layer4_legacy.viralclone.omodul_impl.variants import generate_variant_matrix

__all__ = [
    "compile_and_render_template",
    "generate_variant_matrix",
    "produce_product_asset",
    "produce_viralclone",
    "reference_breakdown",
]

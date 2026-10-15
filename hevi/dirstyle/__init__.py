"""dirstyle package — compatibility shim for legacy import paths."""
from hevi.layer4_legacy.dirstyle.oprim_impl import (  # noqa: F401
    ARTICLE_DIRECTOR_IDS,
    DIRSTYLE_DATA_DIR,
    SCHEMA_PATH,
    DirectorStyle,
    StyleGradeStep,
    check_article_directors,
    from_dict,
    get_style,
    list_styles,
    load_styles,
)
from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import compile_prompt  # noqa: F401
from hevi.layer4_legacy.dirstyle.omodul_impl.grade import (  # noqa: F401
    GradeResult,
    build_filter_chain,
    probe_video,
    run_style_grade,
    sha256_file,
    signalstats_mean,
)

__all__ = [
    "ARTICLE_DIRECTOR_IDS",
    "DIRSTYLE_DATA_DIR",
    "SCHEMA_PATH",
    "DirectorStyle",
    "StyleGradeStep",
    "compile_prompt",
    "GradeResult",
    "build_filter_chain",
    "probe_video",
    "run_style_grade",
    "sha256_file",
    "signalstats_mean",
    "check_article_directors",
    "from_dict",
    "get_style",
    "list_styles",
    "load_styles",
]

"""Portrait prompt vocabulary: structured index + prompt assembler.

66 bilingual entries in 8 categories (video micro-actions, posture,
hair/head, hands & held objects, motion, sitting, standing, gaze),
each with the concrete way to write it (``how``) and the feeling it
creates.  See ``vocab.py`` for the data provenance and ``assemble.py``
for the assembly method (one pick per category, person before scene,
conflicting picks rejected).
"""

from hevi.image.portrait_vocab.assemble import (
    CATEGORY_ORDER,
    CONFLICT_PAIRS,
    assemble,
    find_conflicts,
)
from hevi.image.portrait_vocab.vocab import (
    CATEGORIES,
    PortraitVocabError,
    counts,
    entries,
    get_entry,
    list_categories,
    load_index,
    phrasing_path,
    phrasing_rules,
    search,
)

__all__ = [
    "CATEGORIES",
    "CATEGORY_ORDER",
    "CONFLICT_PAIRS",
    "PortraitVocabError",
    "assemble",
    "counts",
    "entries",
    "find_conflicts",
    "get_entry",
    "list_categories",
    "load_index",
    "phrasing_path",
    "phrasing_rules",
    "search",
]

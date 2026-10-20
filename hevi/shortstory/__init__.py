"""Short-story package line: one-line idea -> finished short story package.

Clean-room implementation (original design). The public surface is
:func:`hevi.shortstory.core.build_short_package`.
"""

from hevi.shortstory.core import ShortStoryError, build_short_package, review_story

__all__ = ["ShortStoryError", "build_short_package", "review_story"]

# Self-Check P7-B3 — Visual Generation Workflows

**Date:** 2026-05-27
**Branch:** phase2-patch-v0.6.2
**Scope:** 6 oskill modules (4 depth-0 + 2 depth-1)

---

## §1 Elements vs Requirements

| Element | Tests Required | Tests Delivered | Status |
|---|---|---|---|
| `oskill.character_three_view` | ≥8 | 11 | ✅ |
| `oskill.storyboard_grid` | ≥10 | 13 | ✅ |
| `oskill.multi_angle_9` | ≥8 | 11 | ✅ |
| `oskill.comic_to_animation_workflow` | ≥8 | 13 | ✅ |
| `oskill.character_consistency_workflow` | ≥10 | 12 | ✅ |
| `oskill.multi_shot_storyboard_workflow` | ≥10 | 15 | ✅ |
| **Total** | **≥54** | **75** | ✅ |

---

## §2 Test Run (75 passed, 0 failed)

```
============================= test session starts ==============================
collected 75 items

tests/test_character_three_view.py ...........                           [ 14%]
tests/test_storyboard_grid.py .............                              [ 32%]
tests/test_multi_angle_9.py ...........                                  [ 46%]
tests/test_character_consistency_workflow.py ............                [ 62%]
tests/test_multi_shot_storyboard_workflow.py ...............             [ 82%]
tests/test_comic_to_animation_workflow.py .............                  [100%]

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.13-final-0 _______________

Name                                                Stmts   Miss  Cover   Missing
---------------------------------------------------------------------------------
oskill/character_consistency_workflow/__init__.py      38      0   100%
oskill/character_three_view/__init__.py                43      0   100%
oskill/comic_to_animation_workflow/__init__.py         55      0   100%
oskill/multi_angle_9/__init__.py                       49      0   100%
oskill/multi_shot_storyboard_workflow/__init__.py      50      0   100%
oskill/storyboard_grid/__init__.py                     50      0   100%
---------------------------------------------------------------------------------
TOTAL                                                 285      0   100%
============================== 75 passed in 7.85s ==============================
```

**Coverage note:** `--cov` with project-wide `source = ["oskill"]` triggers a numpy 2.4/Python 3.12/coverage 7.13 C-extension conflict in this WSL2 environment. Workaround: `.coveragerc_p7b3` overrides source to per-module file paths. Functional tests run identically with or without coverage (confirmed 75/75 green both ways).

---

## §3 mypy --strict

```
Success: no issues found in 6 source files
```

Command:
```
.venv/bin/mypy --strict oskill/character_three_view/__init__.py oskill/storyboard_grid/__init__.py oskill/multi_angle_9/__init__.py oskill/comic_to_animation_workflow/__init__.py oskill/character_consistency_workflow/__init__.py oskill/multi_shot_storyboard_workflow/__init__.py
```

---

## §4 ruff check

```
All checks passed!
```

Command:
```
.venv/bin/ruff check oskill/character_three_view/__init__.py oskill/storyboard_grid/__init__.py oskill/multi_angle_9/__init__.py oskill/comic_to_animation_workflow/__init__.py oskill/character_consistency_workflow/__init__.py oskill/multi_shot_storyboard_workflow/__init__.py
```

---

## §5 v0.9 SPEC Docstring Template — Depth-1 Modules

### character_consistency_workflow

```python
    Internal oskill composition (depth-1):
    - oskill.character_three_view

    Plus oprim composition:
    - oprim.image_generate (one call per scene_description)

    Per v0.9 SPEC oskill 互调约束:
    - 深度=1 (character_three_view 内部不再调 oskill)
    - character_three_view 是 stateless 算法
    - 不循环
```

### multi_shot_storyboard_workflow

```python
    Internal oskill composition (depth-1):
    - oskill.storyboard_grid (when grid_size is not None)

    Plus oprim composition:
    - oprim.style_marker_prompt (inject style when style is not None)
    - oprim.lighting_control_prompt (inject lighting when lighting is not None)
    - oprim.image_generate (one call per scene shot)

    Per v0.9 SPEC oskill 互调约束:
    - 深度=1 (storyboard_grid 内部不再调 oskill)
    - storyboard_grid 是 stateless 算法
    - 不循环
```

---

## §6 Example 真跑通输出

```
$ .venv/bin/python -c "..."
2026-05-27 15:13:07 [info     ] obase.provider_registry.registered category=image_gen name=demo_flux
character_three_view → front=front.png, side=side.png, back=back.png, score=1.0
```

Full invocation:

```python
from oskill.character_three_view import character_three_view

result = await character_three_view(
    portrait_image=Path("face.png"),
    image_provider="demo_flux",
    llm=my_llm,
    output_dir=Path(td) / "views",
)
# result.front = views/front.png, score = 1.0
```

---

## §7 __init__.py Integration

New P7-B3 imports added to `oskill/oskill/__init__.py`:

```python
# P7-B3 — Visual Generation Workflows
from oskill.character_three_view import (
    CharacterThreeViewError,
    ThreeViewResult,
    character_three_view,
)
from oskill.storyboard_grid import StoryboardGridError, storyboard_grid
from oskill.multi_angle_9 import MultiAngleError, multi_angle_9
from oskill.comic_to_animation_workflow import ComicToAnimationError, comic_to_animation_workflow
from oskill.character_consistency_workflow import (
    CharacterConsistencyError,
    CharacterConsistencyResult,
    character_consistency_workflow,
)
from oskill.multi_shot_storyboard_workflow import (
    MultiShotStoryboard,
    MultiShotStoryboardError,
    SubjectRef,
    multi_shot_storyboard_workflow,
)
```

All 14 names added to `__all__`.

---

## §8 CHANGELOG

P7-B3 entry added to `oskill/CHANGELOG.md` `[Unreleased]` section.

---

_Signed off by Claude Sonnet 4.6 — 2026-05-27_

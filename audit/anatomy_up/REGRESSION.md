# ANATUP regression comparison

baseline: `baseline_pytest.txt` — 228 failed, 8227 passed, 87 skipped, 46 xfailed, 125 warnings, 65 errors in 3450.86s (0:57:30)
after:    `after_pytest.txt` — 226 failed, 8264 passed, 87 skipped, 46 xfailed, 125 warnings, 65 errors in 5605.89s (1:33:25)

| run | failed | passed | skipped | xfailed | errors |
|---|---|---|---|---|---|
| baseline | 228 | 8227 | 87 | 46 | 65 |
| after | 226 | 8264 | 87 | 46 | 65 |

## New failures (must be empty)

  (new: none)

## Tests that no longer fail

  [fixed] tests/test_anatomy_explainer.py::test_anatomy_render_and_assertions
  [fixed] tests/test_anatomy_explainer.py::test_clean_environment_render


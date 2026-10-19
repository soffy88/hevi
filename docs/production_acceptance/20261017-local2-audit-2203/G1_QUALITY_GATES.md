# G1 — Quality gates

## Executed
- Initial global `uv run ruff check hevi tests`: 3,723 findings.
- After narrow, safe fixes, current global Ruff result: **FAIL, 3,709 findings**, 2,037 marked fixable and 615 additional hidden fixes. No global autofix was applied.
- Ruff for all six changed Python files: **PASS** (`All checks passed!`).
- Targeted regression suite, 10 files: **170 passed, 3 warnings, 0 failures**, in 3.84 s. JUnit XML and log are stored alongside this report.
- Full suite: NOT RUN in this pass; previous concurrent run was contaminated by resource exhaustion and is not used as evidence.
- `git diff --check`: PASS.

## Fixes included in this run
- Updated the legacy auth service adapter to call the canonical `sign_access_token` / `decode_access_token` API; added round-trip and missing-user-ID regression tests.
- Replaced the obsolete `aioredis` import with `redis.asyncio` in the rate-limit service. The current locked environment can import redis; direct dependency declaration in project metadata was not changed in this pass.
- Added the declared `zero` and `scene3d` render runtimes already used by production line YAML.
- Updated the Scene3D terminal-stage contract to reflect its self-rendering pipeline ending in `report`.
- Made weak-secret tests pass explicit values so host environment variables do not change the test's intended input.

## Not yet verified
- Mypy / strict typing.
- Coverage threshold.
- Frontend tests and production build.
- Dependency vulnerability / secret scan.
- Full suite on an isolated, adequately provisioned runner.

Decision: FAIL. Global lint remains red and the full release gate set has not passed.

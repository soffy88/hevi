# G0 — Baseline and resource safety

- Audit date: 2026-10-17 (local execution).
- Canonical repository: `/data/soffy/projects/hevi`.
- Branch / HEAD at audit: `closure/3o-v3-architecture-creative-baseline` / `d365dd54`.
- Existing working-tree state: no tracked diff was reported at baseline; numerous pre-existing untracked artifacts, outputs, fixtures, and project metadata exist. None were removed or overwritten.
- Disk: `/data` was 99% used, approximately 14 GB available; `/tmp` had approximately 12 GB available.
- Process risk: 26 `opencode run Read the file seed.txt...` processes were observed under pytest temporary worktrees, plus a pytest process belonging to the separate Veya repository. They were not terminated because they may belong to active work outside HEVI.
- Test safety: no HEVI full-suite run was started. The prior concurrent full-suite counts are not accepted as a trustworthy baseline because file-descriptor exhaustion was observed.
- No production deploy, service restart, destructive Git operation, or cleanup was performed.

Decision: proceed only with bounded, targeted HEVI tests and read-only artifact/security inspection until process/resource ownership is clarified.

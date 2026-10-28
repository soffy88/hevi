# Productization method attribution (2026-10-28 P0 intake)

Method inspiration only; no upstream text was copied into hevi.

- Source studied for product shape (not code): BeefTV
  (glanderness/BeefTV, beeftv.app), as surveyed in the background
  report `~/workspace/hevi-vs-beeftv.md` (read-only survey: public
  pages, docs and directory listing; no desktop build run, no model
  call, no purchase).
- License status of that source: NOT whole-repo MIT. Its LICENSE
  is a scope-split license (new original content under a Source
  Available license; earlier MIT material stays MIT; third-party
  material keeps its own license). Nothing from that repository is
  vendored, quoted or redistributed in this intake for that reason,
  and this intake must not be described as MIT-licensed upstream
  code.
- What was borrowed: working methods only, in own wording --
  an editable node-plus-edge project graph with reusable templates
  carrying a success record; snapshot retention with restore-first
  backup and stale-write refusal plus conflict drafts; a spend
  ledger that freezes parameters and estimates before a batch and
  settles refunds afterwards with failed items returning their
  originals; prompt picture references resolved only against
  connected assets, skipped when ambiguous or unconnected; model
  directory discipline (listed is not verified, config change
  forces retest, fee prompted from a caller-supplied figure);
  and a launch gate that reports readiness without deploying.
- What was NOT borrowed: the source repository's code, text,
  plugin packages, skill texts, pricing, or any route that bypasses
  a platform login. All module text, parameter names, checks and
  tests in this intake were written fresh for hevi.
- What hevi reused instead of duplicating: the existing infinite
  canvas model (`canvas_workflow`), the fixed project directories
  and manifest (`pipeline.project_handoff`), and the pre-spend
  confirmation gate (`pipeline.spend_brake`). This intake is a
  productization layer on top of those, not a second canvas and
  not a second spend gate.

New capabilities in this intake:

- pipeline.project_graph (project_graph.py)
- pipeline.project_snapshot (project_snapshot.py)
- pipeline.spend_ledger (spend_ledger.py)
- pipeline.smart_reference (smart_reference.py)
- model.model_directory (model_directory.py)
- pipeline.launch_gate (launch_gate.py)

Explicitly NOT in this intake (residuals, see task): skill version
management, preview and task-centre discipline, supplementary
multimodal audio-video checks, and production deployment itself.

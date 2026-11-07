# OpenAlice concepts mapped to Helios / 3O — R1

## Scope and provenance

Reference project: [TraderAlice/OpenAlice](https://github.com/TraderAlice/OpenAlice) and its [README](https://github.com/TraderAlice/OpenAlice/blob/main/README.md). The public project identifies itself as AGPL-3.0. This implementation uses the product concepts as architectural reference only; no OpenAlice source files were copied into these worktrees. A network operation to inspect/clone the public repository was blocked by the Local2 permission gate, so this comparison is based on public-facing repository/README material already reviewed, not a local source checkout.

## Concept mapping

| OpenAlice concept | Helios / 3O R1 implementation | Boundary retained |
|---|---|---|
| Git-backed research workspace and durable artifacts | `obase.alice_workspace.ResearchWorkspace`: schema-versioned workspace metadata, atomic document writes, append-only artifact manifest, SHA-256, source references, and observed Git HEAD | Does not initialize a repository, create commits, push, or execute agents. User controls artifact edits and Git operations. |
| Tracked assets, topics, theses, and their relationships | `oprim.alice_tracked_graph.TrackedGraph`: explicit typed nodes, evidence-linked edges, confidence-filtered deterministic neighborhood queries and JSON round-trip | No inferred edges based on names, and no mutation of existing Helios fusion scores. |
| Recurring research Issues | `oskill.alice_issue_schedule`: due-run planning, stable ticket identity, disabled schedules, UTC-aware timestamps, and backlog catch-up | Produces research-only tickets; this library is a planner, not a background scheduler or agent executor. |
| Reports, questions, and updates in an Inbox | `omodul.alice_inbox.InboxStore`: append-only state snapshots, unread/read/archived projection, path checks, and process-level file locking | Local file-backed substrate only; R1 does not create a new service or restart an existing one. |
| Trading as reviewable change, rather than automatic action | `oservi.alice_trade_proposals.ProposalStore`: pending proposal, independent approve/reject review, immutable terms, SHA-256 event chain, and fail-closed replay checks | Approval records a human decision only. No broker, exchange, order-routing, or order-execution path is implemented. |
| Web presentation / controlled opt-in API | `helios/api/app/routers/alice.py`, conditionally mounted in `api/app/main.py` | `ALICE_ENABLED` defaults off; writes need distinct actor tokens from `ALICE_API_TOKENS`; status explicitly reports proposal-only mode and no order execution. |

## Safety and integration decisions

- Keep each change inside its respective `feat/alice-3o` component worktree and preserve source worktrees/other branches.
- Use explicit evidence references on graph nodes and edges; preserve content hashes and observed Git lineage on documents.
- Treat a proposal as a document requiring a separately authenticated reviewer. The actor identity is derived from the token-to-actor map rather than a client-supplied `created_by` or `reviewer` field.
- Leave the integration disabled until an operator configures `ALICE_ENABLED`, `ALICE_DATA_DIR`, `ALICE_RESEARCH_ROOT`, and a distinct-token JSON map in `ALICE_API_TOKENS`. No secret is generated or stored by this task.
- Do not change fusion scoring, connect to exchange credentials, place orders, push branches, or restart services.

## Verification boundary

The source and tests compile under the available Python 3.14 interpreter. `evidence/verify_r1.py` executes seven offline behavioral groups, including calls to the API handlers through minimal framework shims, and records the results in `evidence/test-results.log`. The environment's `pytest` launcher is broken (`_pytest` missing) and FastAPI/Pydantic are not installed, so the actual pytest/TestClient suite could not be run here. The shim test checks handler logic; it is not a substitute for the real framework integration suite.

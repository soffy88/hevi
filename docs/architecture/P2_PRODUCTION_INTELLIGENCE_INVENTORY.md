# P2 Production Intelligence Inventory

Starting point: `21280f98b5a63f7beb3c49b9082a949348c99da8` on
`product/director-workbench-vnext`.

| Capability | Existing authority | P2 extension | Persistence | Boundary |
|---|---|---|---|---|
| Adaptive crew | DirectorSession/Decision, RevisionPatch | typed crew proposals, conflict and anti-theater evidence | `production_graph_entities` | Director proposes; canonical service applies |
| Creative preference | P1 structured memory | confidence/authority/profile records | existing workbench record store | explicit user > locked state > policy > learned |
| Outcome learning | ExecutionAttempt/Artifact/QA | outcome metrics and preference update | existing graph entity store | no automatic canonical mutation |
| Collaboration | ProductionRevision and stale checks | review threads and approval state | existing graph entity store | revision base is mandatory |
| Spatial continuity | ContinuityConstraint/Shot | typed spatial constraints | existing graph entity store | readiness remains authoritative |
| AI-native NLE | P1 timeline commands | typed semantic NLE operations | canonical revision + graph record | no timeline shadow state |
| Localization | existing audio/subtitle paths | locale track and segment evidence | graph entity store | runtime remains existing task/Slate path |
| Plugins | provider/capability registries | signed manifest + allow-listed typed proposals | graph entity store | no arbitrary code/provider access |
| Distributed recovery | existing TaskService, leases/checkpoints | recovery evidence projection | existing scheduler/task tables | extend MPT/Task runtime; no second queue |
| Evaluation | quality/evaluation modules | reproducible cases/results | graph entity store + existing evidence | results link to artifact/provenance |
| Rights | Artifact/provenance | license/territory/expiry ledger | graph entity store | delivery may be blocked by rights |

All P2 API records are `P2Model` instances and carry `project_id` and
`revision_id`. They are control-plane evidence, not replacement canonical
entities. Provider execution remains behind `ProductionCompiler` → `Slate` →
existing durable execution.


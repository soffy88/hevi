# OpenMontage capability gap audit

This is an architecture benchmark only. No OpenMontage source, AGPL code,
runtime dependency, or model is incorporated into HEVI.

| OpenMontage capability | HEVI equivalent | HEVI status | Gap | Priority | Action |
|---|---|---|---|---|---|
| pipeline manifest | `hevi/studio/recipes.py`, qualification manifests | EQUIVALENT | none | — | preserve |
| stage orchestration | studio runtime and execution plans | EQUIVALENT | none | — | preserve |
| director/planner | `hevi/director`, Shot Intelligence | HEVI_SUPERIOR | none | — | preserve |
| provider selection | provider registry/policy | EQUIVALENT | none | — | preserve |
| pre-compose validation | media validation and production gates | EQUIVALENT | none | — | preserve |
| review/reviewer system | human-review qualification state | PARTIAL | workflow UI depth | P2 | audit only |
| decision logs | provenance/runtime manifests | EQUIVALENT | none | — | preserve |
| checkpoint/resume | task checkpoints and qualification retry | EQUIVALENT | none | — | preserve |
| cost tracking | provider usage/cost metrics | EQUIVALENT | none | — | preserve |
| asset provenance | provenance ledger and artifact lineage | EQUIVALENT | none | — | preserve |
| FFmpeg composition | existing assembly/FFmpeg paths | EQUIVALENT | none | — | preserve |
| Remotion composition | `hevi-remotion` | EQUIVALENT | none | — | preserve |
| retry/recovery | worker lease/retry contracts | EQUIVALENT | none | — | preserve |
| human review | `HUMAN_REVIEW_REQUIRED` status | PARTIAL | reviewer UX | P2 | audit only |
| quality gates | qualification policy/media validators | HEVI_SUPERIOR | none | — | preserve |

Conclusion: no genuinely missing capability justifies importing OpenMontage.

# Video Intelligence inspirations

The implementation is HEVI-native. Upstream projects are references only;
their runtime, agents, providers and assets are not dependencies.

* ReelBench-style deterministic shot evidence and contact-sheet workflows are
  reimplemented behind HEVI contracts.
* VideoAgent-style intent decomposition and temporal retrieval are represented
  by typed query/index models, without importing its multi-agent runtime.
* Narrator-style task preflight and typed lifecycle ideas are represented by
  `VideoTask`/`PreflightResult`, without a commercial API.

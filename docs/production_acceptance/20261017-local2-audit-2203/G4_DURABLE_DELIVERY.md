# G4 — Durable delivery, retries, and recovery

- The historical real-video run includes `execution_receipts/RECEIPT.json` and a final artifact hash.
- Targeted test group covering studio recipe loading, production closure contracts, auth adapter, execution receipts, artifact validation, artifact verification, artifact lifecycle, production contracts, production checks and weak-secret policy: **170 passed, 3 warnings** after the fixes in this audit.
- These tests establish unit/contract behavior only. This audit did not run a live database-backed TaskService/Worker/Artifact/Receipt E2E, process-crash recovery, retry under a real failure, duplicate submission/idempotency, or approval/provenance round-trip against the active deployment.
- No test database was provisioned or mutated during this pass.

Decision: PARTIAL; durable delivery cannot be accepted solely from unit tests and an old receipt.

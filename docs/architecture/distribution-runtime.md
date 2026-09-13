# HEVI Distribution Runtime

The Distribution Runtime is an adapter boundary over external publishing
programs. HEVI owns `DistributionJob`, quality approval, idempotency keys,
provenance, and the terminal state; a provider owns only its external request
and result. MatrixMedia remains a separately installed GPL program and is
invoked through its CLI/MCP contract. Its source is not imported or vendored.

The safe path is:

`HEVI artifact -> SHA-256/integrity -> quality approval -> DistributionJob -> provider request -> provider result -> history/provenance`

An artifact without a passed quality gate cannot enter this runtime. An
ambiguous provider response is `NEEDS_ATTENTION`; it is never retried as if an
exactly-once publication had been proven.

The existing HEVI retry evidence primitive is reused. The distribution store
is a durable job projection, not a second queue, task scheduler, or artifact
authority.

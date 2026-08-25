# ADR-004 Transactional Outbox and Event Bus

- Status: Accepted
- Date: 2026-08-25

## Decision

Domain events are inserted in the same PostgreSQL transaction as the
aggregate write. A standalone publisher appends them to the broker. Each API
process owns a consumer cursor and fans events to its local WebSocket
connections. Redis is transport, not truth. Failed handlers retry then DLQ.

## Consequences

- WebSocket process memory is a connection layer only.
- Cross-instance progress p95 must stay under 2 seconds and be replayable.

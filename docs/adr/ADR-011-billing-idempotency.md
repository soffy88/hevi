# ADR-011 Billing Reservation, Consume, and Refund Idempotency

- Status: Accepted
- Date: 2026-08-25

## Decision

Task create accepts `Idempotency-Key`. Budget ledger entries are immutable
and keyed by `external_ref` plus attempt. Consume and refund of the same
attempt must not double-apply. Reservation races collapse to one attempt row.

## Consequences

- Retry, recovery, and duplicate submit are 0 extra charges.
- Tests must cover reserve races, not only the happy path.

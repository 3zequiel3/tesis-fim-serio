# Supersession note

The proposal, design and completed tasks in this change preserve the `items[]` decision that was implemented at the time. They are historical records and are not rewritten.

The change specs and current base specs are authoritative after the canonical breaking migration:

- bulk approve: `{event_ids:[...]}`
- bulk reject: `{event_ids:[...], action:"restore"|"quarantine"}`
- no `items`, client version, confirmation, per-item action or bulk `baseline_absent`
- no compatibility alias; legacy `items` requests receive 422

See `openspec/specs/backend-approve-reject/spec.md`, `openspec/specs/frontend-events/spec.md`, and this change's updated specs.

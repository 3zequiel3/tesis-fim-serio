# Follow-ups found while applying ingest-batched-persistence

Out of scope for this change. Recorded so they are not lost.

## S3 — `compact_chain` can delete a superseded event that has an `Alert`

**Pre-existing** (it also happens on the per-event path before this change); the verifier raised it
for the batched path. `alerts.event_id` is a foreign key without `ON DELETE`
(`backend/app/modules/alerts/models.py`), while `compact_chain` (`events/service.py`, RN-98) deletes the
oldest superseded events of a path beyond the 10 it keeps, protecting only those referenced by
`audit_log`. A `pending` event with `critical`/`high` severity is notified (an `Alert` row is created)
while it is still `pending`; if a later event of the same path supersedes it and the chain grows past
10, the compaction tries to delete a row that an `Alert` references.

Effect: the `DELETE` raises `IntegrityError` (`alerts_event_id_fkey`) inside the ingest transaction, so
**every new event for that path fails** until the oldest alerted event leaves the chain. With the batched
persistence the error rolls the batch back and the per-event replay isolates the offending event (its
message stays in the PEL), so neighbours progress; per-event it was an `IntegrityError` in the executor
that left the message in the PEL, the same poison.

Reproduction (PostgreSQL, ephemeral; verified 2026-10-03 against `postgres:18.3`):

1. Create the schema and one agent.
2. Ingest 1 event `E1` for path `/etc/x` with `action=manual_review` (status `pending`).
3. Insert an `Alert` row with `event_id = E1.id` (what `notify_if_applicable` does for a high event).
4. Ingest 10 more events for the same path with `action=manual_review`: the chain is now 10
   `superseded` plus 1 `pending`.
5. Ingest the 12th event: `compact_chain` selects 11 superseded events, deletes the oldest (`E1`) and the
   flush fails with
   `ForeignKeyViolation: update or delete on table "events" violates foreign key constraint "alerts_event_id_fkey" on table "alerts"`.

Fix options (separate change, needs a decision): treat events referenced by `alerts` as protected in
`compact_chain` (like `audit_log`), or declare `ON DELETE CASCADE`/`SET NULL` on `alerts.event_id`
(schema migration). Not touched here.

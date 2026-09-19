# INVALID_RUN — attempt 1

This interrupted attempt is excluded from every result and denominator.

- Observed failure: the inherited Run 3 instrumentation wrapper accepted three
  positional arguments, while HEAD `965dcac` calls `_ingest` with the new
  fourth `agent_id` argument introduced by backend optimization Unit 1.
- Evidence: `stdout.log` records the repeated `TypeError`; the process was
  stopped before the configured timeout to avoid treating harness failure as
  system performance.
- Correction before retry: the wrapper now accepts and forwards `agent_id`.
- System under test was not changed. PostgreSQL, Valkey and the local queue are
  reset by the harness at the start of the valid retry.

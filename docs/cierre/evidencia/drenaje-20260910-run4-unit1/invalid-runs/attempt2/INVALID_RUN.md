# INVALID_RUN — attempt 2

This completed attempt is excluded from the final result and every denominator.

- It observed 3,000/3,000 persisted events and an end-to-end duration of
  27.615535954 seconds.
- Unit 1 changed event acknowledgement to an atomic Valkey pipeline. The
  inherited wrapper delegated `pipeline()` directly, so it did not observe the
  transaction's XACK or signed event_ack XADD. This produced `n=0` stage fields
  and an impossible negative last-XACK interval.
- Correction before retry: wrap the real pipeline without replacing it and
  timestamp its atomic execute boundary. The system under test and controls are
  unchanged. PostgreSQL, Valkey and the local queue reset before the retry.

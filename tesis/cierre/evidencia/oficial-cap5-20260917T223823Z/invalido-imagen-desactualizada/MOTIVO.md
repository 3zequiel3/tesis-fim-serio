# Quarantined runs — the backend image did not match the candidate

These runs are preserved, not deleted. They are invalid as Chapter 5 evidence because the
backend they measured was not the candidate they declare.

## Evidence of the mismatch

The run logs declare `candidate=7a906c202e417aec5f03d9a7545e216a724aca81`, `tag=v1.0-tesis`,
and `metadata/entorno.txt` declares `git_status_clean=yes`. The working tree did match that
commit: `git status --porcelain backend/app/core/valkey.py backend/app/modules/events/consumer.py`
returned empty. The running container did not:

| File | In the container | In the repository |
|---|---|---|
| `app/core/valkey.py` | `f6e0e5f1111170bcf80ea42dfbeef87c13b21ca0e0dcc8bc020d821751c342ae` | `433d78ccceb6f5988fda71efcba15437d03b5785eef07f5d02cf75a037e9f991` |
| `app/modules/events/consumer.py` | `c1b96a2b36385a87e3c2e53615952123466605b52ed5f319e55981935b799aee` | `36d037e5f423133096ae12385c5e18f56c0a1f93119e9d35ac265d64d61400ef` |

The image `fim-backend:dev` was built on **2026-09-13T03:35:39-03:00**, four days before the
candidate commit, and the container mounts no source (its only mount is the `backend_certs`
volume at `/certs`). Independent confirmation: the container's `app/core/valkey.py` has neither
`_tls_kwargs` nor `build_async_valkey_client`, which the repository defines at lines 36 and 68 —
they arrived with `d0d9cb7`, the mutual-TLS Valkey commit. Nineteen commits touch `backend/`
between the image build and the candidate.

The agent was **not** affected: `sha256sum` of `/opt/tesis/agent/publisher.py` on the monitored
host equals the repository's
(`0fd266bc9ab9a7e5e5a7545775c17e2ec6a971c4ebb50b254d6f7b55e4b83f08`).

## What is quarantined here

| Directory | Run | Why it is still useful |
|---|---|---|
| `bateria3/` | Detection latency, 500 changes over 30 min | Superseded by the re-run; kept for comparison |
| `control/` | Control group, same window as Battery 3 | The scanner does not touch the backend, but the window is tied to the quarantined Battery 3 |
| `bateria5_nominal/` | Battery 5 at the nominal ingest limit (100/60 s) | Documents loss under the production budget: 2100/3000 delivered, 857 discarded |
| `bateria5_experimental/` | Battery 5 at 100000/60 s | Documents the 39 `clock_skew` rejections caused by the backend-cut deviation |
| `bateria5_corte-valkey/` | Battery 5 with the protocol cut | Established that the `clock_skew` rejections were an artefact of cutting the backend instead of Valkey |
| `invalido-nominal-20260917T224118Z/` | First attempt, aborted | Harness defect: the backend was recreated without the TLS override, so Valkey stopped serving 6380 |

## Two further defects these runs exposed, both since corrected

1. **Protocol deviation.** The harness stopped the backend; `docs/plan_medicion_cap5.md:338`
   requires severing connectivity with Valkey. With the broker up, the agent keeps publishing
   during the outage and events age past `_CLOCK_SKEW_S` (300 s) inside the stream, which measures
   a different scenario — backend down, broker up — and rejects the oldest events by construction.
2. **Measurement hysteresis.** The drain figure came from a polling loop requiring three stable
   samples at 5 s intervals, adding roughly 20 s of the harness's own latency. The re-run reads the
   ingest window from `received_at` in the database instead.

# Automated suites on the frozen candidate

Part of the consolidated run on candidate **`v1.0-tesis` (`7a906c2`)**. The agent and frontend trees
are byte-identical to that commit in the working tree, verified with `git diff --quiet`, so only the
backend needed a detached worktree.

## Results

| Suite | Tests | Failures | Errors | Skipped |
|---|---|---|---|---|
| Agent | 642 | **0** | 0 | 1 |
| Backend | 839 | **8** | 0 | 4 |
| Frontend | 260 | **0** | 0 | 0 |

Counts read from the root `<testsuites>` element of each JUnit file.

## The eight backend failures are a harness limitation, not a defect of the candidate

All eight report the same thing, and none of them fails an assertion about behaviour:

```
OSError: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8443):
         address already in use
```

surfacing as `RuntimeError: This portal is not running` when the `TestClient` context manager exits.

The application's lifespan starts the mutual-TLS server on port **8443** (`backend/app/main.py:92`
and `:130`), and that port is fixed in code: `start_mtls_server` declares `port: int = 8443`
(`backend/app/core/pki.py`), with no setting to move it. Most of the suite avoids the problem because
it drives the app through `ASGITransport`, which does not run the lifespan — `backend/tests/conftest.py`
states this explicitly. The eight tests that do use `TestClient` run the real lifespan, each tries to
bind the same fixed port, and they cannot coexist in one pytest session.

The failing tests are:

```
test_notifications.py::test_post_retry_alert_masivo_deja_una_fila_por_alerta
test_sse_alerts.py::test_get_alerts_filter_severity_high
test_sse_alerts.py::test_get_alerts_status_delivered_gana_sobre_failed
test_sse_alerts.py::test_get_alerts_order_desc_by_created_at
test_sse_alerts.py::test_get_alerts_includes_path_and_action_taken
test_sse_alerts.py::test_get_failed_alerts_includes_path_and_action_taken
test_sse_alerts.py::test_stream_alerts_invalid_ticket_returns_401
test_sse_stream_ticket.py::test_issue_ticket_without_jwt_returns_401_and_no_key
```

They cover alert listing and SSE ticket issuance. In every case the failure is raised during teardown,
after the request under test has already returned; no assertion about a status code or a payload
fails.

**Checks that rule out the alternatives.** The lab backend was stopped for the duration of the run,
so it was not holding the port — the conflict is between tests. Running the three affected files on
their own, against dedicated containers, still fails, so it is not an ordering artefact of the full
session either.

## Three harness defects found and fixed while producing this

They are recorded because the first attempt reported **48 failures**, and every one of them came from
the harness rather than from the code. Sealing that would have said the candidate was broken.

| Symptom | Real cause | Fix |
|---|---|---|
| 41 × `PermissionError: '/certs'` | The backend bootstraps its TLS material into `/certs`, the path inside the container, which is not writable on the host | The four certificate paths redirected to a writable directory |
| 41 × `This portal is not running` | No broker: the lifespan opens the consumers at startup, and without Valkey the startup dies and takes the anyio portal with it. `backend/tests/conftest.py:13` documents the container it expects | An isolated Valkey alongside the isolated PostgreSQL |
| Frontend reported 3 tests | The reading script took the first `<testsuite>`, which is the first file, instead of the root `<testsuites>` | Counts summed across every `<testsuite>` |

None of the three names its cause in its message, which is why they took three passes to separate.

## Reproduction

`~/fim-lab/suites_candidato.sh` carries the procedure with each of the three causes commented at the
point that handles it. It stands up an isolated PostgreSQL and Valkey on ports that do not collide
with the lab, stops the lab backend to free 8443 and 8444, runs the three suites and restores the lab.

The procedure in `../../../REPRODUCIR.md` §«suites» does not run as written on this machine: it assumes
a dedicated PostgreSQL with password `test` on port 5432, and the lab's database occupies that port.
Pointed at the lab database the whole suite errors out on connection. That document should record the
`TEST_DATABASE_URL` and `TEST_VALKEY_URL` overrides, which `conftest.py` supports for exactly this.

## Files

| File | Content |
|---|---|
| `procedencia.txt` | Candidate, tree comparison and the containers used |
| `agente.xml` / `agente.log` | Agent suite |
| `backend.xml` / `backend.log` | Backend suite, including the eight bind errors |
| `frontend.xml` / `frontend.log` | Frontend suite |

## Context

After bootstrap (C6, `agent-mtls-bootstrap`, archived), the agent persists its mTLS material in `config.storage.certs_dir` (default `/var/lib/fim-agent/certs`) with the canonical filenames defined in `agent/bootstrap.py`:

```python
_AGENT_CERT = "agent-cert.pem"
_AGENT_KEY  = "agent-key.pem"
_CA_CERT    = "ca.pem"
```

However, `agent/__main__.py:105` opens the Valkey connection with no TLS:

```python
valkey_client = avalkey.Valkey.from_url(cfg.valkey_url, decode_responses=True)
```

So the certs that exist on disk are never wired into the transport. The thesis (Tabla 9, p.16) and RN-86 require the agent↔backend channel to be TLS 1.3 mutual TLS. The HMAC-SHA256 per-message signing (`agent/streams.py`) is in place, but it only protects message integrity, not channel confidentiality or peer authentication. This change closes the channel-layer gap.

**Important correction to the original request**: the prompt suggested deriving cert paths from `secrets_dir`. That is wrong. `secrets_dir` holds `shared_secret` and `master_secret` (0400). The TLS certificate material lives in `certs_dir` (0600), as written by `bootstrap.py`. The factory MUST use `config.storage.certs_dir`.

**Decision closure check**: RN-86 (reglas_de_negocio.md:413) already closes that all communication travels over the mTLS channel established at bootstrap. This change implements an existing closed decision — no new assumption is introduced, so no appendix edit is required.

## Goals / Non-Goals

**Goals:**
- A single factory `create_valkey_client(config)` that produces the Valkey client, choosing mTLS vs plaintext by URL scheme.
- Reuse the bootstrap certificates verbatim — no new key generation, no copying.
- Keep local development and the existing test suite working without certificates (plaintext via `valkey://`/`redis://`).
- Enforce mutual TLS (`ssl_cert_reqs="required"`) so the channel cannot silently downgrade.

**Non-Goals:**
- Certificate rotation or renewal (that is C26).
- Changing the message signing contract (HMAC stays exactly as in `agent/streams.py`).
- Any backend-side Valkey TLS termination config (broker/server configuration is operational, outside this agent code change).
- Introducing a new external dependency — `avalkey` (valkey-py async) already accepts `ssl_*` kwargs on the client constructor.

## Decisions

### D-1: Scheme-driven TLS selection (`valkeys://` vs `valkey://`)

Select transport security from the URL scheme rather than a separate boolean flag.

- **Why**: The scheme is self-documenting and idiomatic (Redis/Valkey use `rediss://`/`valkeys://` for TLS by convention). It keeps a single source of truth (`valkey_url`) instead of a flag that can drift out of sync with the URL. It lets the existing tests — which already use `valkey://`/`redis://` — keep running with zero changes and zero certs.
- **Accepted schemes**: `valkeys://`, `rediss://` → TLS. `valkey://`, `redis://` → plaintext.
- **Alternative considered**: a `tls_enabled: bool` config field. Rejected — redundant with the scheme, and a mismatch between `tls_enabled=true` and a `valkey://` URL would be an ambiguous error state.

### D-2: Construct via `avalkey.Valkey(...)` with explicit kwargs, not `from_url`

The TLS branch builds the client by parsing the URL host/port and passing explicit `ssl_*` kwargs, because `from_url` does not let us inject `ssl_certfile`/`ssl_keyfile`/`ssl_ca_certs` cleanly for mutual TLS.

- **Why**: `from_url` infers `ssl=True` from a `rediss://` scheme but provides no ergonomic hook for client-cert + key + CA + `cert_reqs`. Explicit construction makes the mTLS parameters auditable and testable.
- **Implementation note**: Use `avalkey.Valkey.from_url(url, ssl_certfile=..., ssl_keyfile=..., ssl_ca_certs=..., ssl_cert_reqs="required", decode_responses=True)` if the installed `valkey-py` forwards `ssl_*` kwargs through `from_url` for `rediss`/`valkeys` schemes; otherwise fall back to host/port parsing with the direct `avalkey.Valkey(...)` constructor. The apply phase verifies which path the pinned `avalkey` version supports and selects accordingly. Either way the observable contract (the SSL params asserted in tests) is identical.

### D-3: `ssl_cert_reqs="required"` — full mutual TLS

The server cert MUST be verified against `ca.pem`. No `optional`/`none` fallback.

- **Why**: A downgrade to an unauthenticated channel would defeat the Tabla 9 invariant. Failing closed is the correct security posture for a thesis-grade integrity invariant.
- **Trade-off**: requires the Valkey broker to actually present a CA-signed cert in production. That is an operational prerequisite, documented in the config example, not solved in agent code.

### D-4: Paths derived from `config.storage.certs_dir`

The factory composes `certs_dir / "agent-cert.pem"`, etc. It does not read `ca_cert_path` directly even though that field exists, because `ca_cert_path` is the bootstrap-time CA path and may point elsewhere; the post-bootstrap canonical CA for the running agent is `certs_dir/ca.pem` (what `bootstrap.py` actually writes).

- **Why**: Single, consistent source for all three files. Matches exactly what bootstrap persisted.

## Risks / Trade-offs

- **[Missing cert files at startup when `valkeys://` is used but bootstrap hasn't run]** → `__main__.py` already runs `bootstrap.is_bootstrapped(certs_dir)` and triggers bootstrap before the main loop, so certs exist before the client is built. The factory references paths lazily (the SSL handshake reads them at connect time), so construction itself does not fail on missing files; the connection does. Acceptable — bootstrap ordering guarantees presence.
- **[`avalkey`/`valkey-py` kwarg surface differs from `redis-py`]** → Mitigation: the apply phase confirms the exact kwarg names against the pinned `avalkey` 0.x API and adjusts; the spec asserts observable SSL params, not a specific call shape.
- **[Tests would need certs if they used `valkeys://`]** → Mitigation: all existing tests use `valkey://`/`redis://` (plaintext branch). The new `test_transport.py` asserts SSL kwargs by inspecting the constructed client / patched constructor, without a live TLS handshake.
- **[Plaintext branch could be used in production by mistake]** → Mitigation: config example defaults to `valkeys://` and documents plaintext as dev-only.

## Migration Plan

1. Add `agent/transport.py` with `create_valkey_client(config)`.
2. Add `agent/tests/test_transport.py` (TLS-params-present / plaintext-params-absent).
3. Wire `agent/__main__.py` to call the factory.
4. Update `agent/deploy/config.yaml.example` default scheme to `valkeys://`.

**Rollback**: revert the `__main__.py` call to `avalkey.Valkey.from_url(cfg.valkey_url, decode_responses=True)`. The factory module and tests are additive and inert if unused. No data migration, no schema change.

## Open Questions

- None blocking. The only operational follow-up (out of scope) is ensuring the production Valkey broker is configured with a CA-signed server cert so `ssl_cert_reqs="required"` succeeds — this is deployment configuration, tracked separately from this agent code change.

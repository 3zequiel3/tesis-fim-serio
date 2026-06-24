## Why

The agent↔backend Valkey channel is currently established in plaintext: `agent/__main__.py` calls `avalkey.Valkey.from_url(cfg.valkey_url, decode_responses=True)` with no TLS parameters, even though the agent already holds Ed25519 certificates on disk after bootstrap. This violates the thesis security invariant (Tabla 9, "Integridad de eventos en tránsito → TLS 1.3 (canal) + XACK") and RN-86, which states that all agent↔backend communication travels over the mTLS channel established at bootstrap. The defense-in-depth chain (mTLS channel + HMAC message + AES-GCM at rest) is currently reduced to HMAC only — the channel layer is missing.

## What Changes

- Introduce a Valkey client factory `create_valkey_client(config: AgentConfig) -> avalkey.Valkey` that wires the bootstrap certificates into the transport when the URL scheme requests TLS.
- TLS is selected by URL scheme: `valkeys://` (or `rediss://`) → mTLS over TLS 1.3; `valkey://` (or `redis://`) → plaintext, for local development and tests.
- When TLS is active, the factory passes `ssl=True`, `ssl_certfile=<certs_dir>/agent-cert.pem`, `ssl_keyfile=<certs_dir>/agent-key.pem`, `ssl_ca_certs=<certs_dir>/ca.pem`, `ssl_cert_reqs="required"` (full mTLS — the server must present a cert signed by the same CA).
- Cert/key/CA paths are derived from `config.storage.certs_dir`, reusing the exact filenames written by `agent/bootstrap.py` (`agent-cert.pem`, `agent-key.pem`, `ca.pem`).
- `agent/__main__.py` builds the client through the factory instead of calling `from_url` directly.
- `agent/deploy/config.yaml.example` documents `valkeys://` as the production default URL scheme.

## Capabilities

### New Capabilities
- `agent-valkey-transport`: Defines how the agent constructs its Valkey Streams client, selecting mTLS (TLS 1.3) vs plaintext by URL scheme and sourcing certificate material from the bootstrap `certs_dir`.

### Modified Capabilities
<!-- No existing spec changes its requirements. The valkey-streams-transport spec defines the message/signing contract; it does not own client construction. mTLS bootstrap (RN-78, RN-86) already mandates the channel — this change implements it without redefining a requirement. -->

## Impact

- **Code**: `agent/transport.py` (new — factory), `agent/__main__.py` (use factory), `agent/config.py` (no structural change — `certs_dir` already present; verify accessibility).
- **Config**: `agent/deploy/config.yaml.example` (default scheme `valkeys://`).
- **Tests**: `agent/tests/test_transport.py` (new) — assert SSL params passed for `valkeys://`, omitted for `valkey://`.
- **Rules covered**: RN-63 (mTLS auth), RN-78 (bootstrap mTLS CA propia), RN-86 (all comm over mTLS channel), RN-108 (no HTTP server — Valkey Streams only); Tabla 9 (TLS 1.3 channel invariant).
- **Decisions applied**: D8 (no HTTP server in agent), D7 (cross-cutting travels with first feature needing it).
- **Dependencies**: requires C23 `agent-high-fixes` (archived). No new external dependency — `avalkey` already supports `ssl_*` kwargs.
- **No** Alembic, **no** new HTTP server, **no** cert rotation (rotation is C26).

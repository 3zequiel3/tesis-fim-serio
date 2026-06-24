## 1. Transport factory

- [x] 1.1 Create `agent/transport.py` with `create_valkey_client(config: AgentConfig) -> avalkey.Valkey`
- [x] 1.2 Implement scheme detection: `valkeys://`/`rediss://` → TLS branch; `valkey://`/`redis://` → plaintext branch
- [x] 1.3 In the TLS branch, derive cert paths from `config.storage.certs_dir` using filenames `agent-cert.pem`, `agent-key.pem`, `ca.pem`
- [x] 1.4 In the TLS branch, construct the client with `ssl=True`, `ssl_certfile`, `ssl_keyfile`, `ssl_ca_certs`, `ssl_cert_reqs="required"`, `decode_responses=True` (confirm exact kwarg surface against the pinned `avalkey` version per design D-2)
- [x] 1.5 In the plaintext branch, construct the client with no `ssl`/`ssl_*` params, `decode_responses=True`
- [x] 1.6 Raise a clear `ValueError` for an unrecognized URL scheme

## 2. Entrypoint wiring

- [x] 2.1 Replace `avalkey.Valkey.from_url(cfg.valkey_url, decode_responses=True)` in `agent/__main__.py` with `create_valkey_client(cfg)`
- [x] 2.2 Verify the single client instance is still passed to both `Publisher` and `HeartbeatPublisher`
- [x] 2.3 Confirm the factory import does not create an import cycle (`transport` imports only `config` + `avalkey`)

## 3. Deployment config

- [x] 3.1 Update `agent/deploy/config.yaml.example` so `valkey_url` defaults to `valkeys://localhost:6379`
- [x] 3.2 Update the surrounding comment to state that `valkeys://` enables mTLS and `valkey://`/`redis://` are development-only

## 4. Tests

- [x] 4.1 Create `agent/tests/test_transport.py`
- [x] 4.2 Test: `valkeys://` config produces a client with SSL params set (cert/key/ca paths derived from `certs_dir`, `ssl_cert_reqs="required"`) — assert via patched constructor or client introspection, no live handshake
- [x] 4.3 Test: `rediss://` config is treated identically to `valkeys://`
- [x] 4.4 Test: `valkey://` and `redis://` configs produce a client with no SSL params (plaintext)
- [x] 4.5 Test: cert paths equal `<certs_dir>/agent-cert.pem`, `<certs_dir>/agent-key.pem`, `<certs_dir>/ca.pem`
- [x] 4.6 Test: an unrecognized scheme raises `ValueError`

## 5. Verification

- [x] 5.1 Run the agent test suite and confirm existing tests (using `valkey://`/`redis://`) still pass unchanged
- [x] 5.2 Confirm `agent/__main__.py` still imports and the wiring matches the spec (single shared client)

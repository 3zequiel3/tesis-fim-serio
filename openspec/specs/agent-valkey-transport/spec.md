# agent-valkey-transport Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Valkey client factory selects transport by URL scheme

The agent SHALL construct its Valkey Streams client through a factory `create_valkey_client(config: AgentConfig) -> avalkey.Valkey` that selects the transport security mode based on the scheme of `config.valkey_url`. The factory MUST treat `valkeys://` and `rediss://` as TLS-enabled schemes, and `valkey://` and `redis://` as plaintext schemes. The factory MUST always pass `decode_responses=True`, preserving the existing client behavior.

#### Scenario: TLS scheme enables mTLS

- **WHEN** `create_valkey_client` is called with a config whose `valkey_url` starts with `valkeys://`
- **THEN** the resulting client is constructed with `ssl=True`, `ssl_cert_reqs="required"`, `ssl_certfile` pointing at `<certs_dir>/agent-cert.pem`, `ssl_keyfile` pointing at `<certs_dir>/agent-key.pem`, and `ssl_ca_certs` pointing at `<certs_dir>/ca.pem`

#### Scenario: rediss scheme is treated as TLS

- **WHEN** `create_valkey_client` is called with a config whose `valkey_url` starts with `rediss://`
- **THEN** the client is constructed with the same SSL parameters as the `valkeys://` case

#### Scenario: Plaintext scheme disables TLS

- **WHEN** `create_valkey_client` is called with a config whose `valkey_url` starts with `valkey://` or `redis://`
- **THEN** the resulting client is constructed without any `ssl` or `ssl_*` parameters, so the connection is plaintext

### Requirement: Certificate material is sourced from the bootstrap certs directory

When TLS is selected, the factory SHALL derive all certificate paths from `config.storage.certs_dir`, reusing the exact filenames written by `agent/bootstrap.py`. The factory MUST NOT generate, copy, or rotate certificates; it only references the existing files. The filenames MUST be `agent-cert.pem` (client certificate), `agent-key.pem` (client private key), and `ca.pem` (CA bundle for server verification).

#### Scenario: Paths derived from certs_dir

- **WHEN** the factory builds a TLS client and `config.storage.certs_dir` is `/var/lib/fim-agent/certs`
- **THEN** `ssl_certfile` is `/var/lib/fim-agent/certs/agent-cert.pem`, `ssl_keyfile` is `/var/lib/fim-agent/certs/agent-key.pem`, and `ssl_ca_certs` is `/var/lib/fim-agent/certs/ca.pem`

### Requirement: Mutual TLS verification is enforced

When TLS is selected, the client SHALL require the Valkey server to present a certificate signed by the same CA (`ca.pem`). The factory MUST set `ssl_cert_reqs="required"` so that an unverifiable or absent server certificate aborts the connection rather than falling back to an unauthenticated channel. This enforces the Tabla 9 invariant (TLS 1.3 channel) and RN-86 (all agent↔backend communication over the mTLS channel).

#### Scenario: Server certificate verification is mandatory

- **WHEN** the factory builds a TLS client
- **THEN** `ssl_cert_reqs` is `"required"`, so the connection is rejected if the server presents no certificate or one not chaining to `ca.pem`

### Requirement: Agent entrypoint uses the factory

The `agent/__main__.py` entrypoint SHALL construct its Valkey client by calling `create_valkey_client(cfg)` instead of calling `avalkey.Valkey.from_url` directly. The constructed client MUST be the single instance shared by the `Publisher` and `HeartbeatPublisher`, preserving the current wiring.

#### Scenario: Entrypoint delegates client construction

- **WHEN** the agent main loop starts and needs a Valkey client
- **THEN** it obtains the client from `create_valkey_client(cfg)` and passes that same instance to both `Publisher` and `HeartbeatPublisher`

### Requirement: Deployment example defaults to a TLS scheme

The `agent/deploy/config.yaml.example` SHALL present `valkeys://` as the default `valkey_url` scheme, documenting that production deployments use mTLS over the Valkey channel and that `valkey://`/`redis://` are reserved for local development and tests.

#### Scenario: Example config shows the TLS default

- **WHEN** a maintainer reads `agent/deploy/config.yaml.example`
- **THEN** the `valkey_url` value uses the `valkeys://` scheme and an accompanying comment explains that the plaintext schemes are for development only

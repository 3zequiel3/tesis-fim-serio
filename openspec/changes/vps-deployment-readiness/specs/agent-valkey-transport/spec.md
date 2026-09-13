## MODIFIED Requirements

### Requirement: Mutual TLS verification is enforced

When TLS is selected, the client SHALL require the Valkey server to present a certificate signed by the same CA (`ca.pem`). The factory MUST set `ssl_cert_reqs="required"` so that an unverifiable or absent server certificate aborts the connection rather than falling back to an unauthenticated channel. The factory MUST also set `ssl_check_hostname=True`, so the server certificate SAN MUST cover the host of `config.valkey_url`: a DNS name is matched against `DNSName` entries and an IP literal against `IPAddress` entries (D53/RN-147, RN-115). No configuration key, environment variable or scheme SHALL disable hostname verification. This enforces the Tabla 9 invariant (TLS 1.3 channel) and RN-86 (all agent↔backend communication over the mTLS channel).

#### Scenario: Server certificate verification is mandatory

- **WHEN** the factory builds a TLS client
- **THEN** `ssl_cert_reqs` is `"required"`, so the connection is rejected if the server presents no certificate or one not chaining to `ca.pem`

#### Scenario: Hostname verification is mandatory

- **WHEN** the factory builds a TLS client
- **THEN** `ssl_check_hostname` is `True`

#### Scenario: Server certificate does not cover the URL host

- **WHEN** `valkey_url` is `valkeys://203.0.113.10:6380` and the server certificate chains to `ca.pem` but its SAN does not include `IPAddress(203.0.113.10)`
- **THEN** the TLS handshake fails with a hostname verification error and no command is sent

#### Scenario: IP literal verified against the IP SAN

- **WHEN** `valkey_url` is `valkeys://203.0.113.10:6380` and the server certificate SAN includes `IPAddress(203.0.113.10)`
- **THEN** the connection is established without any name mapping in `/etc/hosts`

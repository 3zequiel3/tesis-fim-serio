## ADDED Requirements

### Requirement: Bootstrap certificate chain is verified before trust

Before persisting the certificate received during bootstrap, the agent SHALL verify that the certificate is signed by the received CA certificate. The verification MUST use the CA public key with the algorithm-appropriate method (Ed25519: `ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes)`, with no RSA padding or hash algorithm). If signature verification fails, the agent MUST raise `RuntimeError` and persist nothing (RN-78, RN-79).

#### Scenario: Certificate not signed by the received CA is rejected
- **WHEN** the bootstrap response contains a certificate not signed by the accompanying CA certificate
- **THEN** verification fails, a `RuntimeError` is raised, and no cert, CA, or secret is written to disk

#### Scenario: Certificate signed by the received CA passes the chain check
- **WHEN** the certificate is correctly signed by the accompanying CA certificate
- **THEN** the chain check passes and verification proceeds to the next checks

### Requirement: Bootstrap certificate CN matches the agent identity

The agent SHALL verify that the certificate's Common Name equals the configured `agent_id`. If it does not match, the agent MUST raise `RuntimeError` and persist nothing.

#### Scenario: Certificate with wrong CN is rejected
- **WHEN** the received certificate's CN is not equal to the agent's `agent_id`
- **THEN** a `RuntimeError` is raised and nothing is persisted

### Requirement: Bootstrap certificate public key matches the local private key

The agent SHALL verify that the public key embedded in the received certificate matches the public key of the locally generated private key (proving the backend signed the agent's own CSR). The comparison MUST be done over the serialized public key bytes. If they do not match, the agent MUST raise `RuntimeError` and persist nothing.

#### Scenario: Certificate whose public key does not match the local key is rejected
- **WHEN** the received certificate's public key differs from the local private key's public key
- **THEN** a `RuntimeError` is raised and nothing is persisted

#### Scenario: All checks pass and material is persisted
- **WHEN** the certificate chains to the CA, the CN matches `agent_id`, and the public key matches the local key
- **THEN** the cert, CA, `shared_secret`, and `master_secret` are written to disk with their existing permissions

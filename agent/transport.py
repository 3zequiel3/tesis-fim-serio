from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import structlog
import valkey.asyncio as avalkey

from agent.config import AgentConfig

log = structlog.get_logger()

_TLS_SCHEMES = {"valkeys", "rediss"}
_PLAIN_SCHEMES = {"valkey", "redis"}
_CERT_FILENAME = "agent-cert.pem"
_KEY_FILENAME = "agent-key.pem"
_CA_FILENAME = "ca.pem"


def create_valkey_client(config: AgentConfig) -> avalkey.Valkey:
    """Factory that builds a Valkey client choosing TLS or plaintext by URL scheme.

    - valkeys:// / rediss://  → mTLS using certs from config.storage.certs_dir
    - valkey://  / redis://   → plaintext (dev / CI only)
    """
    scheme = urlparse(config.valkey_url).scheme.lower()

    if scheme in _TLS_SCHEMES:
        certs_dir = Path(config.storage.certs_dir)
        certfile = certs_dir / _CERT_FILENAME
        keyfile = certs_dir / _KEY_FILENAME
        ca_certs = certs_dir / _CA_FILENAME

        missing = [p for p in (certfile, keyfile, ca_certs) if not p.exists()]
        if missing:
            raise RuntimeError(
                f"mTLS cert files missing (run bootstrap first): "
                + ", ".join(str(p) for p in missing)
            )

        return avalkey.Valkey.from_url(
            config.valkey_url,
            ssl_certfile=str(certfile),
            ssl_keyfile=str(keyfile),
            ssl_ca_certs=str(ca_certs),
            ssl_cert_reqs="required",
            ssl_check_hostname=True,
            decode_responses=True,
        )

    if scheme in _PLAIN_SCHEMES:
        if not config.allow_plaintext_valkey:
            log.warning(
                "transport.plaintext_valkey_warning",
                url=config.valkey_url,
                hint="mTLS is disabled — use valkeys:// in production or set allow_plaintext_valkey=true to suppress this warning (D20)",
            )
        return avalkey.Valkey.from_url(config.valkey_url, decode_responses=True)

    raise ValueError(
        f"Unrecognized Valkey URL scheme '{scheme}://'. "
        f"Use valkeys:// or rediss:// for TLS, valkey:// or redis:// for plaintext."
    )

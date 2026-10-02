"""Publish a signed rule_sync command to the agent while it is stopped (item 42)."""
import asyncio
import json
import sys
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.agents.models import Agent

AGENT = "fim-vm"

with Session(engine) as s:
    agent = s.exec(select(Agent).where(Agent.agent_id == AGENT)).first()
    secret_hex = agent.shared_secret_hex

sys.path.insert(0, "/app")
import hashlib  # noqa: E402
import hmac  # noqa: E402


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


payload = {
    "type": "rule_sync",
    "target_agent_id": AGENT,
    "ruleset_version": 999,
    "schema_version": 1,
    "issued_at": datetime.now(timezone.utc).isoformat(),
}
payload["signature"] = hmac.new(
    bytes.fromhex(secret_hex), canonical(payload).encode(), hashlib.sha256
).hexdigest()


async def main():
    import valkey.asyncio as valkey
    client = valkey.Valkey.from_url(
        str(settings.valkey_url),
        ssl_certfile="/certs/backend-valkey.pem",
        ssl_keyfile="/certs/backend-valkey-key.pem",
        ssl_ca_certs="/certs/ca.pem",
        decode_responses=True,
    )
    msg_id = await client.xadd("commands", {"data": json.dumps(payload)})
    print(f"command queued: id={msg_id} type=rule_sync issued_at={payload['issued_at']}")
    await client.aclose()

asyncio.run(main())

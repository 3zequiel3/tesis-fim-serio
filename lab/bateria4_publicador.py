"""Battery 4 publisher: injects signed events into the ingest stream with a
given concurrency, so the measured interval starts where the protocol says it
starts — when the backend receives the event — and not at the agent.

The interval itself is read from the database afterwards
(alerts.delivered_at - events.received_at), per plan_medicion_cap5.md fuente A.
"""
import asyncio, hashlib, hmac, json, sys, uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app")
from sqlmodel import Session, select
from app.core.config import settings
from app.core.database import engine
from app.modules.agents.models import Agent
from app.modules.agents.secret_wrap import load_wrap_key, unwrap_agent_secret

ESCENARIO = sys.argv[1]
TOTAL = int(sys.argv[2])
CONC = int(sys.argv[3])
AGENT = "fim-vm"

# Since D86/RN-180 the column holds a `v1:` wrapped value (legacy hex still accepted).
load_wrap_key(settings.agent_secret_wrap_key_path)
with Session(engine) as s:
    secret = unwrap_agent_secret(
        AGENT, s.exec(select(Agent).where(Agent.agent_id == AGENT)).first().shared_secret_hex
    )


def canonical(o):
    return json.dumps({k: v for k, v in o.items() if k != "signature"}, sort_keys=True, separators=(",", ":"))


def evento(i):
    ahora = datetime.now(timezone.utc).isoformat()
    # The critical subdirectory maps to the rule with critical severity; the rest
    # to high. Both notify, which is what battery 4 needs (precondition P6).
    ruta = f"/srv/fim-watch/critico/b4_{i:05d}.txt" if i % 5 == 0 else f"/srv/fim-watch/b4_{i:05d}.txt"
    p = {"event_id": str(uuid.uuid4()), "agent_id": AGENT, "path": ruta,
         "event_type": "file_modified", "operation_type": "file_modified",
         "detected_at": ahora, "sent_at": ahora, "schema_version": 1,
         "hash_detected": hashlib.sha256(str(i).encode()).hexdigest(),
         "hash_expected": None, "action": "alert_only", "is_binary": False,
         "is_symlink": False, "symlink_target": None, "parent_event_id": None,
         "process_pid": 1234, "process_uid": 0, "process_exe": None,
         "diff_text": None, "hex_dump_before": None, "hex_dump_after": None}
    p["signature"] = hmac.new(secret, canonical(p).encode(), hashlib.sha256).hexdigest()
    return p


async def main():
    import valkey.asyncio as valkey
    cli = valkey.Valkey.from_url(str(settings.valkey_url),
                                 ssl_certfile="/certs/backend-valkey.pem",
                                 ssl_keyfile="/certs/backend-valkey-key.pem",
                                 ssl_ca_certs="/certs/ca.pem", decode_responses=True)
    sem = asyncio.Semaphore(CONC)
    async def uno(i):
        async with sem:
            await cli.xadd("events", {"data": json.dumps(evento(i))})
    t0 = datetime.now(timezone.utc)
    await asyncio.gather(*(uno(i) for i in range(TOTAL)))
    t1 = datetime.now(timezone.utc)
    print(f"escenario={ESCENARIO} publicados={TOTAL} concurrencia={CONC} "
          f"inicio={t0.isoformat()} fin={t1.isoformat()}")
    await cli.aclose()

asyncio.run(main())

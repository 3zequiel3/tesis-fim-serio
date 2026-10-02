"""In-process micro-benchmark of the events consumer drain (D87/RN-181).

DEVELOPMENT measurement, NOT a thesis result and NOT the lab battery: it runs the
real `run_consumer` of the backend in this process against an ephemeral PostgreSQL
and an ephemeral Valkey on localhost (no VM, no TLS, no n8n, no agent). Use it to
attribute cost per stage and to compare the optimization steps of D87 against the
same yardstick; the number that counts for `v5.0-tesis` is the one measured with
`lab/corrida_unificada.sh` (Change 61).

How it works: pre-fills the `events` stream with N signed events of one agent,
starts `run_consumer`, and measures the time until the N `event_ack` replies are
in the `commands` stream. The notification chain is replaced by a no-op (it needs
n8n and is not part of the drain lane being measured).

Configurations (emulate the code before each D87 step on the same build):
  baseline    auth cache disabled (TTL 0) + immediate event_ack/XACK per event
  auth-cache  auth cache enabled        + immediate event_ack/XACK per event
  batch-ack   auth cache enabled        + batched event_ack/XACK (the shipped code)

Usage (from the repo root; the ephemeral services must already be running):
  BENCH_DATABASE_URL=postgresql+psycopg://fim:test@localhost:55433/fim_bench \\
  BENCH_VALKEY_URL=valkey://localhost:56379 \\
  backend/.venv/bin/python lab/bench_ingest_consumer.py --events 3000 --repeats 3

The database named in BENCH_DATABASE_URL is created if missing and its tables are
created with `SQLModel.metadata.create_all`. NEVER point it at a real database:
the script TRUNCATEs `events`, `alerts` and `rejected_events_audit`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

DB_URL = os.environ["BENCH_DATABASE_URL"]
VALKEY_URL = os.environ["BENCH_VALKEY_URL"]

# Settings() is built at import time: set the environment first.
os.environ.update(
    DATABASE_URL=DB_URL,
    VALKEY_URL=VALKEY_URL,
    JWT_SECRET_CURRENT="bench-secret-current-32-chars-xxxxxxx",
    JWT_SECRET_PREVIOUS="",
    ADMIN_USERNAME="admin",
    ADMIN_PASSWORD="AdminPassword123!",
    ADMIN_EMAIL="admin@fim.local",
    CORS_ALLOWED_ORIGINS="http://localhost:5173",
    RATE_LIMIT_INGEST_BURST="1000000",  # the limiter is not what is being measured
)
_key_dir = tempfile.mkdtemp(prefix="fim-bench-key-")
_key_path = os.path.join(_key_dir, "agent-secret-wrap.key")
fd = os.open(_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, os.urandom(32))
os.close(fd)
os.environ["AGENT_SECRET_WRAP_KEY_PATH"] = _key_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import psycopg  # noqa: E402
import sqlalchemy  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

AGENT_ID = "bench-agent"
SECRET = os.urandom(32)


def _ensure_database() -> None:
    parsed = urlparse(DB_URL.replace("+psycopg", ""))
    name = parsed.path.lstrip("/")
    admin_dsn = parsed._replace(path="/postgres").geturl()
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(f'CREATE DATABASE "{name}"')


_ensure_database()

import app.modules.events.consumer as consumer_mod  # noqa: E402
import app.modules.events.service as service_mod  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.core.streams import (  # noqa: E402
    CONSUMER_GROUP,
    SCHEMA_VERSION,
    STREAM_COMMANDS,
    STREAM_EVENTS,
    sign_payload,
)
from app.core.valkey import build_async_valkey_client  # noqa: E402
from app.modules.agents.models import Agent, AgentStatus  # noqa: E402
from app.modules.agents.secret_wrap import load_wrap_key, wrap_agent_secret  # noqa: E402

assert service_mod  # imported for its side effects on the module graph


def _prepare_schema() -> None:
    load_wrap_key(_key_path)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("TRUNCATE agents, events, alerts, rejected_events_audit RESTART IDENTITY CASCADE"))
    with Session(engine) as session:
        session.add(
            Agent(
                agent_id=AGENT_ID,
                status=AgentStatus.offline,
                shared_secret_hex=wrap_agent_secret(AGENT_ID, SECRET),
            )
        )
        session.commit()


def _event(i: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": AGENT_ID,
        "path": f"/srv/fim-watch/bench_{i:06d}.txt",
        "event_type": "file_modified",
        "operation_type": "file_modified",
        "detected_at": now,
        "sent_at": now,
        "schema_version": SCHEMA_VERSION,
        "hash_detected": f"{i:064x}",
        "hash_expected": None,
        "action": "alert_only",
        "is_binary": False,
        "is_symlink": False,
        "symlink_target": None,
        "parent_event_id": None,
        "process_pid": 1234,
        "process_uid": 0,
        "process_exe": None,
        "diff_text": None,
        "hex_dump_before": None,
        "hex_dump_after": None,
    }
    payload["signature"] = sign_payload(SECRET, payload)
    return payload


class _TimingCollector:
    """Stands in for the module logger: keeps `consumer.timing` records, drops the rest."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def _record(self, event: str, **kw) -> None:
        if event == "consumer.timing":
            self.records.append(kw)

    info = warning = error = debug = lambda self, event, **kw: self._record(event, **kw)  # noqa: E731


async def _noop_notify(_event) -> None:
    return None


def _configure(name: str) -> None:
    """Apply the code-path toggles for one configuration."""
    consumer_mod.reset_agent_auth_cache()
    consumer_mod._AUTH_CACHE_TTL_S = 0.0 if name == "baseline" else 5.0
    if name in ("baseline", "auth-cache"):

        async def immediate(client, _ack_batch, msg_id, event_id, agent_id, secret):
            await consumer_mod._ack_with_event_ack(client, msg_id, event_id, agent_id, secret)

        consumer_mod._ack_or_defer = immediate
    else:
        consumer_mod._ack_or_defer = _ORIGINAL_ACK_OR_DEFER


_ORIGINAL_ACK_OR_DEFER = consumer_mod._ack_or_defer
consumer_mod.notify_if_applicable = _noop_notify


async def _drain(n: int, config: str, profile: bool) -> tuple[float, list[dict]]:
    _configure(config)
    cfg = settings.model_copy(update={"fim_profile_ingest": profile})
    consumer_mod.settings = cfg
    collector = _TimingCollector()
    consumer_mod.log = collector

    client = build_async_valkey_client(VALKEY_URL)
    try:
        await client.delete(STREAM_EVENTS, STREAM_COMMANDS)
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("TRUNCATE events, alerts, rejected_events_audit RESTART IDENTITY CASCADE"))
        pipe = client.pipeline(transaction=False)
        for i in range(n):
            pipe.xadd(STREAM_EVENTS, {"data": json.dumps(_event(i))})
        await pipe.execute()
        # The group is created from "0": the consumer reads the whole pre-filled stream.
        stop = asyncio.Event()
        started = time.perf_counter()
        task = asyncio.create_task(consumer_mod.run_consumer(client, stop))
        while await client.xlen(STREAM_COMMANDS) < n:
            await asyncio.sleep(0.01)
            if time.perf_counter() - started > 600:
                raise TimeoutError("drain did not finish in 600 s")
        elapsed = time.perf_counter() - started
        stop.set()
        await asyncio.wait_for(task, 10)
        with Session(engine) as session:
            persisted = session.execute(sqlalchemy.text("SELECT count(*), count(DISTINCT event_id) FROM events")).one()
        assert tuple(persisted) == (n, n), f"expected {n} distinct rows, got {persisted}"
        pending = (await client.xpending(STREAM_EVENTS, CONSUMER_GROUP))["pending"]
        assert pending == 0, f"{pending} entries left in the PEL"
        return elapsed, collector.records
    finally:
        await client.delete(STREAM_EVENTS, STREAM_COMMANDS)
        await client.aclose()


def _stage_means(records: list[dict]) -> dict[str, float]:
    events = [r for r in records if r.get("scope") == "event"]
    batches = [r for r in records if r.get("scope") == "batch"]
    out: dict[str, float] = {}
    for key in ("auth_ms", "validation_ms", "ingest_ms", "total_ms"):
        if events:
            out[key] = statistics.fmean(r[key] for r in events)
    if events:
        out["auth_cache_hit_ratio"] = sum(1 for r in events if r["auth_cache_hit"]) / len(events)
    if batches:
        out["ack_flush_ms_per_batch"] = statistics.fmean(r["ack_flush_ms"] for r in batches)
        out["ack_flush_ms_per_event"] = sum(r["ack_flush_ms"] for r in batches) / max(
            1, sum(r["batch_size"] for r in batches)
        )
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=3000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--configs", default="baseline,auth-cache,batch-ack")
    args = parser.parse_args()

    _prepare_schema()
    await _drain(200, "batch-ack", profile=False)  # warm-up: connections, imports, JIT-less caches
    for config in args.configs.split(","):
        rates = []
        for _ in range(args.repeats):
            elapsed, _ = await _drain(args.events, config, profile=False)
            rates.append(args.events / elapsed)
        _, records = await _drain(args.events, config, profile=True)
        stages = _stage_means(records)
        print(
            json.dumps(
                {
                    "config": config,
                    "events": args.events,
                    "repeats": args.repeats,
                    "ev_per_s_runs": [round(r, 1) for r in rates],
                    "ev_per_s_median": round(statistics.median(rates), 1),
                    "profile_run_stage_means": {k: round(v, 3) for k, v in stages.items()},
                }
            ),
            flush=True,
        )


asyncio.run(main())

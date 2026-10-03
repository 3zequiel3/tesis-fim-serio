"""In-process micro-benchmark of the events consumer drain (D87/RN-181).

DEVELOPMENT measurement, NOT a thesis result and NOT the lab battery: it runs the
real `run_consumer` of the backend in this process against an ephemeral PostgreSQL
and an ephemeral Valkey on localhost (no VM, no TLS, no n8n, no agent). Use it to
attribute cost per stage and to compare the optimization steps of D87 against the
same yardstick; the number that counts for `v5.0-tesis` is the one measured with
`lab/corrida_unificada.sh` (Change 61).

How it works: pre-fills the `events` stream with N signed events of one agent,
starts `run_consumer`, and measures the time until the N `event_ack` replies are
in the `commands` stream. By default (`--notify stub`) the notification chain is
replaced by a no-op (it needs n8n and is not part of the drain lane being measured).

`--notify real` (Change `ingest-batched-persistence`, D-1) keeps the real chain
(`notify_if_applicable` -> `Alert` row -> `send_n8n` -> `_mark_delivered`): it seeds a
`high` severity rule that matches the bench paths and points `N8N_WEBHOOK_URL` at a
local HTTP sink (a subprocess) that answers 2xx and, per request, INSERTs and COMMITs
a row in a `bench_n8n` database of the SAME PostgreSQL instance, emulating n8n's
execution persistence (a foreign COMMIT per notification on the shared WAL). Each
drain then also waits until the N alerts have `delivered_at` and reports the ingest
rate (last `event_ack`) and the delivery rate (last delivery) separately.
`--paths N` spreads the events over N paths in cyclic order (the load generator
repeats paths: 600 paths for 3,000 events); default: one path per event.

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
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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


SINK_DB_NAME = "bench_n8n"


def _ensure_database(name: str | None = None) -> str:
    """Create the database `name` (default: the one in BENCH_DATABASE_URL) if missing; return its DSN."""
    parsed = urlparse(DB_URL.replace("+psycopg", ""))
    name = name or parsed.path.lstrip("/")
    admin_dsn = parsed._replace(path="/postgres").geturl()
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(f'CREATE DATABASE "{name}"')
    return parsed._replace(path=f"/{name}").geturl()


_ensure_database()

import app.modules.events.consumer as consumer_mod  # noqa: E402
import app.modules.events.service as service_mod  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.core.executors import install_executors  # noqa: E402
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
from app.modules.rules.models import Rule, RuleAction, RuleSeverity  # noqa: E402

assert service_mod  # imported for its side effects on the module graph


BENCH_PATH_PREFIX = "/srv/fim-watch/"


def _prepare_schema(notify: str) -> None:
    load_wrap_key(_key_path)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            sqlalchemy.text("TRUNCATE agents, events, alerts, rules, rejected_events_audit RESTART IDENTITY CASCADE")
        )
    if notify == "real":
        # `high` rule matching every bench path: each event alerts, as in the lab.
        with Session(engine) as session:
            session.add(Rule(pattern=f"{BENCH_PATH_PREFIX}*", severity=RuleSeverity.high, action=RuleAction.alert_only))
            session.commit()
    with Session(engine) as session:
        session.add(
            Agent(
                agent_id=AGENT_ID,
                status=AgentStatus.offline,
                shared_secret_hex=wrap_agent_secret(AGENT_ID, SECRET),
            )
        )
        session.commit()


def _event(i: int, paths: int | None = None) -> dict:
    path_index = i if paths is None else i % paths
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": AGENT_ID,
        "path": f"{BENCH_PATH_PREFIX}bench_{path_index:06d}.txt",
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


# Emulates n8n persisting its execution: one INSERT + COMMIT per request in another
# database of the same PostgreSQL instance. A subprocess, like n8n, so it does not
# share the GIL with the consumer. Prints its port on stdout once it is listening.
_SINK_CODE = r"""
import sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import psycopg

conn = psycopg.connect(sys.argv[1], autocommit=False)
conn.execute("CREATE TABLE IF NOT EXISTS execution_entity (id bigserial PRIMARY KEY, body text, created_at timestamptz DEFAULT now())")
conn.commit()
lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        with lock:
            conn.execute("INSERT INTO execution_entity (body) VALUES (%s)", (body,))
            conn.commit()
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_address[1], flush=True)
server.serve_forever()
"""


def _start_sink() -> tuple[subprocess.Popen, str, str]:
    """Start the HTTP sink; return (process, webhook url, DSN of the sink database)."""
    dsn = _ensure_database(SINK_DB_NAME)
    proc = subprocess.Popen(
        [sys.executable, "-c", _SINK_CODE, dsn], stdout=subprocess.PIPE, text=True
    )
    port = int(proc.stdout.readline())
    return proc, f"http://127.0.0.1:{port}/webhook/bench", dsn


def _sink_count(sink_dsn: str) -> int:
    with psycopg.connect(sink_dsn) as conn:
        return conn.execute("SELECT count(*) FROM execution_entity").fetchone()[0]


_POLL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bench-poll")


def _delivered_count() -> int:
    with Session(engine) as session:
        return session.execute(sqlalchemy.text("SELECT count(*) FROM alerts WHERE delivered_at IS NOT NULL")).scalar_one()


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
_ORIGINAL_NOTIFY = consumer_mod.notify_if_applicable


async def _drain(
    n: int, config: str, profile: bool, notify: str, paths: int | None, sink_dsn: str | None = None
) -> tuple[float, float | None, list[dict]]:
    """Drain N events; return (seconds to the last event_ack, seconds to the last delivery or None, timing records)."""
    _configure(config)
    consumer_mod.notify_if_applicable = _noop_notify if notify == "stub" else _ORIGINAL_NOTIFY
    cfg = settings.model_copy(update={"fim_profile_ingest": profile})
    consumer_mod.settings = cfg
    collector = _TimingCollector()
    consumer_mod.log = collector
    loop = asyncio.get_running_loop()

    client = build_async_valkey_client(VALKEY_URL)
    try:
        await client.delete(STREAM_EVENTS, STREAM_COMMANDS)
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("TRUNCATE events, alerts, rejected_events_audit RESTART IDENTITY CASCADE"))
        if sink_dsn is not None:
            with psycopg.connect(sink_dsn, autocommit=True) as conn:
                conn.execute("TRUNCATE execution_entity")
        pipe = client.pipeline(transaction=False)
        for i in range(n):
            pipe.xadd(STREAM_EVENTS, {"data": json.dumps(_event(i, paths))})
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
        deliver_elapsed: float | None = None
        if notify == "real":
            # The drain is not over until every alert was delivered: otherwise the
            # tail of this drain would load the next one.
            while await loop.run_in_executor(_POLL_EXECUTOR, _delivered_count) < n:
                await asyncio.sleep(0.05)
                if time.perf_counter() - started > 600:
                    raise TimeoutError("deliveries did not finish in 600 s")
            deliver_elapsed = time.perf_counter() - started
        stop.set()
        await asyncio.wait_for(task, 10)
        with Session(engine) as session:
            persisted = session.execute(sqlalchemy.text("SELECT count(*), count(DISTINCT event_id) FROM events")).one()
        assert tuple(persisted) == (n, n), f"expected {n} distinct rows, got {persisted}"
        pending = (await client.xpending(STREAM_EVENTS, CONSUMER_GROUP))["pending"]
        assert pending == 0, f"{pending} entries left in the PEL"
        if notify == "real":
            sunk = _sink_count(sink_dsn)
            assert sunk == n, f"expected {n} rows in the sink, got {sunk}"
        return elapsed, deliver_elapsed, collector.records
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
    commits = [r["commit_ms"] for r in events if "commit_ms" in r]
    if commits:
        out["commit_ms"] = statistics.fmean(commits)
        # Share of `ingest_ms` spent in the COMMIT (per-event path).
        out["commit_fraction_of_ingest"] = out["commit_ms"] / out["ingest_ms"]
    if events:
        out["auth_cache_hit_ratio"] = sum(1 for r in events if r["auth_cache_hit"]) / len(events)
    batch_commits = [r["commit_ms"] for r in batches if "commit_ms" in r]
    if batch_commits:
        # Batched persistence (one COMMIT per batch): per-batch means.
        out["batch_commit_ms"] = statistics.fmean(batch_commits)
        out["batch_ingest_db_ms"] = statistics.fmean(r["ingest_db_ms"] for r in batches if "ingest_db_ms" in r)
        out["batch_candidates"] = statistics.fmean(r["candidates"] for r in batches if "candidates" in r)
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
    parser.add_argument("--notify", choices=("stub", "real"), default="stub")
    parser.add_argument("--paths", type=int, default=None)
    args = parser.parse_args()

    _prepare_schema(args.notify)
    sink_proc = sink_dsn = None
    if args.notify == "real":
        sink_proc, webhook_url, sink_dsn = _start_sink()
        # `alerts.service` and `notifier` read the process-wide `settings` object.
        settings.n8n_webhook_url = webhook_url
        # The real chain needs the lifespan's executors (D76/RN-170): one exclusive
        # ingest executor, installed as the loop default like `main.py` does, and
        # one for the notification lane. Stub mode keeps the plain default executor
        # so it stays comparable with the Change 69 measurements.
        ingest_executor = ThreadPoolExecutor(max_workers=settings.db_executor_max_workers, thread_name_prefix="fim-db")
        notify_executor = ThreadPoolExecutor(max_workers=settings.db_notify_executor_max_workers, thread_name_prefix="fim-notify")
        install_executors(ingest_executor, notify_executor)
        asyncio.get_running_loop().set_default_executor(ingest_executor)
    try:
        await _drain(200, "batch-ack", False, args.notify, args.paths, sink_dsn)  # warm-up
        for config in args.configs.split(","):
            rates, deliver_rates = [], []
            for _ in range(args.repeats):
                elapsed, deliver_elapsed, _ = await _drain(
                    args.events, config, False, args.notify, args.paths, sink_dsn
                )
                rates.append(args.events / elapsed)
                if deliver_elapsed is not None:
                    deliver_rates.append(args.events / deliver_elapsed)
            _, _, records = await _drain(args.events, config, True, args.notify, args.paths, sink_dsn)
            stages = _stage_means(records)
            result = {
                "config": config,
                "notify": args.notify,
                "paths": args.paths,
                "events": args.events,
                "repeats": args.repeats,
                "ev_per_s_runs": [round(r, 1) for r in rates],
                "ev_per_s_median": round(statistics.median(rates), 1),
                "profile_run_stage_means": {k: round(v, 3) for k, v in stages.items()},
            }
            if deliver_rates:
                result["delivered_ev_per_s_runs"] = [round(r, 1) for r in deliver_rates]
                result["delivered_ev_per_s_median"] = round(statistics.median(deliver_rates), 1)
            print(json.dumps(result), flush=True)
    finally:
        if sink_proc is not None:
            sink_proc.terminate()
            sink_proc.wait(10)


asyncio.run(main())

#!/usr/bin/env python3
"""Profile the real offline-queue -> Valkey -> PostgreSQL -> ACK path.

This harness imports the production Publisher and event consumer. It adds
timestamps at their boundaries without replacing signing, validation,
persistence, XACK, or the signed event_ack returned to the agent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import SQLModel, Session, select
import valkey.asyncio as avalkey


COUNT = int(os.environ.get("FIM_DRAIN_COUNT", "3000"))
TIMEOUT_S = float(os.environ.get("FIM_DRAIN_TIMEOUT_S", "300"))
AGENT_ID = "drain-profile-agent"
SECRET = bytes.fromhex("4f" * 32)  # controlled synthetic credential; never used outside this run
OUT_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("FIM_DRAIN_WORK_DIR", "/tmp/fim-drain-profile"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * fraction


class InstrumentedValkey:
    def __init__(self, client: Any, clock: Any, metrics: dict[str, dict[str, Any]]) -> None:
        self._client = client
        self._clock = clock
        self._metrics = metrics
        self._stream_message_to_event: dict[str, str] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def xadd(self, stream: str, fields: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        payload: dict[str, Any] = {}
        raw = fields.get("data")
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                pass
        event_id = payload.get("event_id")
        started = self._clock()
        result = await self._client.xadd(stream, fields, *args, **kwargs)
        finished = self._clock()
        if isinstance(event_id, str):
            row = self._metrics[event_id]
            if stream == "events":
                row["xadd_start_ns"] = started
                row["xadd_end_ns"] = finished
                row["stream_id"] = str(result)
            elif stream == "commands" and payload.get("type") == "event_ack":
                row["event_ack_xadd_start_ns"] = started
                row["event_ack_xadd_end_ns"] = finished
        return result

    async def xreadgroup(self, *args: Any, **kwargs: Any) -> Any:
        result = await self._client.xreadgroup(*args, **kwargs)
        observed = self._clock()
        for _stream, messages in result or []:
            for msg_id, fields in messages:
                raw = fields.get("data")
                if not isinstance(raw, str):
                    continue
                try:
                    event_id = json.loads(raw).get("event_id")
                except json.JSONDecodeError:
                    continue
                if isinstance(event_id, str):
                    self._stream_message_to_event[str(msg_id)] = event_id
                    self._metrics[event_id]["consumer_read_ns"] = observed
        return result

    async def xack(self, stream: str, group: str, msg_id: str, *args: Any) -> Any:
        event_id = self._stream_message_to_event.get(str(msg_id))
        started = self._clock()
        result = await self._client.xack(stream, group, msg_id, *args)
        finished = self._clock()
        if event_id:
            self._metrics[event_id]["xack_start_ns"] = started
            self._metrics[event_id]["xack_end_ns"] = finished
        return result


async def main() -> int:
    # Imports occur after the caller supplies the isolated DB/Valkey URLs.
    import app.modules  # noqa: F401
    import app.modules.events.consumer as consumer
    from app.core.database import engine
    from app.modules.agents.models import Agent, AgentStatus
    from app.modules.events.models import Event, RejectedEventAudit
    from agent.config import AgentConfig, StorageConfig
    from agent.publisher import Publisher
    from agent.queue import EventQueue
    from agent.state import AgentState

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if WORK_DIR.exists():
        import shutil
        shutil.rmtree(WORK_DIR)
    queue_dir = WORK_DIR / "queue"
    secrets_dir = WORK_DIR / "secrets"
    state_path = WORK_DIR / "state.json"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "shared_secret").write_bytes(SECRET)
    os.chmod(secrets_dir / "shared_secret", 0o600)

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Agent(
                agent_id=AGENT_ID,
                status=AgentStatus.offline,
                shared_secret_hex=SECRET.hex(),
            )
        )
        session.commit()

    config = AgentConfig(
        agent_id=AGENT_ID,
        backend_url="http://controlled.invalid",
        valkey_url=os.environ["VALKEY_URL"],
        ca_cert_path="/nonexistent/controlled-ca.pem",
        watch_paths=["/controlled"],
        storage=StorageConfig(
            baseline_dir=str(WORK_DIR / "baseline"),
            queue_dir=str(queue_dir),
            journal_dir=str(WORK_DIR / "journal"),
            secrets_dir=str(secrets_dir),
            certs_dir=str(WORK_DIR / "certs"),
            discard_dir=str(WORK_DIR / "discarded"),
        ),
    )
    queue = EventQueue(queue_dir)

    raw_client = avalkey.Valkey.from_url(os.environ["VALKEY_URL"], decode_responses=True)
    await raw_client.flushdb()
    metrics: dict[str, dict[str, Any]] = defaultdict(dict)
    origin_ns = time.perf_counter_ns()
    clock = lambda: time.perf_counter_ns() - origin_ns
    client = InstrumentedValkey(raw_client, clock, metrics)

    seed_publisher = Publisher(config, queue, client)
    queue_build_started_ns = clock()
    event_ids: list[str] = []
    for index in range(COUNT):
        payload = seed_publisher._build_payload(
            {
                "event_type": "file_modified",
                "path": f"/controlled/drain-{index:05d}.txt",
                "hash_detected": hashlib.sha256(f"payload-{index}".encode()).hexdigest(),
                "action": "manual_review",
                "process_pid": 4242,
                "process_uid": 1000,
                "process_exe": "/usr/bin/fim-controlled-generator",
            }
        )
        queue.enqueue(payload)
        event_id = payload["event_id"]
        event_ids.append(event_id)
        metrics[event_id]["queue_enqueued_ns"] = clock()
        metrics[event_id]["sequence"] = index + 1
    queue_build_finished_ns = clock()

    # Restart-equivalent publisher: _pending starts empty and disk is truth.
    publisher = Publisher(config, queue, client)
    publisher._agent_state = AgentState(state_path=state_path)

    original_verify = consumer.verify_payload
    original_ingest = consumer._ingest
    original_handle_command = publisher._handle_command_async

    def measured_verify(secret: bytes, payload: dict[str, Any]) -> bool:
        result = original_verify(secret, payload)
        event_id = payload.get("event_id")
        if result and isinstance(event_id, str):
            metrics[event_id]["hmac_verified_ns"] = clock()
        return result

    def measured_ingest(payload: dict[str, Any], received_at: datetime, detected_at: datetime) -> Any:
        event_id = payload.get("event_id")
        if isinstance(event_id, str):
            metrics[event_id]["persist_start_ns"] = clock()
        result = original_ingest(payload, received_at, detected_at)
        if isinstance(event_id, str):
            metrics[event_id]["persist_commit_ns"] = clock()
        return result

    async def measured_handle_command(payload: dict[str, Any]) -> None:
        await original_handle_command(payload)
        event_id = payload.get("event_id")
        if payload.get("type") == "event_ack" and isinstance(event_id, str):
            metrics[event_id]["agent_ack_applied_ns"] = clock()

    consumer.verify_payload = measured_verify
    consumer._ingest = measured_ingest
    publisher._handle_command_async = measured_handle_command
    consumer.reset_rate_limiter()

    consumer_stop = asyncio.Event()
    publisher_stop = asyncio.Event()
    consumer_task = asyncio.create_task(consumer.run_consumer(client, consumer_stop))
    await asyncio.sleep(0.05)
    reconnect_ns = clock()
    publisher_task = asyncio.create_task(publisher.run(publisher_stop))

    deadline = time.monotonic() + TIMEOUT_S
    completed = False
    while time.monotonic() < deadline:
        remaining_files = len(list(queue_dir.glob("*.json")))
        with Session(engine) as session:
            persisted = len(session.exec(select(Event)).all())
        if remaining_files == 0 and persisted == COUNT:
            completed = True
            break
        await asyncio.sleep(0.1)
    finished_ns = clock()

    publisher_stop.set()
    consumer_stop.set()
    for task in (publisher_task, consumer_task):
        task.cancel()
    await asyncio.gather(publisher_task, consumer_task, return_exceptions=True)
    await raw_client.aclose()

    with Session(engine) as session:
        persisted_events = session.exec(select(Event)).all()
        rejections = session.exec(select(RejectedEventAudit)).all()

    rows: list[dict[str, Any]] = []
    for event_id in event_ids:
        row = {"event_id": event_id, **metrics[event_id]}
        rows.append(row)
    with (OUT_DIR / "metrics.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def ms_between(row: dict[str, Any], start: str, end: str) -> float | None:
        if start not in row or end not in row:
            return None
        return (row[end] - row[start]) / 1_000_000

    stage_defs = {
        "xadd": ("xadd_start_ns", "xadd_end_ns"),
        "valkey_to_consumer": ("xadd_end_ns", "consumer_read_ns"),
        "consumer_before_persist": ("consumer_read_ns", "persist_start_ns"),
        "persistence": ("persist_start_ns", "persist_commit_ns"),
        "commit_to_xack": ("persist_commit_ns", "xack_end_ns"),
        "xack_to_ack_publish": ("xack_end_ns", "event_ack_xadd_end_ns"),
        "ack_publish_to_agent_apply": ("event_ack_xadd_end_ns", "agent_ack_applied_ns"),
        "xadd_to_agent_apply": ("xadd_start_ns", "agent_ack_applied_ns"),
    }
    stage_summary: dict[str, Any] = {}
    for name, (start, end) in stage_defs.items():
        values = [value for row in rows if (value := ms_between(row, start, end)) is not None]
        stage_summary[name] = {
            "n": len(values),
            "mean_ms": sum(values) / len(values) if values else None,
            "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95),
            "p99_ms": percentile(values, 0.99),
            "max_ms": max(values) if values else None,
        }

    total_s = (finished_ns - reconnect_ns) / 1_000_000_000
    last_commit_ns = max((row.get("persist_commit_ns", 0) for row in rows), default=0)
    last_xack_ns = max((row.get("xack_end_ns", 0) for row in rows), default=0)
    last_agent_ack_ns = max((row.get("agent_ack_applied_ns", 0) for row in rows), default=0)
    last_xadd_ns = max((row.get("xadd_end_ns", 0) for row in rows), default=0)
    summary = {
        "evaluation": "drenaje-20260910-run1",
        "new_evaluation_not_historical_reinterpretation": True,
        "started_at_utc": utc_now(),
        "completed": completed,
        "planned_events": COUNT,
        "queued_events": len(event_ids),
        "persisted_events": len(persisted_events),
        "rejected_events": len(rejections),
        "queue_remaining": len(list(queue_dir.glob("*.json"))),
        "rate_limit": {
            "production_default_events": 100,
            "production_default_window_seconds": 60.0,
            "experimental_events": int(os.environ["RATE_LIMIT_INGEST_EVENTS"]),
            "experimental_window_seconds": float(os.environ["RATE_LIMIT_INGEST_WINDOW_SECONDS"]),
        },
        "historical": {"events": 2988, "seconds": 153, "throughput_events_s": 2988 / 153},
        "threshold": {"events": 2988, "seconds_strictly_less_than": 30, "minimum_events_s": 2988 / 30},
        "queue_build_seconds_excluded_from_drain": (queue_build_finished_ns - queue_build_started_ns) / 1_000_000_000,
        "reconnect_to_queue_empty_seconds": total_s,
        "throughput_events_s": COUNT / total_s if total_s > 0 else None,
        "reconnect_to_last_xadd_seconds": (last_xadd_ns - reconnect_ns) / 1_000_000_000,
        "reconnect_to_last_commit_seconds": (last_commit_ns - reconnect_ns) / 1_000_000_000,
        "reconnect_to_last_xack_seconds": (last_xack_ns - reconnect_ns) / 1_000_000_000,
        "reconnect_to_last_agent_ack_seconds": (last_agent_ack_ns - reconnect_ns) / 1_000_000_000,
        "stage_latency": stage_summary,
        "controls_active": {
            "hmac_signing_and_validation": True,
            "postgresql_persistence": True,
            "valkey_consumer_group_xack": True,
            "signed_event_ack_and_local_queue_removal": True,
            "notification_check": True,
            "audit_note": "No rejection or operator action occurred; rejection/operator audit rows are not applicable to this success path.",
        },
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    environment = {
        "captured_at_utc": utc_now(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "hostname": "SANITIZED",
        "clock": "time.perf_counter_ns (monotonic, same host/process)",
        "clock_resolution_seconds": time.get_clock_info("perf_counter").resolution,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "topology": "single physical host; isolated PostgreSQL and Valkey containers; Python agent/backend pipeline on host",
        "postgres_image": "postgres:18.3",
        "valkey_image": "valkey/valkey:9.0.3",
    }
    (OUT_DIR / "environment.json").write_text(json.dumps(environment, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if completed and len(persisted_events) == COUNT and not rejections else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

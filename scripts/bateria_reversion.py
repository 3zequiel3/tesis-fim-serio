#!/usr/bin/env python3
"""Controlled B3/B5 experiment: approved-baseline suppression and short-lived paths.

D14/RN-112 keeps the active baseline at the last approved version. ``add_snapshot``
only preserves audit history; it does not promote observed bytes. Consequently,
C0 -> C1 -> C2 -> C0 must emit for C1/C2 and suppress the return to C0.

The JSONL manifest contains hashes and paths only—never file contents or secrets.
Start the agent with the same run id and append-only trace destination:

    RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    FIM_EXPERIMENT_RUN_ID="$RUN_ID" \\
    FIM_EXPERIMENT_TRACE_FILE="/evidence/$RUN_ID/agent_trace.jsonl" \\
      docker compose --profile app up agent
    python3 scripts/bateria_reversion.py --dir fim-watch --run-id "$RUN_ID" \\
      --salida "docs/cierre/evidencia/$RUN_ID"

The compose mount maps ``./docs/cierre/evidencia`` to ``/evidence``. The trace
path is therefore valid inside the container and the host writes operations in the
same controlled, unique run directory.

Then correlate local stages, ACKs, and backend persistence with
``scripts/analisis_ausencias.py``. This tool does not start Docker or the agent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RELLENO = b"\x00" * 4076
C0 = b"integridad-aprobada-" + RELLENO
C1 = b"integridad-observada-uno-" + RELLENO[:-4]
C2 = b"integridad-observada-dos-" + RELLENO[:-4]
EPHEMERAL = b"integridad-efimera-" + RELLENO


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def safe_run_slug(run_id: str) -> str:
    """Validate the correlation id and derive a filesystem-safe opaque slug."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", run_id):
        raise ValueError("run_id must use only letters, numbers, underscores and hyphens")
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]


def scoped_run_path(directory: Path, kind: str, run_slug: str, repetition: int) -> Path:
    """Construct one experiment path and prove it cannot escape --dir."""
    root = directory.resolve()
    candidate = (root / f"{kind}_{run_slug}_{repetition:03d}.bin").resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("experiment path escapes --dir")
    return candidate


def write_bytes(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)


def append_record(
    sink: Any,
    records: list[dict[str, Any]],
    *,
    run_id: str,
    seq: int,
    case: str,
    operation: str,
    host_path: Path,
    agent_path: str,
    before_hash: str | None,
    after_hash: str | None,
    expected: bool | None,
    content_size: int | None,
    started_epoch: float,
    started_monotonic_ns: int,
    completed_epoch: float,
    completed_monotonic_ns: int,
    error: str | None = None,
) -> None:
    record = {
        "schema_version": 2,
        "run_id": run_id,
        "seq": seq,
        "operation_id": f"{run_id}:{seq}",
        "case": case,
        "operation": operation,
        "ruta_host": str(host_path),
        "ruta_agente": agent_path,
        # Compatibility aliases point at the start boundary, never after the mutation.
        "ts_utc": iso_utc(started_epoch),
        "ts_epoch": started_epoch,
        "started_epoch": started_epoch,
        "started_monotonic_ns": started_monotonic_ns,
        "completed_epoch": completed_epoch,
        "completed_monotonic_ns": completed_monotonic_ns,
        "hash_antes": before_hash,
        "hash_despues": after_hash,
        "bytes": content_size,
        # None means the ephemeral observation is intentionally experimental;
        # it is not silently counted as a successful or failed assertion.
        "deteccion_agente_esperada": expected,
        "error": error,
    }
    records.append(record)
    sink.write(json.dumps(record, ensure_ascii=False) + "\n")
    sink.flush()


def wait(seconds: float) -> None:
    if seconds:
        time.sleep(seconds)


def _operation_started() -> tuple[float, int]:
    return time.time(), time.monotonic_ns()


def _operation_completed() -> tuple[float, int]:
    return time.time(), time.monotonic_ns()


def run_approved_sequence(
    path: Path, agent_path: str, sink: Any, records: list[dict[str, Any]],
    *, run_id: str, seq: int, baseline_wait: float, event_wait: float,
) -> int:
    """C0 baseline -> C1 -> C2 -> C0; only the last operation is suppressed."""
    write_bytes(path, C0)
    wait(baseline_wait)
    previous = sha256_file(path)
    for content, name, expected in (
        (C1, "B_sucesivo_c1", True),
        (C2, "B_sucesivo_c2", True),
        (C0, "B_retorno_baseline_aprobada", False),
    ):
        started_epoch, started_monotonic_ns = _operation_started()
        try:
            write_bytes(path, content)
            error = None
        except OSError as exc:
            error = type(exc).__name__
        completed_epoch, completed_monotonic_ns = _operation_completed()
        after = sha256_file(path)
        append_record(sink, records, run_id=run_id, seq=seq, case=name, operation="modify",
                      host_path=path, agent_path=agent_path, before_hash=previous, after_hash=after,
                      expected=expected, content_size=len(content), started_epoch=started_epoch,
                      started_monotonic_ns=started_monotonic_ns, completed_epoch=completed_epoch,
                      completed_monotonic_ns=completed_monotonic_ns, error=error)
        seq += 1
        previous = after
        wait(event_wait)
    return seq


def run_create_delete(
    path: Path, agent_path: str, sink: Any, records: list[dict[str, Any]],
    *, run_id: str, seq: int, event_wait: float,
) -> int:
    started_epoch, started_monotonic_ns = _operation_started()
    write_bytes(path, C1)
    completed_epoch, completed_monotonic_ns = _operation_completed()
    append_record(sink, records, run_id=run_id, seq=seq, case="C_create", operation="create",
                  host_path=path, agent_path=agent_path, before_hash=None, after_hash=sha256_file(path),
                  expected=True, content_size=len(C1), started_epoch=started_epoch,
                  started_monotonic_ns=started_monotonic_ns, completed_epoch=completed_epoch,
                  completed_monotonic_ns=completed_monotonic_ns)
    seq += 1
    wait(event_wait)
    before = sha256_file(path)
    started_epoch, started_monotonic_ns = _operation_started()
    path.unlink()
    completed_epoch, completed_monotonic_ns = _operation_completed()
    append_record(sink, records, run_id=run_id, seq=seq, case="C_delete", operation="delete",
                  host_path=path, agent_path=agent_path, before_hash=before, after_hash=None,
                  expected=True, content_size=None, started_epoch=started_epoch,
                  started_monotonic_ns=started_monotonic_ns, completed_epoch=completed_epoch,
                  completed_monotonic_ns=completed_monotonic_ns)
    return seq + 1


def run_ephemeral(
    path: Path, agent_path: str, sink: Any, records: list[dict[str, Any]],
    *, run_id: str, seq: int,
) -> int:
    """Create/write/delete without wait; its full stage sequence stays in one slot."""
    started_epoch, started_monotonic_ns = _operation_started()
    write_bytes(path, EPHEMERAL)
    before_delete = sha256_file(path)
    path.unlink()
    completed_epoch, completed_monotonic_ns = _operation_completed()
    append_record(sink, records, run_id=run_id, seq=seq, case="D_ephemeral", operation="ephemeral",
                  host_path=path, agent_path=agent_path, before_hash=None, after_hash=None,
                  expected=None, content_size=len(EPHEMERAL), started_epoch=started_epoch,
                  started_monotonic_ns=started_monotonic_ns, completed_epoch=completed_epoch,
                  completed_monotonic_ns=completed_monotonic_ns,
                  error=None if before_delete else "write_unreadable")
    return seq + 1

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--repeticiones", type=int, default=10)
    parser.add_argument("--espera-baseline", type=float, default=5.0)
    parser.add_argument("--espera-evento", type=float, default=5.0)
    parser.add_argument("--salida", type=Path, default=Path("resultados/bateria9"))
    parser.add_argument("--agent-prefix", default=None)
    parser.add_argument("--run-id", default=None, help="Must match FIM_EXPERIMENT_RUN_ID in the agent")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.dir.is_dir() or args.repeticiones < 1 or min(args.espera_baseline, args.espera_evento) < 0:
        print("ERROR: --dir must exist, --repeticiones must be positive, waits cannot be negative")
        return 2

    run_id = args.run_id or str(uuid.uuid4())
    try:
        run_slug = safe_run_slug(run_id)
    except ValueError as exc:
        print(f"ERROR: invalid --run-id: {exc}")
        return 2
    prefix = (args.agent_prefix or str(args.dir)).rstrip("/")
    args.salida.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.salida / "bateria9_operaciones.jsonl"
    manifest_path = args.salida / f"bateria9_manifiesto_{run_slug}.json"
    if jsonl_path.exists():
        existing_runs = {
            json.loads(line).get("run_id") for line in jsonl_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        if run_id in existing_runs:
            print(f"ERROR: run_id {run_id!r} already exists in {jsonl_path}; choose a new run id.")
            return 2
    if manifest_path.exists():
        print(f"ERROR: manifest already exists for run_id {run_id!r}: {manifest_path}")
        return 2
    plan_count = args.repeticiones * 6
    print(f"run_id={run_id}; plan={plan_count} operaciones (3 sucesivas + create/delete + efímera por repetición)")
    if args.dry_run:
        print("--dry-run: no filesystem mutation. Export this run id before starting the agent.")
        return 0

    started = time.time()
    records: list[dict[str, Any]] = []
    seq = 1
    # Append only: each run is retained in the shared operations evidence file.
    with jsonl_path.open("a", encoding="utf-8") as sink:
        for rep in range(1, args.repeticiones + 1):
            baseline_path = scoped_run_path(args.dir, "baseline", run_slug, rep)
            lifecycle_path = scoped_run_path(args.dir, "lifecycle", run_slug, rep)
            ephemeral_path = scoped_run_path(args.dir, "ephemeral", run_slug, rep)
            seq = run_approved_sequence(baseline_path, f"{prefix}/{baseline_path.name}", sink, records,
                                        run_id=run_id, seq=seq, baseline_wait=args.espera_baseline, event_wait=args.espera_evento)
            seq = run_create_delete(lifecycle_path, f"{prefix}/{lifecycle_path.name}", sink, records,
                                    run_id=run_id, seq=seq, event_wait=args.espera_evento)
            seq = run_ephemeral(ephemeral_path, f"{prefix}/{ephemeral_path.name}", sink, records,
                                run_id=run_id, seq=seq)
            wait(args.espera_evento)

    manifest = {
        "schema_version": 2, "bateria": 9, "run_id": run_id,
        "title": "Baseline approved fixed: sequences, return, create/delete and ephemeral",
        "started_utc": iso_utc(started), "finished_utc": iso_utc(time.time()),
        "kernel": os.uname().release,
        "baseline_revision": "not_available; active baseline identified by status+hash",
        "operations": records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Operations: {jsonl_path}\nManifest: {manifest_path}")
    print("Correlate: python3 scripts/analisis_ausencias.py --operaciones "
          f"{jsonl_path} --traza {args.salida / 'agent_trace.jsonl'} --database-url \"$DATABASE_URL\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

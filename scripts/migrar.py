#!/usr/bin/env python3
"""Apply the numbered SQL migrations and keep the `schema_migrations` registry (D84/RN-178).

WHY IT EXISTS
    The backend builds a new schema with `SQLModel.metadata.create_all`, which never
    adds a column to an existing table. Columns added later arrive as manual scripts in
    `backend/db/migrations/`, and nothing recorded which ones were applied. The backend
    now refuses to start when the registry is behind its `EXPECTED_SCHEMA_VERSION`
    (`backend/app/core/schema_version.py`); this tool is how the registry gets filled.

MODES
    migrar.py                    apply the pending migrations in ascending order, one
                                 transaction per migration that also holds its registry row.
                                 On a NEW database (no application tables) it applies `000`
                                 and registers `1..N` WITHOUT executing them: `create_all`
                                 builds the current shape on the first backend start (D3).
    migrar.py --marcar-hasta N   EXISTING database without a registry: apply `000` if missing
                                 and register versions `1..N` without executing them.
                                 Nothing after N is applied. When in doubt, mark a LOWER
                                 version and let a plain run apply the rest: the migrations
                                 are idempotent.
    migrar.py --verificar        read-only: check sha256 and compare the registry with the
                                 tree. Never writes.

INTEGRITY
    Before doing anything, the sha256 (raw bytes of the file) of every registered version is
    compared with the file in the tree. A mismatch, or a registered version with no file,
    aborts without touching the database.

CONNECTION
    Default: `docker compose [-p P] [-f F]... exec -T db psql -X -q -v ON_ERROR_STOP=1`
    (the db service does not publish 5432; standard library only).
    `--dsn URL`: direct connection through `psycopg` (imported lazily).

EXIT CODES
    0  success / up to date
    1  execution or connection failure
    2  usage error or invalid migration tree
    3  integrity: sha256 mismatch, registered version without file, registry gap,
       existing database without a registry
    4  `--verificar` found pending migrations

INSTALL (new database)
    docker compose up -d --wait db
    python3 scripts/migrar.py            # BEFORE the first backend start
    docker compose --profile app up -d

UPGRADE (existing database that has no registry yet)
    python3 scripts/migrar.py --marcar-hasta 22   # highest version actually applied
    python3 scripts/migrar.py                     # apply anything pending
    python3 scripts/migrar.py --verificar         # exit 0
    # then restart the backend
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "backend" / "db" / "migrations"
NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
REGISTRY_TABLE = "schema_migrations"

EXIT_OK = 0
EXIT_EXECUTION = 1
EXIT_USAGE = 2
EXIT_INTEGRITY = 3
EXIT_PENDING = 4


# ── Errors ───────────────────────────────────────────────────────────────────

class MigrationError(Exception):
    exit_code = EXIT_EXECUTION


class ExecutionError(MigrationError):
    exit_code = EXIT_EXECUTION


class UsageError(MigrationError):
    exit_code = EXIT_USAGE


class TreeError(MigrationError):
    exit_code = EXIT_USAGE


class IntegrityError(MigrationError):
    exit_code = EXIT_INTEGRITY


class PendingError(MigrationError):
    exit_code = EXIT_PENDING


# ── Tree ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    sha256: str
    path: Path


def read_tree(directory: Path) -> list[Migration]:
    """Read and validate the migration tree: names, no duplicates, contiguous from 000.

    The name regex also guarantees that `filename` is safe to interpolate in the INSERT.
    """
    if not directory.is_dir():
        raise TreeError(f"migrations directory not found: {directory}")
    found: dict[int, list[Path]] = {}
    for path in sorted(directory.iterdir()):
        if path.suffix != ".sql":
            continue
        match = NAME_RE.match(path.name)
        if not match:
            raise TreeError(f"invalid migration file name (expected NNN_name.sql): {path.name}")
        found.setdefault(int(match.group(1)), []).append(path)

    duplicates = {v: ps for v, ps in found.items() if len(ps) > 1}
    if duplicates:
        detail = "; ".join(
            f"{v:03d}: {', '.join(p.name for p in ps)}" for v, ps in sorted(duplicates.items())
        )
        raise TreeError(f"duplicate migration numbers: {detail}")
    if 0 not in found:
        raise TreeError("missing migration 000 (000_schema_migrations.sql)")
    missing = [v for v in range(max(found) + 1) if v not in found]
    if missing:
        raise TreeError(
            "gap in migration numbering, missing version(s): "
            + ", ".join(f"{v:03d}" for v in missing)
        )

    return [
        Migration(
            version=v,
            filename=found[v][0].name,
            sha256=hashlib.sha256(found[v][0].read_bytes()).hexdigest(),
            path=found[v][0],
        )
        for v in sorted(found)
    ]


# ── Plan (pure) ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Action:
    kind: str  # "apply" | "register"
    migration: Migration


def plan(
    tree: list[Migration],
    registry: dict[int, tuple[str, str]],
    has_app_tables: bool,
    mark_upto: int | None = None,
    verify: bool = False,
) -> list[Action]:
    """Decide what to do. Pure: no I/O. Raises a typed error mapped to an exit code.

    `registry` maps version -> (filename, sha256). Verification order: registered rows
    against the tree (file + sha256), classification of the database, pending versions.
    """
    by_version = {m.version: m for m in tree}
    highest = max(by_version)

    problems: list[str] = []
    for version, (_filename, registered_sha) in sorted(registry.items()):
        migration = by_version.get(version)
        if migration is None:
            problems.append(f"version {version} is registered but has no file in the tree")
        elif migration.sha256 != registered_sha:
            problems.append(
                f"version {version} ({migration.filename}) was modified after being applied: "
                f"registered sha256 {registered_sha}, file sha256 {migration.sha256}"
            )
    if problems:
        raise IntegrityError("; ".join(problems))

    pending = [m for m in tree if m.version not in registry]
    max_registered = max(registry) if registry else None

    if verify:
        gap = [m for m in pending if max_registered is not None and m.version < max_registered]
        if gap:
            raise IntegrityError(_gap_message(gap, max_registered))
        if pending:
            raise PendingError(
                "pending migrations: " + ", ".join(m.filename for m in pending)
                + f" (registry at {max_registered}, tree at {highest})"
            )
        return []

    if mark_upto is not None:
        if mark_upto < 1 or mark_upto > highest:
            raise UsageError(
                f"--marcar-hasta {mark_upto} is out of range (the tree goes from 1 to {highest})"
            )
        if not has_app_tables:
            raise UsageError(
                "--marcar-hasta is for existing databases; this database has no application "
                "tables, and a plain run already registers up to the highest version"
            )
        actions = [Action("apply", by_version[0])] if 0 in {m.version for m in pending} else []
        actions += [Action("register", m) for m in pending if 1 <= m.version <= mark_upto]
        return actions

    if not has_app_tables:
        # New database: 000 is applied, 1..N are registered without executing them.
        return [
            Action("apply" if m.version == 0 else "register", m) for m in pending
        ]

    if not any(v > 0 for v in registry):
        raise IntegrityError(
            "existing database without a registry: register the versions already applied "
            f"with `--marcar-hasta N` (highest version in the tree: {highest})"
        )
    gap = [m for m in pending if m.version < max_registered]
    if gap:
        raise IntegrityError(_gap_message(gap, max_registered))
    return [Action("apply", m) for m in pending]


def _gap_message(gap: list[Migration], max_registered: int) -> str:
    return (
        "gap in the registry: version(s) "
        + ", ".join(str(m.version) for m in gap)
        + f" are not registered but version {max_registered} is; "
        "register them with `--marcar-hasta` or fix the registry by hand"
    )


# ── Executors ────────────────────────────────────────────────────────────────

class Executor(Protocol):
    def query(self, sql: str) -> list[tuple[str, ...]]: ...

    def transaction(self, sql: str) -> None: ...


class ComposeExecutor:
    """Runs SQL through `docker compose exec -T <service> psql` (no published port)."""

    def __init__(
        self,
        compose_files: list[str] | None = None,
        project_name: str | None = None,
        service: str = "db",
        user: str = "fim",
        database: str = "fim",
    ) -> None:
        self.compose_files = compose_files or []
        self.project_name = project_name
        self.service = service
        self.user = user
        self.database = database

    def _base(self) -> list[str]:
        cmd = ["docker", "compose"]
        if self.project_name:
            cmd += ["-p", self.project_name]
        for compose_file in self.compose_files:
            cmd += ["-f", compose_file]
        cmd += [
            "exec", "-T", self.service,
            "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", self.user, "-d", self.database,
        ]
        return cmd

    def _run(self, extra: list[str], stdin: str | None = None) -> str:
        try:
            result = subprocess.run(
                self._base() + extra, input=stdin, capture_output=True, text=True
            )
        except OSError as exc:
            raise ExecutionError(f"could not run docker compose: {exc}") from exc
        if result.returncode != 0:
            raise ExecutionError(
                f"psql exited with code {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout

    def query(self, sql: str) -> list[tuple[str, ...]]:
        out = self._run(["-A", "-t", "-F", "|", "-c", sql])
        return [tuple(line.split("|")) for line in out.splitlines() if line.strip()]

    def transaction(self, sql: str) -> None:
        self._run(["--single-transaction", "-f", "-"], stdin=sql)


class DsnExecutor:
    """Runs SQL over a direct `psycopg` connection (`--dsn`)."""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
        except ImportError as exc:
            raise ExecutionError(
                "--dsn needs the `psycopg` package (pip install 'psycopg[binary]')"
            ) from exc
        self._psycopg = psycopg
        self.dsn = re.sub(r"^postgresql\+psycopg://", "postgresql://", dsn)

    def query(self, sql: str) -> list[tuple[str, ...]]:
        try:
            with self._psycopg.connect(self.dsn, autocommit=True) as conn:
                return [tuple(str(c) for c in row) for row in conn.execute(sql).fetchall()]
        except self._psycopg.Error as exc:
            raise ExecutionError(str(exc).strip()) from exc

    def transaction(self, sql: str) -> None:
        try:
            with self._psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.transaction():
                    conn.execute(sql)
        except self._psycopg.Error as exc:
            raise ExecutionError(str(exc).strip()) from exc


# ── Execution ────────────────────────────────────────────────────────────────

def read_registry(executor: Executor) -> dict[int, tuple[str, str]]:
    exists = executor.query(f"SELECT to_regclass('public.{REGISTRY_TABLE}') IS NOT NULL")
    if not exists or exists[0][0] not in ("t", "True", "true"):
        return {}
    rows = executor.query(f"SELECT version, filename, sha256 FROM {REGISTRY_TABLE} ORDER BY version")
    return {int(r[0]): (r[1], r[2].strip()) for r in rows}


def has_app_tables(executor: Executor) -> bool:
    rows = executor.query(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
        f"AND tablename <> '{REGISTRY_TABLE}'"
    )
    return int(rows[0][0]) > 0


def _insert_row(m: Migration) -> str:
    return (
        f"INSERT INTO {REGISTRY_TABLE} (version, filename, sha256) "
        f"VALUES ({m.version}, '{m.filename}', '{m.sha256}');\n"
    )


def execute(actions: list[Action], executor: Executor, out: Callable[[str], None]) -> None:
    for action in actions:
        m = action.migration
        try:
            if action.kind == "apply":
                # File and registry row share ONE transaction: both persist or neither.
                executor.transaction(m.path.read_text(encoding="utf-8") + "\n" + _insert_row(m))
                out(f"applied    {m.filename}")
            else:
                executor.transaction(_insert_row(m))
                out(f"registered {m.filename} (not executed)")
        except ExecutionError as exc:
            raise ExecutionError(f"{m.filename} failed: {exc}") from exc


def run(
    tree: list[Migration],
    executor: Executor,
    mark_upto: int | None,
    verify: bool,
    out: Callable[[str], None] = print,
) -> int:
    registry = read_registry(executor)
    initial = max(registry) if registry else None
    actions = plan(tree, registry, has_app_tables(executor), mark_upto, verify)
    if verify:
        out(f"schema up to date at version {initial}")
        return EXIT_OK
    if not actions:
        out(f"nothing to do: schema at version {initial}")
        return EXIT_OK
    execute(actions, executor, out)
    final = max([a.migration.version for a in actions] + ([initial] if initial is not None else []))
    out(f"schema version: {initial} -> {final}")
    return EXIT_OK


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply SQL migrations and maintain the schema_migrations registry (D84/RN-178)."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--marcar-hasta", type=int, metavar="N",
                      help="register versions 1..N of an existing database without executing them")
    mode.add_argument("--verificar", action="store_true",
                      help="read-only check: exit 0 when up to date, 4 when pending")
    parser.add_argument("--dsn", help="connect directly to this URL instead of docker compose exec")
    parser.add_argument("-f", "--compose-file", action="append", default=[],
                        help="compose file (repeatable)")
    parser.add_argument("-p", "--project-name", help="compose project name")
    parser.add_argument("--servicio", default="db", help="compose service running postgres")
    parser.add_argument("--usuario", default="fim", help="database user")
    parser.add_argument("--base", default="fim", help="database name")
    parser.add_argument("--migraciones", type=Path, default=DEFAULT_MIGRATIONS_DIR,
                        help="migrations directory (default: backend/db/migrations)")
    return parser


def main(
    argv: list[str] | None = None,
    executor_factory: Callable[[argparse.Namespace], Executor] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        tree = read_tree(args.migraciones)
        if executor_factory is not None:
            executor = executor_factory(args)
        elif args.dsn:
            executor = DsnExecutor(args.dsn)
        else:
            executor = ComposeExecutor(
                args.compose_file, args.project_name, args.servicio, args.usuario, args.base
            )
        return run(tree, executor, args.marcar_hasta, args.verificar)
    except MigrationError as exc:
        print(f"migrar.py: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())

"""D84/RN-178 (Change 66) — tests for `scripts/migrar.py`.

Tree, plan, integrity, failure and `--verificar` run against a fake executor that keeps
the registry in memory. The compose command line is pinned by patching `subprocess.run`.
Integration tests (`-m integration`) run `--dsn` against an ephemeral database of the test
Postgres (`TEST_DATABASE_URL`) and need `psycopg`.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "migrar.py"
REAL_TREE = Path(__file__).resolve().parents[2] / "backend" / "db" / "migrations"

_spec = importlib.util.spec_from_file_location("migrar", SCRIPT)
migrar = importlib.util.module_from_spec(_spec)
sys.modules["migrar"] = migrar
_spec.loader.exec_module(migrar)


# ── Helpers ──────────────────────────────────────────────────────────────────

REGISTRY_SQL = "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY);\n"


def make_tree(root: Path, names: list[str], body: str = "SELECT 1;\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).write_text(REGISTRY_SQL if name.startswith("000_") else body)
    return root


def names_upto(n: int) -> list[str]:
    return ["000_schema_migrations.sql"] + [f"{v:03d}_m{v}.sql" for v in range(1, n + 1)]


class FakeExecutor:
    """In-memory database: `tables` are application tables, `registry` maps rows."""

    ROW = re.compile(r"VALUES \((\d+), '([^']+)', '([0-9a-f]{64})'\)")

    def __init__(self, tables=0, registry=None, fail_on=None, has_registry=None):
        self.tables = tables
        self.registry = dict(registry or {})
        self.has_registry = bool(self.registry) if has_registry is None else has_registry
        self.fail_on = fail_on
        self.transactions: list[str] = []
        self.queries: list[str] = []

    def query(self, sql):
        self.queries.append(sql)
        if "to_regclass" in sql:
            return [("t" if self.has_registry else "f",)]
        if "FROM schema_migrations" in sql:
            return [(str(v), f, s) for v, (f, s) in sorted(self.registry.items())]
        if "pg_tables" in sql:
            return [(str(self.tables),)]
        raise AssertionError(sql)

    def transaction(self, sql):
        if self.fail_on and self.fail_on in sql:
            raise migrar.ExecutionError("boom")
        self.transactions.append(sql)
        for v, f, s in self.ROW.findall(sql):
            self.registry[int(v)] = (f, s)
            self.has_registry = True


def registry_for(tree, upto):
    return {m.version: (m.filename, m.sha256) for m in tree if m.version <= upto}


def run_cli(tmp_path, n, executor, *args):
    tree_dir = make_tree(tmp_path / "tree", names_upto(n))
    argv = ["--migraciones", str(tree_dir), *args]
    code = migrar.main(argv, executor_factory=lambda _a: executor)
    return code, migrar.read_tree(tree_dir)


# ── 6.1 Tree ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "names, fragment",
    [
        (["000_schema_migrations.sql", "001_a.sql", "003_c.sql"], "002"),
        (["000_schema_migrations.sql", "001_a.sql", "001_b.sql"], "duplicate"),
        (["000_schema_migrations.sql", "01_bad.sql"], "invalid migration file name"),
        (["000_schema_migrations.sql", "002_Bad.sql"], "invalid migration file name"),
        (["001_a.sql", "002_b.sql"], "000"),
    ],
)
def test_invalid_tree_exits_2_without_touching_the_executor(tmp_path, capsys, names, fragment):
    tree_dir = make_tree(tmp_path / "tree", names)

    def factory(_args):
        raise AssertionError("the executor must not be created for an invalid tree")

    code = migrar.main(["--migraciones", str(tree_dir)], executor_factory=factory)
    assert code == 2
    assert fragment in capsys.readouterr().err


def test_real_tree_is_valid():
    tree = migrar.read_tree(REAL_TREE)
    assert [m.version for m in tree] == list(range(len(tree)))


# ── 6.2 Plan ─────────────────────────────────────────────────────────────────

def test_new_database_applies_000_and_registers_the_rest_without_executing(tmp_path):
    ex = FakeExecutor(tables=0)
    code, tree = run_cli(tmp_path, 3, ex)
    assert code == 0
    assert set(ex.registry) == {0, 1, 2, 3}
    assert len(ex.transactions) == 4
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in ex.transactions[0]
    assert all("SELECT 1" not in t for t in ex.transactions[1:])


def test_new_database_with_marcar_hasta_is_a_usage_error(tmp_path):
    ex = FakeExecutor(tables=0)
    code, _ = run_cli(tmp_path, 3, ex, "--marcar-hasta", "2")
    assert code == 2 and ex.transactions == []


def test_existing_database_without_registry_aborts_with_3(tmp_path, capsys):
    ex = FakeExecutor(tables=5)
    code, _ = run_cli(tmp_path, 3, ex)
    assert code == 3 and ex.transactions == []
    assert "--marcar-hasta" in capsys.readouterr().err


def test_existing_database_with_registry_holding_only_000_aborts_with_3(tmp_path):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(2)))
    ex = FakeExecutor(tables=5, registry=registry_for(tree, 0))
    code, _ = run_cli(tmp_path, 2, ex)
    assert code == 3 and ex.transactions == []


def test_marcar_hasta_registers_without_executing_and_applies_nothing_later(tmp_path):
    ex = FakeExecutor(tables=5)
    code, _ = run_cli(tmp_path, 4, ex, "--marcar-hasta", "2")
    assert code == 0
    assert set(ex.registry) == {0, 1, 2}
    assert all("SELECT 1" not in t for t in ex.transactions[1:])


@pytest.mark.parametrize("n", ["0", "5", "-1"])
def test_marcar_hasta_out_of_range_is_rejected(tmp_path, n):
    ex = FakeExecutor(tables=5)
    code, _ = run_cli(tmp_path, 4, ex, f"--marcar-hasta={n}")
    assert code == 2 and ex.transactions == []


def test_two_pending_are_applied_in_order_one_transaction_each(tmp_path):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(4)))
    ex = FakeExecutor(tables=5, registry=registry_for(tree, 2))
    code, _ = run_cli(tmp_path, 4, ex)
    assert code == 0
    assert len(ex.transactions) == 2
    assert "'003_m3.sql'" in ex.transactions[0] and "'004_m4.sql'" in ex.transactions[1]
    assert "SELECT 1" in ex.transactions[0]
    assert max(ex.registry) == 4


def test_nothing_pending_runs_nothing(tmp_path):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(2)))
    ex = FakeExecutor(tables=5, registry=registry_for(tree, 2))
    code, _ = run_cli(tmp_path, 2, ex)
    assert code == 0 and ex.transactions == []


def test_gap_in_the_registry_aborts_with_3(tmp_path):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(4)))
    registry = registry_for(tree, 4)
    del registry[2]
    ex = FakeExecutor(tables=5, registry=registry)
    code, _ = run_cli(tmp_path, 4, ex)
    assert code == 3 and ex.transactions == []


# ── 6.3 Integrity ────────────────────────────────────────────────────────────

def test_sha_mismatch_and_missing_file_abort_before_any_action(tmp_path, capsys):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(3)))
    registry = registry_for(tree, 2)
    registry[2] = (registry[2][0], "f" * 64)  # edited after being applied
    registry[7] = ("007_gone.sql", "a" * 64)  # no file in the tree
    ex = FakeExecutor(tables=5, registry=registry)
    code, _ = run_cli(tmp_path, 3, ex)
    err = capsys.readouterr().err
    assert code == 3 and ex.transactions == []
    assert "version 2" in err and "f" * 64 in err
    assert "version 7" in err


# ── 6.4 Failure ──────────────────────────────────────────────────────────────

def test_failure_stops_before_the_next_pending_and_names_the_file(tmp_path, capsys):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(4)))
    ex = FakeExecutor(tables=5, registry=registry_for(tree, 1), fail_on="'003_m3.sql'")
    code, _ = run_cli(tmp_path, 4, ex)
    assert code == 1
    assert max(ex.registry) == 2
    assert not any("004_m4.sql" in t for t in ex.transactions)
    assert "003_m3.sql" in capsys.readouterr().err


# ── 6.5 --verificar ──────────────────────────────────────────────────────────

def test_verify_up_to_date_returns_0_and_never_writes(tmp_path):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(3)))
    ex = FakeExecutor(tables=5, registry=registry_for(tree, 3))
    code, _ = run_cli(tmp_path, 3, ex, "--verificar")
    assert code == 0 and ex.transactions == []


def test_verify_with_pending_returns_4_and_never_writes(tmp_path, capsys):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(3)))
    ex = FakeExecutor(tables=5, registry=registry_for(tree, 2))
    code, _ = run_cli(tmp_path, 3, ex, "--verificar")
    assert code == 4 and ex.transactions == []
    assert "003_m3.sql" in capsys.readouterr().err


def test_verify_without_registry_returns_4(tmp_path):
    ex = FakeExecutor(tables=5)
    code, _ = run_cli(tmp_path, 3, ex, "--verificar")
    assert code == 4 and ex.transactions == []


def test_verify_detects_sha_mismatch_with_3(tmp_path):
    tree = migrar.read_tree(make_tree(tmp_path / "t", names_upto(2)))
    registry = registry_for(tree, 2)
    registry[1] = (registry[1][0], "0" * 64)
    ex = FakeExecutor(tables=5, registry=registry)
    code, _ = run_cli(tmp_path, 2, ex, "--verificar")
    assert code == 3


def test_marcar_hasta_and_verificar_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        migrar.main(["--marcar-hasta", "3", "--verificar"])


# ── 6.6 Compose command line ─────────────────────────────────────────────────

def test_compose_executor_command_lines(monkeypatch):
    calls = []

    def fake_run(cmd, input=None, capture_output=None, text=None):
        calls.append((cmd, input))
        return subprocess.CompletedProcess(cmd, 0, stdout="t\n", stderr="")

    monkeypatch.setattr(migrar.subprocess, "run", fake_run)
    ex = migrar.ComposeExecutor(["a.yml", "b.yml"], "proj", "db", "fim", "fim")

    assert ex.query("SELECT 1") == [("t",)]
    ex.transaction("SELECT 2;")

    head = ["docker", "compose", "-p", "proj", "-f", "a.yml", "-f", "b.yml", "exec", "-T", "db",
            "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "fim", "-d", "fim"]
    assert calls[0] == (head + ["-A", "-t", "-F", "|", "-c", "SELECT 1"], None)
    assert calls[1] == (head + ["--single-transaction", "-f", "-"], "SELECT 2;")


def test_compose_executor_failure_becomes_execution_error(monkeypatch):
    monkeypatch.setattr(
        migrar.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 3, stdout="", stderr="ERROR: nope"),
    )
    with pytest.raises(migrar.ExecutionError, match="nope"):
        migrar.ComposeExecutor().query("SELECT 1")


# ── 6.7 Integration (--dsn against an ephemeral database) ────────────────────

@pytest.fixture
def ephemeral_dsn():
    psycopg = pytest.importorskip("psycopg")
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL not set")
    base = re.sub(r"^postgresql\+psycopg://", "postgresql://", base)
    server, _, _db = base.rpartition("/")
    name = f"fim_migrar_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield f"{server}/{name}"
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _real_000(tree_dir: Path) -> None:
    (tree_dir / "000_schema_migrations.sql").write_bytes(
        (REAL_TREE / "000_schema_migrations.sql").read_bytes()
    )


def _scalar(dsn, sql):
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(sql).fetchone()[0]


@pytest.mark.integration
def test_integration_new_database_registers_everything_and_creates_no_tables(
    tmp_path, ephemeral_dsn
):
    tree = tmp_path / "tree"
    tree.mkdir()
    _real_000(tree)
    (tree / "001_t1.sql").write_text("CREATE TABLE t1 (id int);\n")
    (tree / "002_t2.sql").write_text("CREATE TABLE t2 (id int);\n")

    assert migrar.main(["--dsn", ephemeral_dsn, "--migraciones", str(tree)]) == 0

    assert _scalar(ephemeral_dsn, "SELECT array_agg(version ORDER BY version) FROM schema_migrations") == [0, 1, 2]
    assert _scalar(
        ephemeral_dsn,
        "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename <> 'schema_migrations'",
    ) == 0
    assert migrar.main(["--dsn", ephemeral_dsn, "--migraciones", str(tree), "--verificar"]) == 0


@pytest.mark.integration
def test_integration_failing_migration_leaves_no_row_and_no_partial_change(
    tmp_path, ephemeral_dsn
):
    import psycopg

    tree = tmp_path / "tree"
    tree.mkdir()
    _real_000(tree)
    (tree / "001_t1.sql").write_text("CREATE TABLE t1 (id int);\n")
    (tree / "002_broken.sql").write_text("CREATE TABLE t2 (id int);\nSELECT 1/0;\n")
    # An existing database: it has an application table, registry only up to 1.
    with psycopg.connect(ephemeral_dsn, autocommit=True) as conn:
        conn.execute("CREATE TABLE t1 (id int)")
    assert migrar.main(["--dsn", ephemeral_dsn, "--migraciones", str(tree), "--marcar-hasta", "1"]) == 0

    code = migrar.main(["--dsn", ephemeral_dsn, "--migraciones", str(tree)])

    assert code == 1
    assert _scalar(ephemeral_dsn, "SELECT max(version) FROM schema_migrations") == 1
    assert _scalar(ephemeral_dsn, "SELECT to_regclass('public.t2') IS NULL") is True


@pytest.mark.integration
def test_integration_marcar_hasta_does_not_execute_migration_sql(tmp_path, ephemeral_dsn):
    import psycopg

    tree = tmp_path / "tree"
    tree.mkdir()
    _real_000(tree)
    (tree / "001_would_fail.sql").write_text("SELECT 1/0;\n")
    with psycopg.connect(ephemeral_dsn, autocommit=True) as conn:
        conn.execute("CREATE TABLE app_table (id int)")

    code = migrar.main(["--dsn", ephemeral_dsn, "--migraciones", str(tree), "--marcar-hasta", "1"])

    assert code == 0
    assert _scalar(ephemeral_dsn, "SELECT max(version) FROM schema_migrations") == 1


@pytest.mark.integration
def test_integration_edited_migration_aborts_with_sha_mismatch(tmp_path, ephemeral_dsn):
    tree = tmp_path / "tree"
    tree.mkdir()
    _real_000(tree)
    (tree / "001_a.sql").write_text("SELECT 1;\n")
    assert migrar.main(["--dsn", ephemeral_dsn, "--migraciones", str(tree)]) == 0
    (tree / "001_a.sql").write_text("SELECT 2;\n")

    assert migrar.main(["--dsn", ephemeral_dsn, "--migraciones", str(tree)]) == 3

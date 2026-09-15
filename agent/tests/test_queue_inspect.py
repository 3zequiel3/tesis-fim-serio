"""Tests for `agent/queue_inspect.py` — the root-only, read-only forensic
CLI for the encrypted offline queue and discard directory (D-9 / D63 /
RN-157). Cubre tasks.md task 7.8.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import agent.queue_inspect as qi
from agent.config import AgentConfig, StorageConfig
from agent.queue import EventQueue
from agent.tests.conftest import TEST_AGENT_ID, TEST_MASTER_SECRET


def _make_config(tmp_path: Path) -> AgentConfig:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "master_secret").write_bytes(TEST_MASTER_SECRET)
    return AgentConfig(
        agent_id=TEST_AGENT_ID,
        backend_url="http://localhost:8000",
        valkey_url="redis://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/tmp"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(secrets_dir),
            certs_dir=str(tmp_path / "certs"),
            discard_dir=str(tmp_path / "discarded"),
        ),
    )


def _snapshot(directory: Path) -> dict[str, tuple[int, int, bytes]]:
    if not directory.exists():
        return {}
    return {
        f.name: (f.stat().st_size, f.stat().st_mtime_ns, f.read_bytes())
        for f in directory.glob("*.json")
    }


@pytest.fixture()
def populated_queue(tmp_path: Path) -> tuple[AgentConfig, EventQueue, Path]:
    cfg = _make_config(tmp_path)
    queue = EventQueue(
        cfg.storage.queue_dir,
        master_secret=TEST_MASTER_SECRET,
        agent_id=cfg.agent_id,
        discard_dir=cfg.storage.discard_dir,
    )
    evt = {
        "event_id": "evt-1",
        "detected_at": "2026-01-01T00:00:00+00:00",
        "path": "/etc/passwd",
        "hash_detected": "abc123",
        "schema_version": 1,
        "diff_text": "-old\n+new",
    }
    path = queue.enqueue(evt)
    return cfg, queue, path


# ── Chequeo de root ──────────────────────────────────────────────────────────


def test_non_root_user_is_rejected_before_reading_anything(
    populated_queue: tuple[AgentConfig, EventQueue, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cfg, _queue, _path = populated_queue
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    def _fail_if_called(*_a: object, **_kw: object) -> None:
        raise AssertionError("must not read config before the root check")

    monkeypatch.setattr(qi, "load_config", _fail_if_called)

    with pytest.raises(SystemExit) as excinfo:
        qi.main(["--config", "irrelevant.yaml"])
    assert excinfo.value.code != 0


# ── --print con la clave correcta ────────────────────────────────────────────


def test_print_with_correct_key_returns_identical_envelope(
    populated_queue: tuple[AgentConfig, EventQueue, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg, _queue, path = populated_queue
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(qi, "load_config", lambda _path: cfg)

    exit_code = qi.main(["--config", "irrelevant.yaml", "--dir", "queue", "--print", path.name])
    assert exit_code == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["payload"]["event_id"] == "evt-1"
    assert printed["payload"]["diff_text"] == "-old\n+new"
    assert printed["attempts"] == 0


# ── --print con clave incorrecta o archivo manipulado ────────────────────────


def test_print_with_wrong_master_secret_reports_reason_without_traceback(
    populated_queue: tuple[AgentConfig, EventQueue, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg, _queue, path = populated_queue
    (Path(cfg.storage.secrets_dir) / "master_secret").write_bytes(os.urandom(32))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(qi, "load_config", lambda _path: cfg)

    exit_code = qi.main(["--config", "irrelevant.yaml", "--dir", "queue", "--print", path.name])
    assert exit_code != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "authentication_failed" in captured.err


def test_print_with_tampered_ciphertext_reports_reason_without_traceback(
    populated_queue: tuple[AgentConfig, EventQueue, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg, _queue, path = populated_queue
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0xFF
    path.write_bytes(bytes(raw))

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(qi, "load_config", lambda _path: cfg)

    exit_code = qi.main(["--config", "irrelevant.yaml", "--dir", "queue", "--print", path.name])
    assert exit_code != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "authentication_failed" in captured.err


# ── Modo lista ────────────────────────────────────────────────────────────────


def test_list_mode_prints_status_without_content(
    populated_queue: tuple[AgentConfig, EventQueue, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg, _queue, path = populated_queue
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(qi, "load_config", lambda _path: cfg)

    exit_code = qi.main(["--config", "irrelevant.yaml", "--dir", "queue"])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert path.name in out
    assert "ok" in out
    assert "diff_text" not in out
    assert "-old" not in out
    assert "+new" not in out


# ── Solo lectura: nunca modifica nada, en ningún modo ────────────────────────


def test_command_never_writes_in_any_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _make_config(tmp_path)
    queue = EventQueue(
        cfg.storage.queue_dir,
        master_secret=TEST_MASTER_SECRET,
        agent_id=cfg.agent_id,
        discard_dir=cfg.storage.discard_dir,
    )
    evt = {
        "event_id": "ro-1",
        "detected_at": "2026-01-01T00:00:00+00:00",
        "path": "/etc/hosts",
        "hash_detected": "def456",
        "schema_version": 1,
    }
    path = queue.enqueue(evt)
    # Un archivo en claro heredado también debe quedar intacto: el CLI nunca
    # corre la pasada de migración de D-5, a diferencia de EventQueue (D-9).
    legacy = queue._dir / "0000000000000001_legacy.json"
    legacy.write_text(
        json.dumps({"payload": {"event_id": "legacy"}, "attempts": 0, "first_attempt_at": None})
    )

    before_queue = _snapshot(queue._dir)
    before_discard = _snapshot(queue._discard_dir)

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(qi, "load_config", lambda _path: cfg)

    qi.main(["--config", "irrelevant.yaml", "--dir", "both"])
    qi.main(["--config", "irrelevant.yaml", "--dir", "both", "--print", path.name])
    qi.main(["--config", "irrelevant.yaml", "--dir", "both", "--print", legacy.name])

    after_queue = _snapshot(queue._dir)
    after_discard = _snapshot(queue._discard_dir)

    assert before_queue == after_queue
    assert before_discard == after_discard
    assert set(after_queue) == {path.name, legacy.name}

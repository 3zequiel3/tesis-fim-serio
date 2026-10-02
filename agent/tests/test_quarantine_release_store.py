"""Tests of QuarantineStore.load_for_release / remove_artifact (D83/RN-177, tasks 1.1-1.3)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from agent.quarantine import QuarantineError, QuarantineStore

_CONTENT = b"quarantined payload\n"
_SHA = hashlib.sha256(_CONTENT).hexdigest()


@pytest.fixture()
def store(tmp_path: Path) -> QuarantineStore:
    return QuarantineStore(tmp_path / "quarantine", os.urandom(32), "agent-x")


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    watch = tmp_path / "watch"
    watch.mkdir()
    target = watch / "evil.conf"
    target.write_bytes(_CONTENT)
    os.chmod(target, 0o4755)
    return target


def _reason(exc_info: pytest.ExceptionInfo[QuarantineError]) -> str:
    return exc_info.value.reason


def test_load_for_release_returns_authenticated_artifact(store, source) -> None:
    store.quarantine("evt-1", str(source))
    artifact = store.load_for_release("evt-1", str(source), _SHA)
    assert artifact.content == _CONTENT
    assert artifact.metadata["action_id"] == "evt-1"
    assert artifact.metadata["sha256"] == _SHA


def test_load_for_release_without_content(store, source) -> None:
    store.quarantine("evt-1", str(source))
    artifact = store.load_for_release("evt-1", str(source), _SHA, include_content=False)
    assert artifact.content == b""
    assert artifact.metadata["sha256"] == _SHA


def test_load_for_release_missing_artifact(store, source) -> None:
    with pytest.raises(QuarantineError) as exc:
        store.load_for_release("evt-1", str(source), _SHA)
    assert _reason(exc) == "artifact_not_found"


def test_load_for_release_tampered_artifact(store, source) -> None:
    store.quarantine("evt-1", str(source))
    artifact_path = store.artifact_path("evt-1", str(source))
    os.chmod(artifact_path, 0o600)
    raw = bytearray(artifact_path.read_bytes())
    raw[40] ^= 0xFF
    artifact_path.write_bytes(bytes(raw))
    with pytest.raises(QuarantineError) as exc:
        store.load_for_release("evt-1", str(source), _SHA)
    assert _reason(exc) == "artifact_integrity_failed"


def test_load_for_release_foreign_identity(store, source) -> None:
    store.quarantine("evt-1", str(source))
    # Plant the authentic artifact of evt-1 under the name evt-2 resolves to.
    src = store.artifact_path("evt-1", str(source))
    dst = store.artifact_path("evt-2", str(source))
    dst.write_bytes(src.read_bytes())
    with pytest.raises(QuarantineError) as exc:
        store.load_for_release("evt-2", str(source), _SHA)
    assert _reason(exc) == "artifact_identity_mismatch"


def test_load_for_release_hash_mismatch(store, source) -> None:
    store.quarantine("evt-1", str(source))
    with pytest.raises(QuarantineError) as exc:
        store.load_for_release("evt-1", str(source), "0" * 64)
    assert _reason(exc) == "artifact_hash_mismatch"


def test_legacy_artifact_named_by_command_id_is_not_found(store, source) -> None:
    store.quarantine("cmd-legacy", str(source))
    with pytest.raises(QuarantineError) as exc:
        store.load_for_release("agent-event-uuid", str(source), _SHA)
    assert _reason(exc) == "artifact_not_found"


def test_remove_artifact_deletes_only_the_authenticated_artifact(store, source, tmp_path) -> None:
    second = source.parent / "other.conf"
    second.write_bytes(_CONTENT)
    store.quarantine("evt-1", str(source))
    store.quarantine("evt-2", str(second))
    store.remove_artifact("evt-1", str(source), _SHA)
    assert not store.artifact_path("evt-1", str(source)).exists()
    assert store.artifact_path("evt-2", str(second)).exists()


def test_remove_artifact_refuses_a_file_that_does_not_authenticate(store, source) -> None:
    store.quarantine("evt-1", str(source))
    artifact_path = store.artifact_path("evt-1", str(source))
    os.chmod(artifact_path, 0o600)
    raw = bytearray(artifact_path.read_bytes())
    raw[40] ^= 0xFF
    artifact_path.write_bytes(bytes(raw))
    with pytest.raises(QuarantineError) as exc:
        store.remove_artifact("evt-1", str(source), _SHA)
    assert _reason(exc) == "artifact_integrity_failed"
    assert artifact_path.exists()


def test_remove_artifact_hash_mismatch_keeps_the_file(store, source) -> None:
    store.quarantine("evt-1", str(source))
    artifact_path = store.artifact_path("evt-1", str(source))
    with pytest.raises(QuarantineError) as exc:
        store.remove_artifact("evt-1", str(source), "f" * 64)
    assert _reason(exc) == "artifact_hash_mismatch"
    assert artifact_path.exists()


def test_remove_artifact_missing(store, source) -> None:
    with pytest.raises(QuarantineError) as exc:
        store.remove_artifact("evt-1", str(source), _SHA)
    assert _reason(exc) == "artifact_not_found"

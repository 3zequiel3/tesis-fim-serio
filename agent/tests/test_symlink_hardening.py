"""
Tests de hardening del filtro de scope + symlink-as-object (C39, D33/RN-127).

Cierra el hallazgo MEDIUM-2 de la revisión dual-judge de C37 (2026-07-02): un
symlink de escape creado dentro de un watch_path (p. ej. `/etc/evil ->
/root/.ssh/authorized_keys`) resolvía fuera de scope por `realpath` completo y
su creación se descartaba silenciosamente. D33/RN-127 separa "¿el link está en
scope?" (ubicación, `_path_location_in_scope`) de "¿el destino resuelto está en
scope?" (contenido, `_target_in_scope`, ex `_realpath_in_scope`).

Cubre la matriz de edge cases del diseño (engram obs #238 §3, tasks.md 5.1-5.6):
- Containment por ubicación: create/delete de symlink de escape, dir intermedio
  simbólico (in/out de scope), watch_path que es él mismo un symlink.
- No-regresión C35: file_deleted de un archivo regular en scope sigue publicándose.
- Symlink-as-object: nunca se abre/hashea/cifra el contenido del destino;
  hash_detected == sha256(readlink); diff siempre None; re-pointing → file_modified.
- Baseline symlink-aware: write_symlink_entry no lee contenido; from_dict parsea
  entries viejas sin symlink_target; delete de symlink registrado no es espurio.
- auto_restore sobre un symlink degrada limpiamente (sin contenido restaurable).
- hardlink_suspected: contador detective opcional, sin cambio de comportamiento.

El backend fanotify interno no está disponible en este entorno: `_classify_event` se parchea
para simular las máscaras FAN_CREATE/FAN_DELETE (mismo patrón que
test_detector_multi_event.py); la rama "sin clasificar" (FAN_CLOSE_WRITE /
mask=0) se ejercita sin parchear, ya que `_HAS_FAN=False` hace que
`_classify_event` retorne "file_modified" por defecto.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.baseline import (
    BaselineEngine,
    BaselineEntry,
    select_restorable_content,
)
from agent.config import AgentConfig, StorageConfig
from agent.decision import DecisionEngine
from agent import detector as detector_module
from agent.detector import FanotifyDetector, FanotifyEvent, _path_location_in_scope
from agent.journal import JournalManager
from agent.rules import RulesCache


def _make_detector(
    tmp_path: Path, baseline: MagicMock | None = None
) -> tuple[FanotifyDetector, MagicMock, MagicMock]:
    baseline = baseline if baseline is not None else MagicMock()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0
    detector = FanotifyDetector(
        agent_id="agent-symlink-test",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=asyncio.Event(),
    )
    return detector, baseline, publisher


# ── 5.1 Matriz de edge cases — containment por ubicación ─────────────────────

def test_location_scope_escape_symlink_is_in_scope_by_location(tmp_path: Path) -> None:
    """El link en sí está en scope por UBICACIÓN aunque su destino resuelto no lo esté."""
    watch = tmp_path / "watched"
    watch.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    target = outside / "id_rsa"
    target.write_text("secret")
    link = watch / "evil"
    link.symlink_to(target)

    assert _path_location_in_scope(str(link), [os.path.realpath(str(watch))]) is True


def test_location_scope_intermediate_symlink_dir_pointing_in_scope(tmp_path: Path) -> None:
    """Dir intermedio simbólico que apunta DENTRO de scope: el path final resuelve in-scope."""
    watch = tmp_path / "watched"
    watch.mkdir()
    real_sub = watch / "real_sub"
    real_sub.mkdir()
    linkdir = watch / "linkdir"
    linkdir.symlink_to(real_sub)

    candidate = str(linkdir / "file.txt")
    assert _path_location_in_scope(candidate, [os.path.realpath(str(watch))]) is True


def test_location_scope_intermediate_symlink_dir_pointing_out_of_scope(tmp_path: Path) -> None:
    """
    Dir intermedio simbólico que apunta FUERA de scope: el archivo detrás del link
    resuelve fuera (correcto: sus bytes viven afuera), pero el linkdir en sí,
    como entrada directa del watch_path, está en scope por ubicación.
    """
    watch = tmp_path / "watched"
    watch.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    linkdir = watch / "linkdir"
    linkdir.symlink_to(outside)

    # El linkdir mismo (entrada directa de watch) está en scope por ubicación.
    assert _path_location_in_scope(str(linkdir), [os.path.realpath(str(watch))]) is True
    # Un archivo alcanzado A TRAVÉS del linkdir resuelve fuera de scope por destino.
    from agent.detector import _target_in_scope
    assert _target_in_scope(str(linkdir / "secret.txt"), [os.path.realpath(str(watch))]) is False


def test_location_scope_watch_path_symlink_boundary_preserved(tmp_path: Path) -> None:
    """D31: un watch_path que es él mismo un symlink sigue definiendo su boundary por realpath."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_watch = tmp_path / "link_watch"
    link_watch.symlink_to(real_dir)

    canonical = [os.path.realpath(str(link_watch))]
    assert _path_location_in_scope(str(real_dir / "f.txt"), canonical) is True


def test_location_scope_delete_of_regular_file_parent_still_resolves(tmp_path: Path) -> None:
    """El parent existe en un delete (el componente final ya no); la ubicación resuelve igual."""
    watch = tmp_path / "watched"
    watch.mkdir()
    deleted_path = str(watch / "gone.txt")  # nunca se crea: simula post-delete

    assert _path_location_in_scope(deleted_path, [os.path.realpath(str(watch))]) is True


# ── 5.2 No-regresión C35 — borrado legítimo de archivo regular ──────────────

@pytest.mark.asyncio
async def test_regular_file_delete_in_scope_still_publishes(tmp_path: Path) -> None:
    """La trampa de C35: un file_deleted de un archivo regular en scope DEBE publicarse."""
    watch = tmp_path / "watched"
    watch.mkdir()
    deleted_path = str(watch / "gone.txt")

    entry_mock = MagicMock()
    entry_mock.hash = "deadbeef"
    entry_mock.symlink_target = None
    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=deleted_path, pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    with patch.object(detector, "_classify_event", return_value="file_deleted"):
        await detector._process_event(fan_event)

    publisher.publish.assert_awaited_once()
    published = publisher.publish.call_args[0][0]
    assert published["event_type"] == "file_deleted"
    assert published["is_symlink"] is False
    assert published["symlink_target"] is None
    baseline.mark_absent.assert_called_once_with(deleted_path)


# ── 5.3 Symlink-as-object en _process_event ──────────────────────────────────

@pytest.mark.asyncio
async def test_symlink_create_reports_file_created_with_target_string_hash(tmp_path: Path) -> None:
    watch = tmp_path / "watched"
    watch.mkdir()
    outside_target = tmp_path / "secret" / "id_rsa"
    outside_target.parent.mkdir()
    outside_target.write_text("secret")
    link = watch / "evil"
    link.symlink_to(outside_target)

    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(link), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    with patch.object(detector, "_classify_event", return_value="file_created"):
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    expected_hash = hashlib.sha256(str(outside_target).encode()).hexdigest()
    assert published["event_type"] == "file_created"
    assert published["is_symlink"] is True
    assert published["symlink_target"] == str(outside_target)
    assert published["hash_detected"] == expected_hash
    assert published["diff_text"] is None
    baseline.write_symlink_entry.assert_called_once_with(str(link))
    baseline.write_entry.assert_not_called()


@pytest.mark.asyncio
async def test_symlink_create_never_calls_hash_file_async(tmp_path: Path) -> None:
    """
    Prueba directa de Philosophy B: `_hash_file_async` (que abre y lee bytes)
    NUNCA se invoca para un symlink, sea el destino in-scope o out-of-scope.
    """
    watch = tmp_path / "watched"
    watch.mkdir()
    outside_target = tmp_path / "secret" / "id_rsa"
    outside_target.parent.mkdir()
    outside_target.write_text("secret")
    link = watch / "evil"
    link.symlink_to(outside_target)

    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(link), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    boom = AsyncMock(side_effect=AssertionError("must never hash target content"))
    with patch("agent.detector._hash_file_async", new=boom), \
         patch.object(detector, "_classify_event", return_value="file_created"):
        await detector._process_event(fan_event)

    boom.assert_not_called()
    published = publisher.publish.call_args[0][0]
    assert published["hash_detected"] == hashlib.sha256(str(outside_target).encode()).hexdigest()


@pytest.mark.asyncio
async def test_symlink_delete_uses_baseline_metadata_not_spurious(tmp_path: Path) -> None:
    """
    LOW-1 resuelto como efecto colateral: como el symlink quedó en baseline al
    crearse, el delete lee is_symlink/symlink_target del baseline (el path ya
    no existe — no se puede volver a hacer lstat/readlink) y es una baja real,
    no espuria.
    """
    watch = tmp_path / "watched"
    watch.mkdir()
    link_path = str(watch / "evil")  # nunca existe en disco: simula post-delete

    entry_mock = MagicMock()
    entry_mock.hash = hashlib.sha256(b"/root/.ssh/authorized_keys").hexdigest()
    entry_mock.symlink_target = "/root/.ssh/authorized_keys"
    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=link_path, pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    with patch.object(detector, "_classify_event", return_value="file_deleted"):
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["event_type"] == "file_deleted"
    assert published["is_symlink"] is True
    assert published["symlink_target"] == "/root/.ssh/authorized_keys"
    assert published["hash_detected"] == ""  # D-C13-04: hash ausente = "", nunca None
    baseline.mark_absent.assert_called_once_with(link_path)


@pytest.mark.asyncio
async def test_symlink_repoint_reports_file_modified(tmp_path: Path) -> None:
    """Re-pointing de un symlink existente: cambia el string de readlink → cambia
    el hash → se detecta como file_modified (mismo mecanismo de dedup por hash
    que un archivo regular)."""
    watch = tmp_path / "watched"
    watch.mkdir()
    target_a = tmp_path / "target_a"
    target_a.write_text("a")
    link = watch / "mylink"
    link.symlink_to(target_a)

    entry_mock = MagicMock()
    entry_mock.hash = hashlib.sha256(str(target_a).encode()).hexdigest()
    entry_mock.symlink_target = str(target_a)
    entry_mock.content_b64 = None
    entry_mock.oversize = False
    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = entry_mock

    target_b = tmp_path / "target_b"
    target_b.write_text("b")
    link.unlink()
    link.symlink_to(target_b)

    fan_event = FanotifyEvent(
        path=str(link), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    # mask=0 por defecto; _HAS_FAN=False -> _classify_event retorna "file_modified",
    # que cae en la rama genérica (no matchea "file_deleted" ni "file_created").
    await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["event_type"] == "file_modified"
    assert published["is_symlink"] is True
    assert published["symlink_target"] == str(target_b)
    assert published["hash_detected"] == hashlib.sha256(str(target_b).encode()).hexdigest()
    assert published["diff_text"] is None
    baseline.add_snapshot.assert_called_once_with(str(link))


@pytest.mark.asyncio
async def test_symlink_unchanged_target_is_deduped(tmp_path: Path) -> None:
    """Si el destino no cambió, se descarta igual que un archivo regular sin cambios."""
    watch = tmp_path / "watched"
    watch.mkdir()
    target = tmp_path / "target"
    target.write_text("x")
    link = watch / "mylink"
    link.symlink_to(target)

    entry_mock = MagicMock()
    entry_mock.hash = hashlib.sha256(str(target).encode()).hexdigest()
    entry_mock.symlink_target = str(target)
    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(link), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    publisher.publish.assert_not_called()


# ── 5.4 Baseline symlink-aware ────────────────────────────────────────────────

@pytest.fixture()
def master_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def secrets_dir(tmp_path: Path, master_secret: bytes) -> Path:
    sd = tmp_path / "secrets"
    sd.mkdir(mode=0o700)
    ms_path = sd / "master_secret"
    fd = os.open(str(ms_path), os.O_CREAT | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(master_secret)
    return sd


@pytest.fixture()
def storage(tmp_path: Path, secrets_dir: Path) -> StorageConfig:
    return StorageConfig(
        baseline_dir=str(tmp_path / "baseline"),
        queue_dir=str(tmp_path / "queue"),
        journal_dir=str(tmp_path / "journal"),
        secrets_dir=str(secrets_dir),
        certs_dir=str(tmp_path / "certs"),
    )


@pytest.fixture()
def config(storage: StorageConfig) -> AgentConfig:
    return AgentConfig(
        agent_id="test-agent-symlink",
        backend_url="http://localhost:8000",
        valkey_url="redis://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/tmp"],
        storage=storage,
    )


@pytest.fixture()
def engine(config: AgentConfig, master_secret: bytes) -> BaselineEngine:
    return BaselineEngine(config, master_secret)


def test_write_symlink_entry_never_reads_target_content(engine: BaselineEngine, tmp_path: Path) -> None:
    outside_target = tmp_path / "outside.txt"
    outside_target.write_text("target content that must never be read")
    link = tmp_path / "mylink"
    link.symlink_to(outside_target)

    entry = engine.write_symlink_entry(str(link))

    assert entry.content_b64 is None
    assert entry.symlink_target == str(outside_target)
    assert entry.hash == hashlib.sha256(str(outside_target).encode()).hexdigest()

    read_back = engine.read_entry(str(link))
    assert read_back is not None
    assert read_back.content_b64 is None
    assert read_back.symlink_target == str(outside_target)


def test_from_dict_parses_pre_existing_entry_without_symlink_target() -> None:
    """Retrocompatibilidad: entries serializadas antes de D33/RN-127 no tienen
    la key `symlink_target` — from_dict debe parsear igual, con default None."""
    old_dict = {
        "path": "/etc/passwd",
        "status": "present",
        "hash": "abc123",
        "size": 10,
        "mode": "0o644",
        "uid": 0,
        "gid": 0,
        "mtime": "2026-01-01T00:00:00+00:00",
        "captured_at": "2026-01-01T00:00:00+00:00",
        "snapshots": [],
        "content_b64": "aGVsbG8=",
        "oversize": False,
        # sin "symlink_target"
    }
    entry = BaselineEntry.from_dict(old_dict)
    assert entry.symlink_target is None
    assert entry.path == "/etc/passwd"


def test_init_scan_baselines_escape_symlink_as_object(engine: BaselineEngine, tmp_path: Path) -> None:
    """
    D33/RN-127 invierte el comportamiento de C37/D31: un symlink de escape ya NO
    se omite del baseline — se registra como objeto propio (metadata del link),
    sin leer/cifrar el contenido del destino. El archivo regular in-scope sigue
    baseline-ándose normalmente.
    """
    watch = tmp_path / "watched_scope"
    watch.mkdir()
    outside_dir = tmp_path / "root_ssh"
    outside_dir.mkdir()
    secret_file = outside_dir / "id_rsa"
    secret_file.write_bytes(b"super secret key material")

    escape_link = watch / "escape_link"
    escape_link.symlink_to(secret_file)
    (watch / "regular.txt").write_bytes(b"in scope content")

    report = engine.init_scan([str(watch)])

    assert report.scanned == 2  # regular.txt + escape_link (symlink-as-object)
    assert report.skipped == 0
    assert report.errors == 0

    link_entry = engine.read_entry(str(escape_link))
    assert link_entry is not None
    assert link_entry.symlink_target == str(secret_file)
    assert link_entry.content_b64 is None
    assert link_entry.hash == hashlib.sha256(str(secret_file).encode()).hexdigest()

    regular_entry = engine.read_entry(str(watch / "regular.txt"))
    assert regular_entry is not None
    assert regular_entry.status == "present"


def test_run_scan_baselines_escape_symlink_as_object(engine: BaselineEngine, tmp_path: Path) -> None:
    """run_scan aplica el mismo criterio de clasificación que init_scan."""
    watch = tmp_path / "watched_scope_rescan"
    watch.mkdir()
    outside_dir = tmp_path / "root_ssh_rescan"
    outside_dir.mkdir()
    secret_file = outside_dir / "id_rsa"
    secret_file.write_bytes(b"super secret key material")

    escape_link = watch / "escape_link"
    escape_link.symlink_to(secret_file)
    (watch / "regular.txt").write_bytes(b"in scope content")

    report = engine.run_scan([str(watch)])

    assert report.scanned == 2
    assert report.skipped == 0

    link_entry = engine.read_entry(str(escape_link))
    assert link_entry is not None
    assert link_entry.symlink_target == str(secret_file)
    assert link_entry.content_b64 is None


def test_scan_regular_file_behind_out_of_scope_symlinked_dir_is_not_baselined(
    engine: BaselineEngine, tmp_path: Path
) -> None:
    """
    Un archivo regular alcanzado vía un directorio intermedio simbólico que
    apunta fuera de scope NO se baseline-a (sus bytes viven afuera) — pero el
    symlink de directorio en sí SÍ se registra como objeto (Path.rglob de
    Python 3.13 no recursa dentro de dirs simbólicos por defecto, así que el
    archivo detrás del link ni siquiera se enumera; el link-dir en sí queda
    como una entrada más de `watch`, clasificada is_symlink() antes de is_file()).
    """
    watch = tmp_path / "watched_intermediate"
    watch.mkdir()
    outside_dir = tmp_path / "outside_intermediate"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_bytes(b"lives outside scope")

    linkdir = watch / "linkdir"
    linkdir.symlink_to(outside_dir)

    report = engine.init_scan([str(watch)])

    assert report.scanned == 1  # solo linkdir (symlink-as-object)
    assert engine.read_entry(str(linkdir)) is not None
    assert engine.read_entry(str(outside_dir / "secret.txt")) is None


# ── 5.5 auto_restore sobre un symlink degrada limpiamente ────────────────────

def test_select_restorable_content_none_for_symlink_entry() -> None:
    """Un symlink no tiene content_b64 ni snapshots restaurables: select_restorable_content
    debe retornar None, sin lanzar excepción."""
    entry = BaselineEntry(
        path="/watched/evil",
        status="present",
        hash=hashlib.sha256(b"/root/.ssh/authorized_keys").hexdigest(),
        size=None,
        mode=None,
        uid=None,
        gid=None,
        mtime="2026-01-01T00:00:00+00:00",
        captured_at="2026-01-01T00:00:00+00:00",
        snapshots=[],
        content_b64=None,
        symlink_target="/root/.ssh/authorized_keys",
    )
    assert select_restorable_content(entry) is None


def test_auto_restore_on_symlink_degrades_cleanly_no_crash(tmp_path: Path) -> None:
    """
    auto_restore sobre un symlink no debe crashear: select_restorable_content
    retorna None (sin contenido restaurable) → DecisionEngine marca
    action_failed=True, sin intentar restaurar bytes.
    """
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "auto_restore"
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")

    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.symlink_target = "/root/.ssh/authorized_keys"
    entry_mock.snapshots = []
    baseline = MagicMock()
    baseline.read_entry.return_value = entry_mock

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )

    link_path = str(tmp_path / "watched" / "evil")
    change = MagicMock()
    change.event_id = "test-symlink-restore-001"
    change.path = link_path
    change.event_type = "file_deleted"
    change.to_event_data.return_value = {
        "event_id": change.event_id,
        "path": link_path,
        "event_type": "file_deleted",
        "hash_expected": entry_mock.hash if hasattr(entry_mock, "hash") else None,
        "hash_detected": None,
        "diff_text": None,
        "process_pid": 0,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
        "is_symlink": True,
        "symlink_target": "/root/.ssh/authorized_keys",
    }

    payload, commit_fn = engine.evaluate_and_act(change)  # no debe lanzar

    assert payload["action_failed"] is True
    assert payload["event_type"] != "auto_restored"


# ── 5.6 hardlink_suspected — contador detective opcional ─────────────────────

@pytest.mark.asyncio
async def test_hardlink_suspected_increments_on_regular_file_create_with_nlink_ge_2(
    tmp_path: Path,
) -> None:
    watch = tmp_path / "watched"
    watch.mkdir()
    original = watch / "original.txt"
    original.write_text("shared content")
    hardlink = watch / "hardlink.txt"
    os.link(original, hardlink)  # st_nlink pasa a 2 para ambos nombres

    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(hardlink), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    with patch.object(detector, "_classify_event", return_value="file_created"):
        await detector._process_event(fan_event)

    assert detector.hardlink_suspected == 1
    # Sin cambio de comportamiento: se procesa exactamente como un create normal.
    published = publisher.publish.call_args[0][0]
    assert published["event_type"] == "file_created"
    assert published["is_symlink"] is False
    baseline.write_entry.assert_called_once_with(str(hardlink))


@pytest.mark.asyncio
async def test_hardlink_suspected_not_incremented_for_single_link_file(tmp_path: Path) -> None:
    watch = tmp_path / "watched"
    watch.mkdir()
    solo = watch / "solo.txt"
    solo.write_text("no hardlinks here")

    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(solo), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    with patch.object(detector, "_classify_event", return_value="file_created"):
        await detector._process_event(fan_event)

    assert detector.hardlink_suspected == 0


@pytest.mark.asyncio
async def test_hardlink_suspected_not_incremented_for_symlink_create(tmp_path: Path) -> None:
    """El contador es SOLO para archivos regulares (D33/RN-127); un symlink no lo toca."""
    watch = tmp_path / "watched"
    watch.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = watch / "mylink"
    link.symlink_to(target)

    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(link), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    with patch.object(detector, "_classify_event", return_value="file_created"):
        await detector._process_event(fan_event)

    assert detector.hardlink_suspected == 0


@pytest.mark.asyncio
async def test_heartbeat_payload_includes_hardlink_suspected() -> None:
    import json

    from agent.heartbeat import HeartbeatPublisher

    detector = MagicMock()
    detector.event_drops = 0
    detector.out_of_scope_drops = 0
    detector.hardlink_suspected = 5

    queue = MagicMock()
    queue.queue_size = 0
    queue.queue_pressure = 0.0
    state = MagicMock()
    state.ruleset_version = 1
    client = MagicMock()
    client.xadd = AsyncMock(return_value="1-0")

    cfg = MagicMock()
    cfg.agent_id = "agent-hb-hardlink-test"

    hb = HeartbeatPublisher(config=cfg, queue=queue, state=state, client=client, detector=detector)
    await hb._publish(False)

    data = json.loads(client.xadd.call_args[0][1]["data"])
    assert data["hardlink_suspected"] == 5


# ── MEDIUM-1 (dual-review C39) — diff jamás sigue un symlink ──────────────────

@pytest.mark.asyncio
async def test_file_modified_never_diffs_symlink_even_with_stale_regular_entry(
    tmp_path: Path,
) -> None:
    """
    MEDIUM-1 (defensa-en-profundidad, dual-review C39): la garantía "el contenido
    del destino NUNCA se lee/hashea/cifra" debe estar FORZADA por código, no
    delegada al invariante frágil "un symlink nunca tiene content_b64".

    Escenario: una entry REGULAR obsoleta (content_b64 seteado, symlink_target
    None) queda en baseline para un path `/scope/foo` que entretanto se volvió un
    symlink `/scope/foo -> <secreto out-of-scope>`. Sin el guard `not is_symlink`
    en la rama file_modified, `_generate_diff(previous_content, path)` abriría el
    path, seguiría el link y publicaría hasta 1 MB del contenido del destino en
    `diff_text`. El guard lo impide de raíz: diff_text es None y `_generate_diff`
    ni siquiera se invoca sobre el path del symlink.
    """
    watch = tmp_path / "watched"
    watch.mkdir()
    secret_dir = tmp_path / "root_ssh"
    secret_dir.mkdir()
    secret_file = secret_dir / "id_rsa"
    secret_marker = "TOP-SECRET-PRIVATE-KEY-MATERIAL"
    secret_file.write_text(
        f"-----BEGIN PRIVATE KEY-----\n{secret_marker}\n-----END PRIVATE KEY-----\n"
    )

    # El path era un archivo regular; ahora es un symlink al secreto out-of-scope.
    link = watch / "foo"
    link.symlink_to(secret_file)

    # Entry REGULAR obsoleta: content_b64 seteado (contenido viejo del archivo),
    # symlink_target None (nació como regular), hash viejo != sha256(readlink).
    entry_mock = MagicMock()
    entry_mock.hash = "stale-regular-hash-that-differs-from-readlink"
    entry_mock.symlink_target = None
    entry_mock.content_b64 = base64.b64encode(b"old regular content\n").decode()
    entry_mock.oversize = False

    detector, baseline, publisher = _make_detector(tmp_path)
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(link), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )

    # Spy que envuelve la implementación real: si el guard funciona, NUNCA se llama.
    spy = MagicMock(wraps=detector_module._generate_diff)
    with patch("agent.detector._generate_diff", new=spy):
        # mask=0; _HAS_FAN=False -> _classify_event retorna "file_modified" (rama
        # genérica, misma que ejercita test_symlink_repoint_reports_file_modified).
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    # El path se trata como symlink-as-object: hash = sha256(readlink), no del contenido.
    assert published["event_type"] == "file_modified"
    assert published["is_symlink"] is True
    assert published["hash_detected"] == hashlib.sha256(str(secret_file).encode()).hexdigest()
    # Garantía absoluta C39: sin diff y sin abrir el destino.
    assert published["diff_text"] is None
    spy.assert_not_called()
    assert secret_marker not in (published.get("diff_text") or "")

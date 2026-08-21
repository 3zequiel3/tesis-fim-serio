"""
Tests del cierre del loop de retroalimentación de `auto_restore` (Change 43,
agent-restore-feedback-loop).

Reproducido en vivo: una sola modificación bajo una regla `auto_restore`
produjo 497 eventos sobre ese path en 4,7 minutos y dejó 3240 eventos
encolados. La raíz: `os.replace` entrega `FAN_MOVED_TO` sobre el path FINAL
tras una restauración, el filtro de sufijo de `.fim_restore_tmp` no lo cubre,
y la rama `file_created` de `_process_event` (a diferencia de la rama
`file_modified`) nunca comparaba el hash resultante contra el baseline antes
de publicar.

Prohibido en este archivo: `MagicMock` para `BaselineEngine`, para el
filesystem o para `DecisionEngine` (task 2.1). Lo único simulado es el
publisher (colector de payloads, un cliente de red) y el arribo de eventos
fanotify, que se inyecta llamando `_process_event` directamente — el mismo
punto de entrada que ya usa el resto de la suite del detector, porque
`fanotify` real requiere `CAP_SYS_ADMIN` y no está disponible en CI.

Un test que solo cuenta eventos también pasa cuando la restauración FALLA en
silencio — que es el estado en que vivió el sistema entre D19 y la change 41.
Por eso cada test de supresión afirma primero que la restauración ocurrió de
verdad (contenido en disco, journal en `completed`, metadata) y solo después
afirma que no se publicó nada (D-7 del design).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agent._fanotify import (
    FAN_CLOSE_WRITE,
    FAN_CREATE,
    FAN_MOVED_FROM,
    FAN_MOVED_TO,
)
from agent.baseline import (
    BaselineEngine,
    BaselineEntry,
    _atomic_write,
    _entry_path,
    select_restorable_content,
)
from agent.config import AgentConfig, StorageConfig
from agent.decision import DecisionEngine, parse_baseline_mode
from agent.detector import FanotifyDetector, FanotifyEvent
from agent.journal import JournalManager
from agent.rules import RulesCache


# ── Publisher de prueba: lo único que se simula (D-7 del design) ─────────────


class _CollectingPublisher:
    """Colector de payloads. No es un hecho del filesystem — es el cliente de
    red — así que simularlo no oculta nada del defecto (D-7)."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def publish(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class _ObservingJournal(JournalManager):
    """JournalManager real e íntegro (misma escritura atómica + HMAC que en
    producción). Además registra los event_id que pasaron por `mark_completed`,
    porque `evaluate_and_act` borra la entrada del journal inmediatamente
    después de completarla (D-6 del design) y el test necesita observar el
    estado `completed` antes de que desaparezca."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.completed_event_ids: list[str] = []

    def mark_completed(self, event_id: str) -> None:
        self.completed_event_ids.append(event_id)
        super().mark_completed(event_id)


# ── El rig: todo real salvo el publisher (D-7 del design) ────────────────────


@dataclasses.dataclass
class RestoreRig:
    tmp_path: Path
    watch_dir: Path
    config: AgentConfig
    baseline: BaselineEngine
    rules: RulesCache
    journal: _ObservingJournal
    engine: DecisionEngine
    detector: FanotifyDetector
    publisher: _CollectingPublisher
    target: Path
    known_content: bytes
    known_entry: BaselineEntry


def _build_rig(tmp_path: Path, *, with_auto_restore_rule: bool = True) -> RestoreRig:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    master_secret = os.urandom(32)
    ms_path = secrets_dir / "master_secret"
    fd = os.open(str(ms_path), os.O_CREAT | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(master_secret)

    storage = StorageConfig(
        baseline_dir=str(tmp_path / "baseline"),
        queue_dir=str(tmp_path / "queue"),
        journal_dir=str(tmp_path / "journal"),
        secrets_dir=str(secrets_dir),
        certs_dir=str(tmp_path / "certs"),
    )
    config = AgentConfig(
        agent_id="restore-rig-agent",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=[str(watch_dir)],
        storage=storage,
    )

    baseline = BaselineEngine(config, master_secret)

    rules_payload = (
        [{"pattern": f"{watch_dir}/**", "action": "auto_restore", "negated": False}]
        if with_auto_restore_rule
        else []
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ruleset_version": 1, "rules": rules_payload}))
    rules = RulesCache(state_path)

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    journal = _ObservingJournal(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")

    quarantine_dir = tmp_path / "quarantine"
    engine = DecisionEngine(rules=rules, journal=journal, baseline=baseline, quarantine_dir=quarantine_dir)

    publisher = _CollectingPublisher()
    detector = FanotifyDetector(
        agent_id=config.agent_id,
        watch_paths=[str(watch_dir)],
        baseline=baseline,
        publisher=publisher,
        stop_event=asyncio.Event(),
        decision_engine=engine,
    )

    target = watch_dir / "target.conf"
    known_content = b"known-good baseline content\n"
    target.write_bytes(known_content)
    known_entry = baseline.write_entry(str(target))

    # task 2.3: si el rig no puede restaurar, todos los tests que siguen pasan
    # en verde sin probar nada — es exactamente el modo de fallo que ocultó el
    # defecto (razón 2 del proposal).
    result = select_restorable_content(known_entry)
    assert result is not None, "rig fixture cannot restore — tests below would be meaningless"
    restorable_content, expected_hash = result
    assert restorable_content == known_content
    assert expected_hash, "expected_hash must not be empty for the rig's seed entry"

    return RestoreRig(
        tmp_path=tmp_path,
        watch_dir=watch_dir,
        config=config,
        baseline=baseline,
        rules=rules,
        journal=journal,
        engine=engine,
        detector=detector,
        publisher=publisher,
        target=target,
        known_content=known_content,
        known_entry=known_entry,
    )


@pytest.fixture()
def restore_rig(tmp_path: Path) -> RestoreRig:
    return _build_rig(tmp_path, with_auto_restore_rule=True)


@pytest.fixture()
def no_remediation_rig(tmp_path: Path) -> RestoreRig:
    """Sin regla `auto_restore` (default `alert_only`) — para los tests del
    falso positivo general de la sección 4, que no dependen de remediación."""
    return _build_rig(tmp_path, with_auto_restore_rule=False)


def _write_raw_entry(baseline: BaselineEngine, entry: BaselineEntry) -> None:
    """Escribe una entry construida a mano usando el cifrado real del motor
    (mismo AES-GCM, misma escritura atómica) — no es un mock del baseline,
    es la manera de sembrar el caso 'hash presente, sin contenido
    restaurable' (entry oversize / degradada) sin escribir un archivo de más
    de 10 MiB en cada corrida de test."""
    blob = baseline._encrypt_entry(entry)
    _atomic_write(_entry_path(baseline._baseline_dir, entry.path), blob)


async def _inject(rig: RestoreRig, path: Path, mask: int, *, pid: int = 4242) -> None:
    await rig.detector._process_event(
        FanotifyEvent(
            path=str(path),
            pid=pid,
            uid=0,
            exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
            mask=mask,
        )
    )


def _mode_uid_gid(path: Path) -> tuple[int, int, int]:
    st = path.stat()
    return stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid


# ══════════════════════════════════════════════════════════════════════════
# 2. Test de integración detector <-> motor sobre filesystem real
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_restore_moved_to_publishes_nothing(restore_rig: RestoreRig) -> None:
    rig = restore_rig

    # Adulterar el archivo en disco.
    rig.target.write_bytes(b"TAMPERED CONTENT")

    # FAN_CLOSE_WRITE: detecta la adulteración, auto_restore la revierte.
    await _inject(rig, rig.target, FAN_CLOSE_WRITE)

    tamper_event_id = rig.detector._pending[str(rig.target)]

    # ── La restauración debe haber ocurrido de verdad, ANTES de mirar eventos ──
    assert rig.target.read_bytes() == rig.known_content
    assert tamper_event_id in rig.journal.completed_event_ids
    mode, uid, gid = _mode_uid_gid(rig.target)
    assert mode == parse_baseline_mode(rig.known_entry.mode)
    assert uid == rig.known_entry.uid
    assert gid == rig.known_entry.gid

    payloads_before_moved_to = len(rig.publisher.payloads)
    assert payloads_before_moved_to == 1

    # FAN_MOVED_TO: el os.replace de _auto_restore sobre el path final.
    await _inject(rig, rig.target, FAN_MOVED_TO)

    assert len(rig.publisher.payloads) == payloads_before_moved_to


@pytest.mark.asyncio
async def test_baseline_entry_survives_the_round_trip(restore_rig: RestoreRig) -> None:
    """RN-33 como aserción ejecutable: el baseline no se reescribe."""
    rig = restore_rig

    rig.target.write_bytes(b"TAMPERED CONTENT")
    await _inject(rig, rig.target, FAN_CLOSE_WRITE)
    await _inject(rig, rig.target, FAN_MOVED_TO)

    reread = rig.baseline.read_entry(str(rig.target))
    assert reread is not None
    assert reread.hash == rig.known_entry.hash
    assert reread.content_b64 == rig.known_entry.content_b64
    assert reread.mode == rig.known_entry.mode
    assert reread.uid == rig.known_entry.uid
    assert reread.gid == rig.known_entry.gid


@pytest.mark.asyncio
async def test_tamper_event_remains_the_pending_one(restore_rig: RestoreRig) -> None:
    rig = restore_rig

    rig.target.write_bytes(b"TAMPERED CONTENT")
    await _inject(rig, rig.target, FAN_CLOSE_WRITE)
    tamper_event_id = rig.detector._pending[str(rig.target)]

    await _inject(rig, rig.target, FAN_MOVED_TO)

    # El MOVED_TO descartado no debe haber tocado _pending / _event_to_path.
    assert rig.detector._pending[str(rig.target)] == tamper_event_id
    assert rig.detector._event_to_path[tamper_event_id] == str(rig.target)

    assert len(rig.publisher.payloads) == 1
    payload = rig.publisher.payloads[0]
    assert payload["event_id"] == tamper_event_id
    assert payload["action"] == "auto_restore"
    assert payload.get("action_failed", False) is False


# ══════════════════════════════════════════════════════════════════════════
# 3. Test de cota de eventos (regresión del loop)
# ══════════════════════════════════════════════════════════════════════════


async def _run_event_bomb(rig: RestoreRig, target: Path, n: int, ceiling: int) -> None:
    """Adultera `target` n veces. Tras cada evento procesado, si el motor
    efectivamente restauró, reinyecta el FAN_MOVED_TO que entregaría el
    kernel (D-7 del design). Techo duro: si se alcanza, el test FALLA con un
    mensaje explícito en vez de colgarse (task 3.2)."""
    iterations = 0

    async def _step(path: Path, mask: int) -> None:
        nonlocal iterations
        iterations += 1
        if iterations > ceiling:
            pytest.fail(
                f"event bomb exceeded the hard ceiling of {ceiling} iterations "
                "— the restore feedback loop is back"
            )
        await _inject(rig, path, mask)

    for i in range(n):
        target.write_bytes(f"tamper-{i}".encode())
        await _step(target, FAN_CLOSE_WRITE)

        last = rig.publisher.payloads[-1]
        while last.get("action") == "auto_restore" and not last.get("action_failed"):
            count_before = len(rig.publisher.payloads)
            await _step(target, FAN_MOVED_TO)
            if len(rig.publisher.payloads) == count_before:
                break  # el guard suprimió el MOVED_TO: el ciclo convergió
            last = rig.publisher.payloads[-1]


@pytest.mark.asyncio
async def test_n_tampers_produce_at_most_n_events(restore_rig: RestoreRig) -> None:
    rig = restore_rig
    n = 5

    await _run_event_bomb(rig, rig.target, n=n, ceiling=n * 4)

    # Piso y techo juntos (task 3.3): ni menos (el guard no debe suprimir de
    # más) ni más (el guard debe converger en una vuelta por adulteración).
    assert len(rig.publisher.payloads) == n
    assert rig.target.read_bytes() == rig.known_content


@pytest.mark.asyncio
async def test_failed_restore_emits_once_and_does_not_loop(restore_rig: RestoreRig) -> None:
    rig = restore_rig

    # Entry con hash presente pero sin contenido restaurable ni snapshots
    # (caso "oversize" degradado descrito en Risks del design).
    degraded = dataclasses.replace(rig.known_entry, content_b64=None, snapshots=[])
    _write_raw_entry(rig.baseline, degraded)

    rig.target.write_bytes(b"TAMPERED CONTENT")
    await _inject(rig, rig.target, FAN_CLOSE_WRITE)

    assert len(rig.publisher.payloads) == 1
    payload = rig.publisher.payloads[0]
    assert payload["action_failed"] is True
    assert payload["action_error"] == "no_restorable_content"
    # No hubo escritura: el archivo tampereado sigue en disco tal cual.
    assert rig.target.read_bytes() == b"TAMPERED CONTENT"
    # Sin os.replace no hay MOVED_TO del kernel que reinyectar: no hay loop
    # posible para este caso, y no se ejercita más allá de este punto.


# ══════════════════════════════════════════════════════════════════════════
# 4. Falso positivo general y pruebas negativas del guard
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_third_party_atomic_rename_of_identical_content_is_silent(
    no_remediation_rig: RestoreRig,
) -> None:
    rig = no_remediation_rig
    tmp = rig.target.with_suffix(".other-tmp")
    tmp.write_bytes(rig.known_content)
    os.replace(str(tmp), str(rig.target))

    await _inject(rig, rig.target, FAN_MOVED_TO)

    assert rig.publisher.payloads == []


@pytest.mark.asyncio
async def test_atomic_rename_of_different_content_emits_one_event(
    no_remediation_rig: RestoreRig,
) -> None:
    rig = no_remediation_rig
    tmp = rig.target.with_suffix(".other-tmp")
    tmp.write_bytes(b"different content, not the baseline")
    os.replace(str(tmp), str(rig.target))

    await _inject(rig, rig.target, FAN_MOVED_TO)

    assert len(rig.publisher.payloads) == 1
    assert rig.publisher.payloads[0]["event_type"] == "file_created"


@pytest.mark.asyncio
async def test_fan_create_of_identical_content_is_silent(no_remediation_rig: RestoreRig) -> None:
    rig = no_remediation_rig
    tmp = rig.target.with_suffix(".other-tmp")
    tmp.write_bytes(rig.known_content)
    os.replace(str(tmp), str(rig.target))

    await _inject(rig, rig.target, FAN_CREATE)

    assert rig.publisher.payloads == []


@pytest.mark.asyncio
async def test_fan_create_of_different_content_emits_one_event(no_remediation_rig: RestoreRig) -> None:
    rig = no_remediation_rig
    tmp = rig.target.with_suffix(".other-tmp")
    tmp.write_bytes(b"different content, not the baseline")
    os.replace(str(tmp), str(rig.target))

    await _inject(rig, rig.target, FAN_CREATE)

    assert len(rig.publisher.payloads) == 1
    assert rig.publisher.payloads[0]["event_type"] == "file_created"


@pytest.mark.asyncio
async def test_type_change_is_not_suppressed(no_remediation_rig: RestoreRig) -> None:
    """D-2 del design: identidad de tipo de objeto, no solo igualdad de hash."""
    rig = no_remediation_rig
    link_target_str = "/some/dangling/target/string"
    link_path = rig.watch_dir / "linky"

    os.symlink(link_target_str, str(link_path))
    rig.baseline.write_symlink_entry(str(link_path))

    # El path pasa de symlink a archivo regular cuyo CONTENIDO es
    # literalmente el string del destino original — mismo hash SHA-256,
    # tipo de objeto distinto.
    os.remove(str(link_path))
    link_path.write_bytes(link_target_str.encode())

    await _inject(rig, link_path, FAN_MOVED_TO)

    assert len(rig.publisher.payloads) == 1


@pytest.mark.asyncio
async def test_recreated_after_delete_is_not_suppressed(no_remediation_rig: RestoreRig) -> None:
    rig = no_remediation_rig
    rig.baseline.mark_absent(str(rig.target))
    os.remove(str(rig.target))

    rig.target.write_bytes(rig.known_content)  # recreado con el mismo contenido

    await _inject(rig, rig.target, FAN_CREATE)

    assert len(rig.publisher.payloads) == 1
    assert rig.publisher.payloads[0]["event_type"] == "file_created"


@pytest.mark.asyncio
async def test_suffix_filter_still_applies(no_remediation_rig: RestoreRig) -> None:
    rig = no_remediation_rig
    tmp_marker_path = str(rig.target) + ".fim_restore_tmp"

    with patch.object(rig.baseline, "read_entry", wraps=rig.baseline.read_entry) as spy:
        await _inject(rig, Path(tmp_marker_path), FAN_MOVED_TO)

    assert rig.publisher.payloads == []
    spy.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# 5. Camino del operador (agent/commands.py)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_operator_restore_publishes_ack_and_no_event(restore_rig: RestoreRig) -> None:
    from agent import commands

    rig = restore_rig
    rig.target.write_bytes(b"TAMPERED BY SOMEONE ELSE")

    mock_valkey = AsyncMock()
    mock_valkey.xadd = AsyncMock()

    cmd = {
        "command_id": "cmd-restore-001",
        "event_id": "evt-1",
        "path": str(rig.target),
    }

    await commands.handle_restore_file(
        command=cmd,
        baseline_engine=rig.baseline,
        journal=rig.journal,
        valkey_client=mock_valkey,
        config=rig.config,
    )

    assert rig.target.read_bytes() == rig.known_content
    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "ok"

    await _inject(rig, rig.target, FAN_MOVED_TO)

    assert rig.publisher.payloads == []


@pytest.mark.asyncio
async def test_operator_restore_failure_publishes_only_its_ack(restore_rig: RestoreRig) -> None:
    from agent import commands

    rig = restore_rig
    no_entry_path = rig.watch_dir / "no_baseline_entry.txt"
    no_entry_path.write_bytes(b"unrelated content, no baseline for this path")

    mock_valkey = AsyncMock()
    mock_valkey.xadd = AsyncMock()

    cmd = {
        "command_id": "cmd-restore-002",
        "event_id": "evt-2",
        "path": str(no_entry_path),
    }

    await commands.handle_restore_file(
        command=cmd,
        baseline_engine=rig.baseline,
        journal=rig.journal,
        valkey_client=mock_valkey,
        config=rig.config,
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "error"
    assert ack_payload["error"] is not None
    assert no_entry_path.read_bytes() == b"unrelated content, no baseline for this path"
    assert rig.publisher.payloads == []


@pytest.mark.asyncio
async def test_quarantine_still_reports_the_absence(no_remediation_rig: RestoreRig) -> None:
    """Sin regla `auto_restore` compitiendo por el mismo path (RN-30: cualquier
    regla `auto_restore` alcanza, D-1 del design) — este test aísla la
    asimetría de `quarantine_file`, no la interacción con la remediación."""
    from agent import commands

    rig = no_remediation_rig
    quarantine_dir = rig.tmp_path / "quarantine"
    quarantine_dir.mkdir(exist_ok=True)

    mock_valkey = AsyncMock()
    mock_valkey.xadd = AsyncMock()

    cmd = {
        "command_id": "cmd-quarantine-001",
        "event_id": "evt-3",
        "path": str(rig.target),
    }

    await commands.handle_quarantine_file(
        command=cmd,
        journal=rig.journal,
        valkey_client=mock_valkey,
        config=rig.config,
        quarantine_dir=str(quarantine_dir),
    )

    mock_valkey.xadd.assert_called_once()
    ack_payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert ack_payload["status"] == "ok"
    assert not rig.target.exists()

    # shutil.move produce el FAN_MOVED_FROM sobre el path original.
    await _inject(rig, rig.target, FAN_MOVED_FROM)

    assert len(rig.publisher.payloads) == 1
    assert rig.publisher.payloads[0]["event_type"] == "file_deleted"
    entry = rig.baseline.read_entry(str(rig.target))
    assert entry is not None
    assert entry.status == "absent"


@pytest.mark.asyncio
async def test_auto_restore_on_absent_entry_fails_without_looping(restore_rig: RestoreRig) -> None:
    rig = restore_rig
    rig.baseline.mark_absent(str(rig.target))
    os.remove(str(rig.target))

    # Un archivo nuevo aparece en ese path (RN-30: cualquier auto_restore
    # normal lo alcanza porque las reglas se evalúan por path, D-1 del design).
    new_content = b"attacker-controlled content"
    rig.target.write_bytes(new_content)

    await _inject(rig, rig.target, FAN_CREATE)

    assert len(rig.publisher.payloads) == 1
    payload = rig.publisher.payloads[0]
    assert payload["action_failed"] is True
    assert payload["action_error"] == "no_restorable_content"
    # Sin mutación del filesystem: el contenido recién creado queda intacto.
    assert rig.target.read_bytes() == new_content

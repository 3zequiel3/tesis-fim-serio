"""
Detector reactivo de cambios en el filesystem usando pyfanotify (C09, RN-01/02/03/04/93).
Solo activo en Linux con CAP_SYS_ADMIN.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import difflib
import hashlib
import os
import platform
import threading
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agent.baseline import BaselineEngine
    from agent.decision import DecisionEngine
    from agent.publisher import Publisher

log = structlog.get_logger()

_LINUX = platform.system() == "Linux"
_TEXT_PROBE_BYTES = 8192
_MAX_DIFF_BYTES = 1024 * 1024  # 1 MB
_AGENT_WORK_DIR = "/var/lib/fim-agent"
_DRAIN_TIMEOUT_S = 30.0
_AT_FDCWD = -100  # Linux AT_FDCWD

if _LINUX:
    try:
        import pyfanotify as _fan_mod
        _HAS_FAN = True
    except ImportError:
        _HAS_FAN = False
        _fan_mod = None  # type: ignore[assignment]
else:
    _HAS_FAN = False
    _fan_mod = None  # type: ignore[assignment]


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclasses.dataclass
class FanotifyEvent:
    """Evento raw recibido de pyfanotify (interno al detector)."""
    path: str
    pid: int
    uid: int
    exe: str | None
    timestamp: str
    mask: int = 0


@dataclasses.dataclass
class DetectedChange:
    """Payload de cambio detectado — se envía al publisher."""
    event_id: str
    path: str
    event_type: str          # "file_modified" | "file_absent" | "file_deleted" | "file_created"
    operation_type: str      # léxico canónico RN-71: mismos valores que event_type
    previous_hash: str | None
    current_hash: str | None
    diff_text: str | None
    process_pid: int
    process_uid: int
    process_exe: str | None
    detected_at: str
    parent_event_id: str | None

    def to_event_data(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ── Helpers de proceso ────────────────────────────────────────────────────────

def _get_exe(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None


def _get_uid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


# ── Helpers de contenido ──────────────────────────────────────────────────────

def _hash_file(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return None


async def _hash_file_async(
    path: str,
    retries: int = 3,
    base_delay: float = 0.05,
) -> str | None:
    """
    Hash SHA-256 con backoff exponencial para absorber races de write-tmp+rename (RN-01, RN-93).

    Happy path (archivo presente): retorna en el primer intento, sin ningún sleep.
    Solo emite None después de agotar todos los reintentos, lo que produce file_absent
    en _process_event. Budget máximo: 50 ms + 100 ms = 150 ms para archivos persistentemente ausentes.

    Usa asyncio.sleep para no bloquear el event loop durante los waits (D8).
    """
    for attempt in range(retries):
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            return h.hexdigest()
        except FileNotFoundError:
            if attempt < retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
    return None


def _is_text(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" not in f.read(_TEXT_PROBE_BYTES)
    except OSError:
        return False


def _generate_diff(previous_content: str, current_path: str) -> str | None:
    """Diff unificado entre contenido anterior y contenido actual. None si no aplica."""
    try:
        if os.path.getsize(current_path) > _MAX_DIFF_BYTES:
            return None
    except OSError:
        return None
    if not _is_text(current_path):
        return None
    try:
        with open(current_path, encoding="utf-8", errors="replace") as f:
            current_lines = f.readlines()
    except OSError:
        return None
    prev_lines = previous_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        prev_lines,
        current_lines,
        fromfile=f"a{current_path}",
        tofile=f"b{current_path}",
    ))
    return "".join(diff) if diff else None


# ── Clase principal ───────────────────────────────────────────────────────────

class FanotifyDetector:
    """
    Detector reactivo de cambios en el filesystem.

    Corre un hilo daemon que lee eventos pyfanotify (bloqueante) y los
    entrega al loop asyncio vía queue para su procesamiento.
    """

    def __init__(
        self,
        agent_id: str,
        watch_paths: list[str],
        baseline: "BaselineEngine",
        publisher: "Publisher",
        stop_event: asyncio.Event,
        decision_engine: "DecisionEngine | None" = None,
    ) -> None:
        self._agent_id = agent_id
        self._watch_paths = list(watch_paths)
        self._baseline = baseline
        self._publisher = publisher
        self._stop_event = stop_event
        self._decision_engine = decision_engine
        self._fan: Any = None
        self._raw_queue: asyncio.Queue[FanotifyEvent | None] = asyncio.Queue(maxsize=1000)
        self._event_drops: int = 0
        self._pending: dict[str, str] = {}          # path → event_id del último evento encolado
        self._event_to_path: dict[str, str] = {}    # event_id → path (índice inverso para ack O(1))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    # ── Backend fanotify (métodos aislados para poder mockear en tests) ────────

    def _init_fan(self) -> None:
        if not _HAS_FAN:
            raise RuntimeError(
                "pyfanotify no disponible — requiere Linux con CAP_SYS_ADMIN"
            )
        try:
            self._fan = _fan_mod.init(
                _fan_mod.FAN_CLASS_NOTIF | _fan_mod.FAN_CLOEXEC
            )
        except PermissionError as exc:
            raise RuntimeError(
                f"fanotify init falló — CAP_SYS_ADMIN requerido: {exc}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"fanotify init falló: {exc}") from exc

    def _mark_paths(self, paths: list[str]) -> None:
        mask = (
            _fan_mod.FAN_CLOSE_WRITE
            | _fan_mod.FAN_DELETE
            | _fan_mod.FAN_MOVED_FROM
            | _fan_mod.FAN_MOVED_TO
            | _fan_mod.FAN_CREATE
        )
        for path in paths:
            _fan_mod.mark(
                self._fan,
                _fan_mod.FAN_MARK_ADD | _fan_mod.FAN_MARK_FILESYSTEM,
                mask,
                _AT_FDCWD,
                path,
            )

    def _mark_exclusion(self) -> None:
        mask = (
            _fan_mod.FAN_CLOSE_WRITE
            | _fan_mod.FAN_DELETE
            | _fan_mod.FAN_MOVED_FROM
            | _fan_mod.FAN_MOVED_TO
            | _fan_mod.FAN_CREATE
        )
        _fan_mod.mark(
            self._fan,
            _fan_mod.FAN_MARK_ADD
            | _fan_mod.FAN_MARK_FILESYSTEM
            | _fan_mod.FAN_MARK_IGNORED_MASK,
            mask,
            _AT_FDCWD,
            _AGENT_WORK_DIR,
        )

    def _flush_marks(self) -> None:
        _fan_mod.mark(
            self._fan,
            _fan_mod.FAN_MARK_FLUSH | _fan_mod.FAN_MARK_FILESYSTEM,
            0,
            _AT_FDCWD,
            "",
        )

    def _read_fan_events(self) -> list[Any]:
        """Lee eventos de pyfanotify (bloqueante). Retorna lista de eventos."""
        return _fan_mod.read(self._fan)

    # ── Hilo de lectura ────────────────────────────────────────────────────────

    def _read_loop(self) -> None:
        assert self._loop is not None
        while not self._stop_event.is_set():
            try:
                raw_events = self._read_fan_events()
            except OSError as exc:
                if self._stop_event.is_set():
                    break
                log.warning("detector.read_error", error=str(exc))
                continue
            for ev in raw_events:
                if self._stop_event.is_set():
                    break
                if ev.path is None:
                    log.warning("detector.event_null_path", pid=ev.pid)
                    continue
                fan_event = FanotifyEvent(
                    path=ev.path,
                    pid=ev.pid,
                    uid=_get_uid(ev.pid),
                    exe=_get_exe(ev.pid),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    mask=getattr(ev, "mask", 0),
                )
                self._loop.call_soon_threadsafe(self._try_enqueue, fan_event)

    def _try_enqueue(self, fan_event: FanotifyEvent) -> None:
        """Intenta encolar un evento; si la cola está llena incrementa el contador de drops."""
        try:
            self._raw_queue.put_nowait(fan_event)
        except asyncio.QueueFull:
            self._event_drops += 1
            log.warning(
                "detector.event_dropped",
                path=fan_event.path,
                total_drops=self._event_drops,
            )

    @property
    def event_drops(self) -> int:
        """Contador acumulado de eventos descartados por cola llena."""
        return self._event_drops

    # ── Procesamiento async de eventos ─────────────────────────────────────────

    def _classify_event(self, mask: int) -> str | None:
        """
        Clasifica el mask de fanotify en operation_type canónico (RN-71).

        Retorna None si la máscara no corresponde a ningún tipo conocido.
        El orden de evaluación importa: FAN_CLOSE_WRITE tiene prioridad sobre CREATE
        para evitar clasificaciones incorrectas en kernels que combinan flags.
        """
        if not _HAS_FAN or _fan_mod is None:
            return "file_modified"
        if mask & _fan_mod.FAN_CLOSE_WRITE:
            return "close_write"
        if mask & _fan_mod.FAN_DELETE or mask & _fan_mod.FAN_MOVED_FROM:
            return "file_deleted"
        if mask & _fan_mod.FAN_CREATE or mask & _fan_mod.FAN_MOVED_TO:
            return "file_created"
        return None

    async def _process_event(self, fan_event: FanotifyEvent) -> None:
        path = fan_event.path
        entry = self._baseline.read_entry(path)
        previous_hash = entry.hash if entry else None

        event_class = self._classify_event(fan_event.mask)

        # ── Borrado / moved-from: sin hash, marcar ausente ─────────────────
        if event_class == "file_deleted":
            event_id = str(uuid.uuid4())
            parent_event_id = self._pending.get(path)
            if parent_event_id is not None:
                self._event_to_path.pop(parent_event_id, None)
            self._pending[path] = event_id
            self._event_to_path[event_id] = path

            change = DetectedChange(
                event_id=event_id,
                path=path,
                event_type="file_deleted",
                operation_type="file_deleted",
                previous_hash=previous_hash,
                current_hash=None,
                diff_text=None,
                process_pid=fan_event.pid,
                process_uid=fan_event.uid,
                process_exe=fan_event.exe,
                detected_at=fan_event.timestamp,
                parent_event_id=parent_event_id,
            )
            # BUG-01 (D14): evaluate FIRST so auto_restore can read baseline content;
            # only mutate baseline AFTER the decision is made.
            if self._decision_engine is not None:
                enriched_payload, commit_fn = self._decision_engine.evaluate_and_act(change)
                action = enriched_payload.get("action")
                action_failed = enriched_payload.get("action_failed", False)
            else:
                enriched_payload = change.to_event_data()
                commit_fn = None
                action = None
                action_failed = False
            if action == "auto_restore" and not action_failed:
                # File was restored — re-record as present/known-good
                self._baseline.write_entry(path)
            else:
                self._baseline.mark_absent(path)
            try:
                await self._publisher.publish(enriched_payload)
                if commit_fn is not None:
                    commit_fn()
            except Exception as exc:
                log.warning("detector.publish_failed", event_id=event_id, error=str(exc))
            log.info("detector.change_detected", path=path, event_type="file_deleted", event_id=event_id)
            return

        # ── Creación / moved-to: hashear, crear entry ──────────────────────
        if event_class == "file_created":
            current_hash = await _hash_file_async(path)
            if current_hash is None:
                log.warning("detector.created_file_vanished", path=path)
                return

            event_id = str(uuid.uuid4())
            parent_event_id = self._pending.get(path)
            if parent_event_id is not None:
                self._event_to_path.pop(parent_event_id, None)
            self._pending[path] = event_id
            self._event_to_path[event_id] = path

            change = DetectedChange(
                event_id=event_id,
                path=path,
                event_type="file_created",
                operation_type="file_created",
                previous_hash=None,
                current_hash=current_hash,
                diff_text=None,
                process_pid=fan_event.pid,
                process_uid=fan_event.uid,
                process_exe=fan_event.exe,
                detected_at=fan_event.timestamp,
                parent_event_id=parent_event_id,
            )
            # BUG-02 (D14): evaluate FIRST so quarantine can act on the file before
            # the baseline records it as present.
            if self._decision_engine is not None:
                enriched_payload, commit_fn = self._decision_engine.evaluate_and_act(change)
                action = enriched_payload.get("action")
                action_failed = enriched_payload.get("action_failed", False)
            else:
                enriched_payload = change.to_event_data()
                commit_fn = None
                action = None
                action_failed = False
            if action == "quarantine" and not action_failed:
                # File was quarantined — record as absent (file was moved away)
                self._baseline.mark_absent(path)
            else:
                self._baseline.write_entry(path)
            try:
                await self._publisher.publish(enriched_payload)
                if commit_fn is not None:
                    commit_fn()
            except Exception as exc:
                log.warning("detector.publish_failed", event_id=event_id, error=str(exc))
            log.info("detector.change_detected", path=path, event_type="file_created", event_id=event_id)
            return

        # ── FAN_CLOSE_WRITE o evento sin clasificar: lógica existente ──────
        current_hash = await _hash_file_async(path)

        # Descartar si el contenido no cambió
        if current_hash is not None and current_hash == previous_hash:
            return

        if current_hash is None:
            event_type = "file_absent"
            operation_type = "file_absent"
            diff_text = None
        else:
            event_type = "file_modified"
            operation_type = "file_modified"
            # Diff usando contenido anterior (antes de actualizar baseline)
            previous_content: str | None = None
            if entry and entry.content_b64 and not entry.oversize:
                try:
                    raw = base64.b64decode(entry.content_b64)
                    previous_content = raw.decode("utf-8", errors="replace")
                except Exception:
                    previous_content = None
            diff_text = (
                _generate_diff(previous_content, path)
                if previous_content is not None
                else None
            )

        event_id = str(uuid.uuid4())
        parent_event_id = self._pending.get(path)

        # Mantener el índice inverso en lockstep con _pending (sin await entre las dos escrituras).
        # Invariante: _event_to_path[eid] == path  ⟺  _pending[path] == eid.
        # No se necesita asyncio.Lock: on_ack y _process_event corren en el mismo event loop
        # (D8, single-loop model); las regiones de mutación no contienen await.
        if parent_event_id is not None:
            self._event_to_path.pop(parent_event_id, None)
        self._pending[path] = event_id
        self._event_to_path[event_id] = path

        change = DetectedChange(
            event_id=event_id,
            path=path,
            event_type=event_type,
            operation_type=operation_type,
            previous_hash=previous_hash,
            current_hash=current_hash,
            diff_text=diff_text,
            process_pid=fan_event.pid,
            process_uid=fan_event.uid,
            process_exe=fan_event.exe,
            detected_at=fan_event.timestamp,
            parent_event_id=parent_event_id,
        )

        # Motor de decisión evalúa y actúa ANTES de actualizar el baseline,
        # para que auto_restore pueda leer el content_b64 anterior (RN-30).
        if self._decision_engine is not None:
            enriched_payload, commit_fn = self._decision_engine.evaluate_and_act(change)
            action = enriched_payload.get("action")
            action_failed = enriched_payload.get("action_failed", False)
        else:
            enriched_payload = change.to_event_data()
            commit_fn = None
            action = None
            action_failed = False

        # Actualizar baseline según resultado de la acción
        if event_type == "file_absent":
            if action == "auto_restore" and not action_failed:
                self._baseline.write_entry(path)  # archivo recreado por auto_restore
            else:
                self._baseline.mark_absent(path)
        else:  # file_modified
            if action == "auto_restore" and not action_failed:
                pass  # archivo restaurado, baseline anterior sigue siendo válido
            elif action == "quarantine" and not action_failed:
                self._baseline.mark_absent(path)  # archivo movido
            else:
                # BUG-03 (D14): only snapshot for audit; do NOT write_entry with attacker
                # content. Active content_b64/hash stay pinned to known-good so
                # select_restorable_content always returns the last approved state.
                self._baseline.add_snapshot(path)

        try:
            await self._publisher.publish(enriched_payload)
            if commit_fn is not None:
                commit_fn()
        except Exception as exc:
            log.warning("detector.publish_failed", event_id=event_id, error=str(exc))
        log.info(
            "detector.change_detected",
            path=path,
            event_type=enriched_payload.get("event_type", event_type),
            event_id=event_id,
        )

    # ── API pública ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Arranca el detector: inicializa fanotify, lanza hilo lector, consume eventos."""
        self._loop = asyncio.get_running_loop()
        self._init_fan()
        self._mark_paths(self._watch_paths)
        self._mark_exclusion()

        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="fan-reader"
        )
        self._thread.start()
        log.info("detector.started", watch_paths=self._watch_paths)

        while not self._stop_event.is_set():
            try:
                fan_event = await asyncio.wait_for(
                    self._raw_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            if fan_event is None:
                break
            try:
                await self._process_event(fan_event)
            except Exception as exc:
                log.error(
                    "detector.process_error",
                    path=fan_event.path,
                    error=str(exc),
                )

        log.info("detector.stopped")

    def on_ack(self, event_id: str) -> None:
        """
        Llamado por el command consumer al recibir event_ack — limpia _pending en O(1).

        Usa el índice inverso _event_to_path para evitar el scan O(N) anterior.
        Safe no-op si event_id no está en el índice (ack duplicado o ya expirado).
        """
        path = self._event_to_path.pop(event_id, None)
        if path is not None and self._pending.get(path) == event_id:
            del self._pending[path]

    async def drain(self, timeout: float = _DRAIN_TIMEOUT_S) -> None:
        """Espera hasta que la cola offline drene o se cumpla el timeout (RN-93)."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._publisher._queue.queue_size == 0:
                break
            await asyncio.sleep(0.5)

    def reload_paths(self, new_paths: list[str]) -> None:
        """Recarga watch_paths en caliente al recibir update_config (RN-04)."""
        added = [p for p in new_paths if p not in self._watch_paths]
        for path in added:
            self._baseline.init_scan([path])
        try:
            self._flush_marks()
        except Exception as exc:
            log.warning("detector.flush_error", error=str(exc))
        self._watch_paths = list(new_paths)
        self._mark_paths(self._watch_paths)
        self._mark_exclusion()
        log.info("detector.paths_reloaded", watch_paths=self._watch_paths)

    def reload_watch_paths(self, new_paths: list[str]) -> None:
        """
        Recarga watch_paths en caliente (C14, D-C14-06).

        Desmarca de fanotify los paths que ya no están en new_paths,
        marca los paths nuevos, y actualiza self._watch_paths.

        Thread-safe: se ejecuta en el event loop del detector (llamado desde handler
        async, que corre en el mismo loop que _process_event).

        No llama init_scan/run_scan — eso lo hace el caller (handle_update_config).
        """
        current = set(self._watch_paths)
        updated = set(new_paths)

        removed = current - updated
        added = updated - current

        if not _HAS_FAN:
            # En plataformas sin fanotify (Windows/test) solo actualiza el atributo
            self._watch_paths = list(new_paths)
            log.info(
                "detector.reload_watch_paths.noop_no_fan",
                added=list(added),
                removed=list(removed),
            )
            return

        fan_mask = (
            _fan_mod.FAN_CLOSE_WRITE
            | _fan_mod.FAN_DELETE
            | _fan_mod.FAN_MOVED_FROM
            | _fan_mod.FAN_MOVED_TO
            | _fan_mod.FAN_CREATE
        )

        # Desmarcar paths eliminados
        for path in removed:
            try:
                _fan_mod.mark(
                    self._fan,
                    _fan_mod.FAN_MARK_REMOVE | _fan_mod.FAN_MARK_FILESYSTEM,
                    fan_mask,
                    _AT_FDCWD,
                    path,
                )
            except Exception as exc:
                log.warning("detector.reload_watch_paths.unmark_failed", path=path, error=str(exc))

        # Marcar paths nuevos
        for path in added:
            try:
                _fan_mod.mark(
                    self._fan,
                    _fan_mod.FAN_MARK_ADD | _fan_mod.FAN_MARK_FILESYSTEM,
                    fan_mask,
                    _AT_FDCWD,
                    path,
                )
            except Exception as exc:
                log.warning("detector.reload_watch_paths.mark_failed", path=path, error=str(exc))

        self._watch_paths = list(new_paths)
        log.info(
            "detector.reload_watch_paths.done",
            added=list(added),
            removed=list(removed),
            watch_paths=self._watch_paths,
        )

    def close(self) -> None:
        """Cierra el fd de fanotify y espera a que el hilo lector termine.

        Idempotente: una segunda llamada es un no-op seguro.
        El hilo reader bloqueado en read() desbloquea al cerrarse el fd.
        """
        fan = self._fan
        if fan is None:
            return
        self._fan = None
        try:
            if _HAS_FAN and _fan_mod is not None:
                _fan_mod.close(fan)
        except OSError:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                log.warning("detector.close.join_timeout", thread=self._thread.name)

    @property
    def watch_paths(self) -> list[str]:
        """Retorna la lista actual de watch_paths."""
        return list(self._watch_paths)

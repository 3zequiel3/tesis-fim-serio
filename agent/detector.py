"""
Detector reactivo de cambios en el filesystem usando el backend fanotify interno de
`agent/_fanotify.py` (ctypes sobre syscalls crudas, modo FID; D46/RN-140) (C09, RN-01/02/03/04/93).
Solo activo en Linux con CAP_SYS_ADMIN y CAP_DAC_READ_SEARCH.
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
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from agent.experiment_trace import ExperimentTrace

if TYPE_CHECKING:
    from agent.baseline import BaselineEngine
    from agent.decision import DecisionEngine
    from agent.publisher import Publisher

log = structlog.get_logger()

_LINUX = platform.system() == "Linux"
_MAX_DIFF_BYTES = 1024 * 1024  # 1 MB
_AGENT_WORK_DIR = "/var/lib/fim-agent"
_DRAIN_TIMEOUT_S = 30.0
_AT_FDCWD = -100  # Linux AT_FDCWD
# D50/RN-144: a lo sumo un detection_gap por ventana. Bajo saturación sostenida
# el kernel emite FAN_Q_OVERFLOW repetidamente; deduplicar por desbordamiento
# inundaría la tabla justo cuando menos capacidad hay para procesarla.
_DETECTION_GAP_WINDOW_S = 60.0

if _LINUX:
    try:
        from agent import _fanotify as _fan_mod
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
    """Evento raw recibido del backend fanotify interno (agent/_fanotify.py)."""
    path: str
    pid: int
    # D49/RN-143: None = atribución no resuelta (el proceso ya no existe cuando se
    # consulta /proc/<pid>/status). 0 significa EXCLUSIVAMENTE root. Ver _get_uid.
    uid: int | None
    exe: str | None
    timestamp: str
    mask: int = 0


@dataclasses.dataclass
class DetectedChange:
    """Payload de cambio detectado — se envía al publisher."""
    event_id: str
    path: str
    event_type: str          # "file_modified" | "file_absent" | "file_deleted" | "file_created" | "detection_gap"
    operation_type: str      # léxico canónico RN-71: mismos valores que event_type
    hash_expected: str | None
    hash_detected: str | None
    diff_text: str | None
    process_pid: int
    # D49/RN-143: None = atribución no resuelta. 0 = root, y solo root.
    process_uid: int | None
    process_exe: str | None
    detected_at: str
    parent_event_id: str | None
    is_symlink: bool = False        # D33/RN-127: symlink-as-object, nunca se sigue el link
    symlink_target: str | None = None  # string crudo de os.readlink, sin normalizar

    def to_event_data(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        # D-C13-04: "" (string vacío) = "hash ausente" (borrado/no hasheable).
        # El contrato con el backend exige hash_detected str NOT NULL; nunca emitir None.
        # (hash_expected puede seguir None: no se persiste en el modelo Event del backend.)
        if data.get("hash_detected") is None:
            data["hash_detected"] = ""
        return data


# ── Helpers de proceso ────────────────────────────────────────────────────────

def _get_exe(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None


def _get_uid(pid: int) -> int | None:
    """Resuelve el uid del proceso causante desde /proc/<pid>/status (best-effort).

    D49/RN-143: retorna `None` si `/proc/<pid>/status` no es accesible — el proceso
    ya terminó, lo que es rutinario y no excepcional: entre la notificación del
    kernel y el armado del evento hay hasta 150 ms de reintentos de hash
    (`_hash_file_async`), y cualquier proceso corto (un editor, `install`, un paso
    de gestor de paquetes) ya no existe cuando se lo consulta. `0` significa
    EXCLUSIVAMENTE que el proceso corría como root — nunca se usa como relleno
    para una atribución que no se pudo resolver, porque contaminaría toda
    búsqueda de cambios privilegiados con los cambios de autor desconocido.
    Alineado con `_get_exe`, que ya devuelve `None` en el mismo caso.
    """
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


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
            content = f.read(_MAX_DIFF_BYTES + 1)
    except OSError:
        return False
    return len(content) <= _MAX_DIFF_BYTES and _is_text_bytes(content)


def _is_text_bytes(value: bytes) -> bool:
    """Require valid UTF-8 and reject binary control bytes, not only NUL."""
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return all(
        char in "\t\n\r\f" or not (ord(char) < 32 or 127 <= ord(char) < 160)
        for char in text
    )


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
        with open(current_path, encoding="utf-8", errors="strict") as f:
            current_lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not _is_text_bytes(previous_content.encode("utf-8")):
        return None
    prev_lines = previous_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        prev_lines,
        current_lines,
        fromfile=f"a{current_path}",
        tofile=f"b{current_path}",
    ))
    result = "".join(diff) if diff else None
    if result is not None and len(result.encode("utf-8")) > _MAX_DIFF_BYTES:
        return None
    return result


# ── Helpers de scope (RN-04, D31/RN-125, refinado por D33/RN-127) ────────────

def _target_in_scope(path: str, canonical_roots: list[str]) -> bool:
    """
    True si el `realpath` de `path` (destino resuelto, siguiendo symlinks) está
    contenido (`is_relative_to`) en alguno de los `canonical_roots` ya
    canonicalizados con `os.path.realpath`.

    Ex `_realpath_in_scope` (D31/RN-125). Tras D33/RN-127 queda SOLO para checks
    de metadata sobre el DESTINO resuelto de un path (p. ej. el containment de un
    archivo regular alcanzado vía un directorio intermedio simbólico, usado por
    `agent/baseline.py`) — NUNCA se usa en el punto de descarte de `_read_loop`,
    porque dereferencia el componente final y por eso ocultaba un symlink de
    escape (hallazgo MEDIUM-2 de la revisión dual-judge de C37). Para esa
    decisión usar `_path_location_in_scope`.

    Se usa `is_relative_to` (no `startswith`) para evitar falsos positivos por
    prefijo (p. ej. `/etc/apple` vs root `/etc/app`).

    Lista de roots vacía → False: nada está en scope (RN-04, "excepciones: ninguna").
    """
    if not canonical_roots:
        return False
    real = Path(os.path.realpath(path))
    return any(real.is_relative_to(root) for root in canonical_roots)


def _path_location_in_scope(path: str, canonical_roots: list[str]) -> bool:
    """
    True si la UBICACIÓN de `path` está en scope: canonicaliza SOLO el
    directorio padre (`os.path.realpath(os.path.dirname(path))`) y compara el
    `basename` literal contra los `canonical_roots`, SIN seguir (sin
    dereferenciar) el componente final aunque sea un symlink.

    El directorio padre siempre existe en el momento del evento — incluso en un
    DELETE, donde el componente final ya no está — así que canonicalizarlo es
    seguro y determinista (a diferencia de canonicalizar el path completo, que
    o dereferencia el link final o falla si ya no existe).

    Reemplaza a `_target_in_scope` en el punto de descarte de `_read_loop`
    (D33/RN-127, refina D31/RN-125): un symlink de escape creado dentro de un
    `watch_path` (p. ej. `/etc/evil -> /root/.ssh/authorized_keys`) está en
    scope por UBICACIÓN aunque su destino resuelto no lo esté — el link en sí
    es una entrada de directorio nueva y un vector de persistencia clásico que
    el FIM debe reportar (ver la rama symlink-as-object en `_process_event`).

    Lista de roots vacía → False: nada está en scope (RN-04, "excepciones: ninguna").
    """
    if not canonical_roots:
        return False
    parent_real = Path(os.path.realpath(os.path.dirname(path)))
    candidate = parent_real / os.path.basename(path)
    return any(candidate.is_relative_to(root) for root in canonical_roots)


# ── Clase principal ───────────────────────────────────────────────────────────

class FanotifyDetector:
    """
    Detector reactivo de cambios en el filesystem.

    Corre un hilo daemon que lee eventos del backend fanotify interno
    (bloqueante) y los entrega al loop asyncio vía queue para su procesamiento.
    """

    def __init__(
        self,
        agent_id: str,
        watch_paths: list[str],
        baseline: "BaselineEngine",
        publisher: "Publisher",
        stop_event: asyncio.Event,
        decision_engine: "DecisionEngine | None" = None,
        experiment_trace: ExperimentTrace | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._watch_paths = list(watch_paths)
        self._watch_paths_real: list[str] = [
            os.path.realpath(p) for p in self._watch_paths
        ]
        self._baseline = baseline
        self._publisher = publisher
        self._stop_event = stop_event
        self._decision_engine = decision_engine
        # Opt-in experimental evidence only; this object never influences detection.
        self._experiment_trace = experiment_trace or ExperimentTrace.from_environment()
        self._fan: Any = None
        self._raw_queue: asyncio.Queue[FanotifyEvent | None] = asyncio.Queue(maxsize=1000)
        self._event_drops: int = 0
        self._out_of_scope_drops: int = 0
        self._hardlink_suspected: int = 0
        self._pending: dict[str, str] = {}          # path → event_id del último evento encolado
        self._event_to_path: dict[str, str] = {}    # event_id → path (índice inverso para ack O(1))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # D50/RN-144: estado de la ventana de deduplicación de detection_gap.
        # Escritos y leídos SOLO desde el hilo lector (_read_loop) — no necesita
        # lock. time.monotonic() y no datetime.now(): un ajuste de reloj del
        # host no debe suprimir ni disparar emisiones. En memoria, no persiste:
        # tras un reinicio del agente el primer desbordamiento emite siempre
        # (D-4 del design) — es el comportamiento correcto, la ventana anterior
        # ya no es comparable.
        self._last_detection_gap_at: float | None = None
        self._suppressed_overflow_count: int = 0

    def _trace_record(self, stage: str, **fields: Any) -> None:
        """Write best-effort experimental evidence without changing the pipeline."""
        try:
            self._experiment_trace.record(stage, **fields)
        except Exception:
            # A malformed or unavailable experiment trace must never create a
            # business outcome, a dropped event, or a failed publication.
            return

    def _trace_change_created(
        self, change: DetectedChange, baseline_status: str | None
    ) -> None:
        self._trace_record(
            "change_classified",
            event_id=change.event_id,
            path=change.path,
            operation=change.operation_type,
            hash_before=change.hash_expected,
            hash_after=change.hash_detected,
            baseline_status=baseline_status,
            baseline_hash=change.hash_expected,
            outcome="classified",
        )

    def _trace_decision(self, change: DetectedChange, payload: dict[str, Any]) -> None:
        self._trace_record(
            "decision_evaluated",
            event_id=change.event_id,
            path=change.path,
            operation=change.operation_type,
            hash_before=change.hash_expected,
            hash_after=change.hash_detected,
            decision=payload.get("action") or "alert_only",
            reason=payload.get("action_error") or "rule_evaluated",
            outcome="decision_complete",
        )

    # ── Backend fanotify (métodos aislados para poder mockear en tests) ────────

    def _init_fan(self) -> None:
        if not _HAS_FAN:
            raise RuntimeError(
                "backend fanotify no disponible — se requiere Linux >= 5.1 con "
                "CAP_SYS_ADMIN y CAP_DAC_READ_SEARCH"
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
        # FAN_MARK_FILESYSTEM aplica la máscara de IGNORADOS a TODO el superblock.
        # Si el work dir comparte filesystem (st_dev) con algún watch_path, ignorar
        # su fs cegaría también los paths vigilados → pérdida silenciosa de eventos.
        # En ese caso se OMITE la exclusión: es solo una optimización y el filtro de
        # scope (_path_location_in_scope) ya descarta los eventos del work dir.
        try:
            work_dev = os.stat(_AGENT_WORK_DIR).st_dev
            watch_devs = {
                os.stat(p).st_dev
                for p in self._watch_paths_real
                if os.path.exists(p)
            }
        except OSError as exc:
            log.warning("detector.mark_exclusion_stat_failed", error=str(exc))
            return
        if work_dev in watch_devs:
            log.warning(
                "detector.mark_exclusion_skipped_same_fs",
                work_dir=_AGENT_WORK_DIR,
                reason=(
                    "work dir comparte filesystem con watch_paths; una marca "
                    "FILESYSTEM de ignorados los cegaría. Se delega en el filtro de scope."
                ),
            )
            return
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
            | _fan_mod.FAN_MARK_IGNORED_MASK
            | _fan_mod.FAN_MARK_IGNORED_SURV_MODIFY,
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
        """Lee eventos del backend fanotify interno (bloqueante). Retorna lista de eventos."""
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
                # D50/RN-144: el chequeo del bit de desbordamiento va ANTES del
                # descarte por path nulo. Un FAN_Q_OVERFLOW no tiene path por
                # construcción (no habla de ningún archivo) — si este chequeo
                # fuera después, el aviso de la brecha de cobertura caería en
                # el descarte genérico y se perdería exactamente lo que existe
                # para no perderse.
                if getattr(ev, "mask", 0) & _fan_mod.FAN_Q_OVERFLOW:
                    self._handle_overflow()
                    continue
                if ev.path is None:
                    self._trace_record("kernel_dropped", operation="kernel", reason="null_path", outcome="dropped")
                    log.warning("detector.event_null_path", pid=ev.pid)
                    continue
                if not _path_location_in_scope(ev.path, self._watch_paths_real):
                    self._out_of_scope_drops += 1
                    log.warning(
                        "detector.out_of_scope_drop",
                        path=ev.path,
                        total_drops=self._out_of_scope_drops,
                    )
                    continue
                # Trace only in-scope kernel events. The fanotify mark covers the
                # whole filesystem, so tracing an out-of-scope write to the trace
                # file itself would create a self-amplifying event loop.
                self._trace_record(
                    "kernel_received",
                    path=ev.path,
                    operation="kernel",
                    kernel_event=self._classify_event(getattr(ev, "mask", 0)) or "unclassified",
                    outcome="received",
                )
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
            self._trace_record("kernel_dropped", path=fan_event.path, operation="kernel", reason="raw_queue_full", outcome="dropped", queue_size=self._raw_queue.qsize())
            log.warning(
                "detector.event_dropped",
                path=fan_event.path,
                total_drops=self._event_drops,
            )

    def _handle_overflow(self) -> None:
        """Deduplica FAN_Q_OVERFLOW por ventana de 60 s y emite detection_gap (D50/RN-144).

        Corre en el hilo lector. Si no hubo emisión previa o transcurrieron
        ≥ _DETECTION_GAP_WINDOW_S desde la última, emite con la cuenta de
        supresiones acumulada y la reinicia; si no, solo incrementa el
        contador y no publica nada — evita inundar la tabla de eventos bajo
        saturación sostenida, que es cuando menos capacidad hay para
        procesarla.
        """
        now = time.monotonic()
        if (
            self._last_detection_gap_at is None
            or (now - self._last_detection_gap_at) >= _DETECTION_GAP_WINDOW_S
        ):
            suppressed = self._suppressed_overflow_count
            self._suppressed_overflow_count = 0
            self._last_detection_gap_at = now
            self._emit_detection_gap(suppressed)
        else:
            self._suppressed_overflow_count += 1

    def _emit_detection_gap(self, suppressed_count: int) -> None:
        """Arma y publica el evento sintético detection_gap (D50/RN-144).

        Sin ruta, sin contexto de proceso: el kernel descartó eventos y el
        agente nunca los recibió, así que no hay nada de eso que reportar.
        NO invoca DecisionEngine.evaluate_and_act ni escribe journal (D-5 del
        design): el motor evalúa reglas contra la ruta y sus acciones físicas
        operan sobre el filesystem — un evento sin ruta no tiene nada que
        matchear ni nada sobre qué actuar. NO toca el baseline: el evento no
        habla de ningún archivo.
        """
        event_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "event_id": event_id,
            "path": None,
            "event_type": "detection_gap",
            "operation_type": "detection_gap",
            "hash_expected": None,
            # D-C13-04: hash_detected es str NOT NULL en el modelo Event del
            # backend; nunca emitir None.
            "hash_detected": "",
            "diff_text": None,
            "process_pid": None,
            "process_uid": None,
            "process_exe": None,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "parent_event_id": None,
            "cause": "fan_q_overflow",
            "action": "alert_only",
            "suppressed_count": suppressed_count,
        }
        log.warning(
            "detector.detection_gap",
            suppressed_count=suppressed_count,
            event_id=event_id,
        )
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._schedule_detection_gap_publish, payload)

    def _schedule_detection_gap_publish(self, payload: dict[str, Any]) -> None:
        """Envoltorio sync que agenda la corrutina de publish (llamado vía call_soon_threadsafe).

        NO pasa por self._raw_queue: bajo saturación esa cola es justamente lo
        que está lleno, y perder el aviso de pérdida por QueueFull anularía el
        propósito de la regla (D-3 del design). Corre ya en el hilo del event
        loop (call_soon_threadsafe lo garantiza), así que agendar la tarea acá
        es seguro sin run_coroutine_threadsafe.
        """
        assert self._loop is not None
        self._loop.create_task(self._publish_detection_gap(payload))

    async def _publish_detection_gap(self, payload: dict[str, Any]) -> None:
        try:
            await self._publisher.publish(payload)
        except Exception as exc:
            log.warning(
                "detector.detection_gap.publish_failed",
                event_id=payload.get("event_id"),
                error=str(exc),
            )

    @property
    def event_drops(self) -> int:
        """Contador acumulado de eventos descartados por cola llena."""
        return self._event_drops

    @property
    def out_of_scope_drops(self) -> int:
        """Contador acumulado de eventos descartados por caer fuera de watch_paths (RN-04)."""
        return self._out_of_scope_drops

    @property
    def hardlink_suspected(self) -> int:
        """
        Contador detective opcional (D33/RN-127): cuántas veces se creó un archivo
        regular en scope con `st_nlink >= 2`. NO altera clasificación, hash, cifrado
        ni publicación — es una señal barata para el operador, no una detección
        (alto falso-positivo; los hardlinks quedan documentados como limitación
        POSIX-inherente, ver design D-5).
        """
        return self._hardlink_suspected

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
        if path.endswith(".fim_restore_tmp"):
            return  # suppress agent-internal atomic write tmp files (D19)
        entry = self._baseline.read_entry(path)
        previous_hash = entry.hash if entry else None
        self._trace_record(
            "baseline_read",
            path=path,
            operation="process",
            baseline_status=entry.status if entry else "missing",
            baseline_hash=previous_hash,
            baseline_revision="unversioned_hash_status",
            outcome="read",
        )
        # D33/RN-127: una entry con symlink_target indica que el path YA ERA un
        # symlink en el baseline. Se usa en el borrado (donde el path ya no existe
        # y no se puede volver a hacer lstat/readlink).
        was_symlink = entry.symlink_target is not None if entry else False
        previous_symlink_target = entry.symlink_target if entry else None

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
                hash_expected=previous_hash,
                hash_detected=None,
                diff_text=None,
                process_pid=fan_event.pid,
                process_uid=fan_event.uid,
                process_exe=fan_event.exe,
                detected_at=fan_event.timestamp,
                parent_event_id=parent_event_id,
                is_symlink=was_symlink,
                symlink_target=previous_symlink_target,
            )
            self._trace_change_created(change, entry.status if entry else "missing")
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
            self._trace_decision(change, enriched_payload)
            if action == "auto_restore" and not action_failed:
                # File was restored — re-record as present/known-good.
                # D33/RN-127: auto_restore nunca tiene éxito sobre un symlink
                # (select_restorable_content retorna None sin contenido restaurable,
                # ver agent/decision.py::_auto_restore), pero se deja la rama
                # symlink-aware por defensividad/consistencia.
                if was_symlink:
                    self._baseline.write_symlink_entry(path)
                else:
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
            # D33/RN-127 — symlink-as-object: si el componente final es un symlink,
            # NUNCA seguirlo. os.lstat/os.readlink solamente; hash_detected es el
            # hash del STRING del destino, no de su contenido (Philosophy B).
            is_symlink = os.path.islink(path)
            symlink_target: str | None = None
            if is_symlink:
                try:
                    symlink_target = os.readlink(path)
                except OSError:
                    log.warning("detector.symlink_vanished", path=path)
                    return
                current_hash = hashlib.sha256(symlink_target.encode()).hexdigest()
            else:
                current_hash = await _hash_file_async(path)
                if current_hash is None:
                    log.warning("detector.created_file_vanished", path=path)
                    return
                # Contador detective opcional (D33/RN-127, D-5): st_nlink >= 2 en un
                # archivo regular sugiere un hardlink. NO cambia clasificación, hash,
                # cifrado ni publicación — solo incrementa un contador para el operador.
                try:
                    if os.stat(path).st_nlink >= 2:
                        self._hardlink_suspected += 1
                except OSError:
                    pass

            # D19/RN-117 (segunda mitad del mecanismo) + RN-33: el filtro de
            # sufijo de :457 solo cubre los eventos sobre el `.fim_restore_tmp`;
            # no cubre el FAN_MOVED_TO que `os.replace` entrega sobre el path
            # FINAL tras una restauración (agent/decision.py, agent/commands.py).
            # RN-33 garantiza que, tras una restauración exitosa, el hash del
            # archivo coincide con el del baseline — así que un MOVED_TO/CREATE
            # que aterriza contenido ya conocido no es un cambio real y no debe
            # reportarse, exactamente como ya hace la rama file_modified en
            # :620-621. Se exige además identidad de tipo de objeto (D33/RN-127):
            # un cambio de symlink a archivo regular (o viceversa) SIEMPRE se
            # reporta, aunque los hashes coincidan.
            if current_hash is not None and current_hash == previous_hash and is_symlink == was_symlink:
                log.debug(
                    "detector.discard_no_real_change",
                    path=path,
                    event_class=event_class,
                )
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
                hash_expected=None,
                hash_detected=current_hash,
                diff_text=None,
                process_pid=fan_event.pid,
                process_uid=fan_event.uid,
                process_exe=fan_event.exe,
                detected_at=fan_event.timestamp,
                parent_event_id=parent_event_id,
                is_symlink=is_symlink,
                symlink_target=symlink_target,
            )
            self._trace_change_created(change, entry.status if entry else "missing")
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
            self._trace_decision(change, enriched_payload)
            if action == "quarantine" and not action_failed:
                # File was quarantined — record as absent (file was moved away)
                self._baseline.mark_absent(path)
            elif is_symlink:
                self._baseline.write_symlink_entry(path)
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
        # D33/RN-127 — symlink-as-object: si el componente final es (todavía) un
        # symlink, hashear el STRING del destino (os.readlink), nunca su contenido.
        # Un re-pointing cambia el string → cambia el hash → se detecta como
        # file_modified con la misma lógica de comparación que un archivo regular.
        is_symlink = os.path.islink(path)
        symlink_target: str | None = None
        if is_symlink:
            try:
                symlink_target = os.readlink(path)
                current_hash = hashlib.sha256(symlink_target.encode()).hexdigest()
            except OSError:
                current_hash = None
        else:
            current_hash = await _hash_file_async(path)

        # Descartar si el contenido no cambió
        if current_hash is not None and current_hash == previous_hash:
            self._trace_record(
                "decision_suppressed",
                path=path,
                operation=event_class or "close_write",
                baseline_status=entry.status if entry else "missing",
                baseline_hash=previous_hash,
                hash_before=previous_hash,
                hash_after=current_hash,
                decision="suppress",
                reason="matches_active_baseline",
                outcome="dropped",
            )
            return

        if current_hash is None:
            event_type = "file_absent"
            operation_type = "file_absent"
            diff_text = None
        else:
            event_type = "file_modified"
            operation_type = "file_modified"
            # Diff usando contenido anterior (antes de actualizar baseline).
            # Garantía de seguridad C39 FORZADA por código: si el path es un
            # symlink NUNCA se genera diff (`_generate_diff` abre el path y
            # seguiría el link hasta el contenido del destino out-of-scope). No
            # se delega esta garantía al invariante "un symlink nunca tiene
            # content_b64": una entry regular obsoleta para un path que se volvió
            # symlink tendría content_b64 seteado y filtraría hasta 1 MB del
            # destino en diff_text. El guard `and not is_symlink` (la misma
            # variable que ya protege current_hash arriba) lo impide de raíz.
            previous_content: str | None = None
            if entry and entry.content_b64 and not entry.oversize:
                try:
                    raw = base64.b64decode(entry.content_b64)
                    previous_content = raw.decode("utf-8", errors="strict")
                    if not _is_text_bytes(raw):
                        previous_content = None
                except (ValueError, UnicodeDecodeError):
                    previous_content = None
            diff_text = (
                _generate_diff(previous_content, path)
                if (previous_content is not None and not is_symlink)
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
            hash_expected=previous_hash,
            hash_detected=current_hash,
            diff_text=diff_text,
            process_pid=fan_event.pid,
            process_uid=fan_event.uid,
            process_exe=fan_event.exe,
            detected_at=fan_event.timestamp,
            parent_event_id=parent_event_id,
            is_symlink=is_symlink,
            symlink_target=symlink_target,
        )
        self._trace_change_created(change, entry.status if entry else "missing")

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
        self._trace_decision(change, enriched_payload)

        # Actualizar baseline según resultado de la acción
        if event_type == "file_absent":
            if action == "auto_restore" and not action_failed:
                # archivo recreado por auto_restore. D33/RN-127: en la práctica
                # auto_restore nunca tiene éxito para un symlink (sin contenido
                # restaurable, ver agent/decision.py::_auto_restore), pero se deja
                # la rama por defensividad/consistencia.
                if is_symlink:
                    self._baseline.write_symlink_entry(path)
                else:
                    self._baseline.write_entry(path)
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
                # Para symlinks: add_snapshot opera igual (content_b64 siempre None,
                # solo archiva hash/captured_at) — no requiere rama especial.
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
        self._watch_paths_real = [os.path.realpath(p) for p in self._watch_paths]
        self._init_fan()
        self._mark_paths(self._watch_paths)
        # Exclusión del work dir: optimización, no correctitud. El filtro de scope
        # (_path_location_in_scope) ya descarta cualquier path fuera de watch_paths.
        # En modo FID la marca de ignorados puede ser rechazada (EINVAL) según kernel;
        # no debe abortar el arranque.
        try:
            self._mark_exclusion()
        except OSError as exc:
            log.warning("detector.mark_exclusion_skipped", error=str(exc))

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
        self._watch_paths_real = [os.path.realpath(p) for p in self._watch_paths]
        self._mark_paths(self._watch_paths)
        try:
            self._mark_exclusion()
        except OSError as exc:
            log.warning("detector.mark_exclusion_skipped", error=str(exc))
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
            self._watch_paths_real = [os.path.realpath(p) for p in self._watch_paths]
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
        self._watch_paths_real = [os.path.realpath(p) for p in self._watch_paths]
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

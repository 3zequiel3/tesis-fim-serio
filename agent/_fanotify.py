"""Backend fanotify interno sobre syscalls crudas (ctypes).

Provee la API a nivel de módulo que `agent/detector.py` espera de su backend
fanotify — `init`, `mark`, `read`, `close` más las constantes `FAN_*` — pero
que `pyfanotify==0.3.0` NO expone a nivel de módulo (su superficie pública es la
clase `Fanotify`/`FanotifyClient` con socket, incompatible con el hilo lector
bloqueante del detector).

Decisión de diseño (RN-01/02/03/93): se usa **reporte de FID** con
`FAN_REPORT_DFID_NAME`. El modo fd clásico (`FAN_CLASS_NOTIF` sin FID) NO admite
los eventos de entrada de directorio `FAN_CREATE`/`FAN_DELETE`/`FAN_MOVED_*` sobre
una marca de filesystem: el kernel responde EINVAL. El modo FID sí los entrega y,
además, permite reconstruir el path de un archivo ya borrado (el kernel reporta el
handle del directorio padre + el nombre), algo imposible cuando solo se tiene un fd
del objeto. La resolución del handle usa `open_by_handle_at(2)`, que requiere
`CAP_DAC_READ_SEARCH` además de `CAP_SYS_ADMIN` (ver unit de systemd).

Solo funcional en Linux con kernel >= 5.1. En otras plataformas la importación de
este módulo se degrada: el detector ya contempla `_HAS_FAN=False`.
"""

from __future__ import annotations

import ctypes
import os
import select
import struct
import threading
from typing import NamedTuple

# ── Constantes fanotify (asm-generic; estables entre arquitecturas Linux) ──────

# init() flags
FAN_CLASS_NOTIF = 0x00000000
FAN_CLOEXEC = 0x00000001
FAN_NONBLOCK = 0x00000002
FAN_REPORT_FID = 0x00000200
FAN_REPORT_DIR_FID = 0x00000400
FAN_REPORT_NAME = 0x00000800
FAN_REPORT_DFID_NAME = FAN_REPORT_DIR_FID | FAN_REPORT_NAME  # 0xC00

# mark() flags
FAN_MARK_ADD = 0x00000001
FAN_MARK_REMOVE = 0x00000002
FAN_MARK_IGNORED_MASK = 0x00000020
FAN_MARK_MOUNT = 0x00000010
FAN_MARK_IGNORED_SURV_MODIFY = 0x00000040
FAN_MARK_FLUSH = 0x00000080
FAN_MARK_FILESYSTEM = 0x00000100
FAN_MARK_INODE = 0x00000000
FAN_MARK_DONT_FOLLOW = 0x00000004  # 0x04 real (asm-generic); no usado aquí

# Máscara de eventos
FAN_ACCESS = 0x00000001
FAN_MODIFY = 0x00000002
FAN_CLOSE_WRITE = 0x00000008
FAN_CLOSE_NOWRITE = 0x00000010
FAN_OPEN = 0x00000020
FAN_MOVED_FROM = 0x00000040
FAN_MOVED_TO = 0x00000080
FAN_CREATE = 0x00000100
FAN_DELETE = 0x00000200
FAN_DELETE_SELF = 0x00000400
FAN_MOVE_SELF = 0x00000800
FAN_ONDIR = 0x40000000
# D50/RN-144: el kernel desbordó su cola de eventos fanotify y descartó eventos.
# Es el único modo de falla del sistema silencioso por construcción: el agente
# nunca recibe los eventos perdidos, solo esta señal de que la ventana existió.
FAN_Q_OVERFLOW = 0x00004000

FAN_NOFD = -1
FANOTIFY_METADATA_VERSION = 3

# Tipos de registro de información (info records) en modo FID
FAN_EVENT_INFO_TYPE_FID = 1
FAN_EVENT_INFO_TYPE_DFID_NAME = 2
FAN_EVENT_INFO_TYPE_DFID = 3

# open() flags para resolver el handle sin abrir contenido
_O_PATH = 0x00200000
_O_CLOEXEC = 0x00080000
_O_NONBLOCK = 0x00000800

# struct fanotify_event_metadata: u32 event_len; u8 vers; u8 reserved;
# u16 metadata_len; u64 mask; s32 fd; s32 pid
_META = struct.Struct("=IBBHQii")
_READ_TIMEOUT_S = 1.0


class FanEvent(NamedTuple):
    """Evento crudo resuelto que consume el detector (`.path`, `.pid`, `.mask`)."""

    path: str | None
    pid: int
    mask: int


class _Context:
    """Estado por descriptor fanotify: fds de montaje para resolver handles."""

    __slots__ = ("fan_fd", "mount_fds", "lock")

    def __init__(self, fan_fd: int) -> None:
        self.fan_fd = fan_fd
        # path marcado → fd O_PATH sobre ese filesystem (para open_by_handle_at)
        self.mount_fds: dict[str, int] = {}
        # Protege mount_fds: mutado en el hilo del event loop (mark/close),
        # leído en el hilo lector bloqueante (read). Sin esto, un reload de
        # config concurrente con read() dispara RuntimeError (dict changed
        # size during iteration) que escapa y mata el hilo lector.
        self.lock = threading.Lock()


_libc = ctypes.CDLL(None, use_errno=True)
try:
    _libc.open_by_handle_at.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    _libc.open_by_handle_at.restype = ctypes.c_int
except AttributeError:  # símbolo ausente (libc no-glibc o plataforma no soportada)
    _libc = None  # type: ignore[assignment]

_contexts: dict[int, _Context] = {}


def _errno_oserror(prefix: str = "") -> OSError:
    err = ctypes.get_errno()
    return OSError(err, (prefix + ": " if prefix else "") + os.strerror(err))


# ── API pública a nivel de módulo (contrato esperado por el detector) ──────────


def init(flags: int, o_flags: int = os.O_RDONLY | _O_CLOEXEC) -> int:
    """Envuelve fanotify_init(2). Fuerza reporte DFID_NAME para eventos de dir."""
    if _libc is None or not hasattr(_libc, "fanotify_init"):
        raise OSError("fanotify no disponible en esta plataforma")
    flags |= FAN_REPORT_DFID_NAME
    fd = _libc.fanotify_init(ctypes.c_uint(flags), ctypes.c_uint(o_flags))
    if fd < 0:
        err = ctypes.get_errno()
        if err in (1, 13):  # EPERM / EACCES
            raise PermissionError(err, os.strerror(err))
        raise OSError(err, os.strerror(err))
    _contexts[fd] = _Context(fd)
    return fd


def mark(fan_fd: int, flags: int, mask: int, dirfd: int, pathname: str) -> None:
    """Envuelve fanotify_mark(2) y mantiene los fds de montaje para resolución."""
    ctx = _contexts.get(fan_fd)

    if flags & FAN_MARK_FLUSH:
        _do_mark(fan_fd, flags, 0, dirfd, None)
        if ctx is not None:
            with ctx.lock:
                for mfd in ctx.mount_fds.values():
                    _safe_close(mfd)
                ctx.mount_fds.clear()
        return

    pb = pathname.encode() if pathname else None
    _do_mark(fan_fd, flags, mask, dirfd, pb)

    # Gestión de fds de montaje solo para marcas de observación reales
    # (no para exclusiones con IGNORED_MASK ni para paths vacíos).
    if ctx is None or not pathname or (flags & FAN_MARK_IGNORED_MASK):
        return
    if flags & FAN_MARK_ADD:
        with ctx.lock:
            if pathname not in ctx.mount_fds:
                mfd = _open_mount_fd(pathname)
                if mfd is not None:
                    ctx.mount_fds[pathname] = mfd
    elif flags & FAN_MARK_REMOVE:
        with ctx.lock:
            mfd = ctx.mount_fds.pop(pathname, None)
        if mfd is not None:
            _safe_close(mfd)


def read(fan_fd: int) -> list[FanEvent]:
    """Lee y resuelve eventos. Bloquea hasta `_READ_TIMEOUT_S`; [] al vencer."""
    try:
        ready, _, _ = select.select([fan_fd], [], [], _READ_TIMEOUT_S)
    except OSError:
        raise
    if not ready:
        return []
    buf = os.read(fan_fd, 64 * 1024)
    ctx = _contexts.get(fan_fd)
    if ctx is not None:
        with ctx.lock:
            mount_fds = list(ctx.mount_fds.values())
    else:
        mount_fds = []
    return _parse_events(buf, mount_fds)


def close(fan_fd: int) -> None:
    """Cierra el fd fanotify y libera los fds de montaje asociados."""
    ctx = _contexts.pop(fan_fd, None)
    if ctx is not None:
        with ctx.lock:
            for mfd in ctx.mount_fds.values():
                _safe_close(mfd)
            ctx.mount_fds.clear()
    _safe_close(fan_fd)


# ── Internos ───────────────────────────────────────────────────────────────────


def _do_mark(fan_fd: int, flags: int, mask: int, dirfd: int, pb: bytes | None) -> None:
    res = _libc.fanotify_mark(
        ctypes.c_int(fan_fd),
        ctypes.c_uint(flags),
        ctypes.c_uint64(mask),
        ctypes.c_int(dirfd),
        pb,
    )
    if res < 0:
        raise _errno_oserror("fanotify_mark")


def _open_mount_fd(pathname: str) -> int | None:
    """Abre un fd de referencia del montaje para open_by_handle_at.

    Debe ser un fd de directorio real (O_DIRECTORY): un descriptor O_PATH es
    rechazado con EBADF como `mount_fd`. Si el path marcado es un archivo se usa
    su directorio contenedor, que basta para identificar el filesystem.
    """
    target = pathname if os.path.isdir(pathname) else os.path.dirname(pathname)
    try:
        return os.open(target, os.O_RDONLY | os.O_DIRECTORY | _O_CLOEXEC)
    except OSError:
        return None


def _safe_close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _parse_events(buf: bytes, mount_fds: list[int]) -> list[FanEvent]:
    out: list[FanEvent] = []
    off = 0
    n = len(buf)
    while off + _META.size <= n:
        event_len, vers, _res, _mlen, mask, _fd, pid = _META.unpack_from(buf, off)
        if event_len < _META.size or off + event_len > n:
            break
        event_end = off + event_len
        # El fd en modo FID es FAN_NOFD (-1); si por versión antigua viniera un fd
        # real (>= 0), hay que cerrarlo para no filtrarlo.
        if _fd is not None and _fd >= 0:
            _safe_close(_fd)

        path = _resolve_path(buf, off + _META.size, event_end, mount_fds)
        out.append(FanEvent(path=path, pid=pid, mask=mask))
        off = event_end
    return out


def _resolve_path(
    buf: bytes, start: int, end: int, mount_fds: list[int]
) -> str | None:
    """Recorre los info records del evento y reconstruye el path del objeto.

    Prefiere DFID_NAME (directorio padre + nombre) porque funciona incluso si el
    objeto ya fue borrado. Cae a FID/DFID (resolución directa del handle) si no
    hay nombre disponible.
    """
    best_dir_name: tuple[bytes, str] | None = None  # (handle, name)
    fallback_handle: bytes | None = None

    off = start
    while off + 4 <= end:
        info_type, _pad, info_len = struct.unpack_from("=BBH", buf, off)
        if info_len < 4 or off + info_len > end:
            break
        if info_type in (
            FAN_EVENT_INFO_TYPE_FID,
            FAN_EVENT_INFO_TYPE_DFID,
            FAN_EVENT_INFO_TYPE_DFID_NAME,
        ):
            # header(4) + fsid(8) + struct file_handle
            fh_off = off + 4 + 8
            if fh_off + 8 <= off + info_len:
                handle_bytes, _htype = struct.unpack_from("=Ii", buf, fh_off)
                fh_total = 8 + handle_bytes
                handle = buf[fh_off : fh_off + fh_total]
                if info_type == FAN_EVENT_INFO_TYPE_DFID_NAME:
                    name_off = fh_off + fh_total
                    name = _read_cstr(buf, name_off, off + info_len)
                    if name is not None and best_dir_name is None:
                        best_dir_name = (handle, name)
                elif fallback_handle is None:
                    fallback_handle = handle
        off += info_len

    if best_dir_name is not None:
        handle, name = best_dir_name
        dir_path = _open_by_handle(handle, mount_fds)
        if dir_path is not None:
            if name in (".", ""):
                return dir_path
            return os.path.join(dir_path, name)
    if fallback_handle is not None:
        return _open_by_handle(fallback_handle, mount_fds)
    return None


def _read_cstr(buf: bytes, start: int, limit: int) -> str | None:
    try:
        end = buf.index(b"\x00", start, limit)
    except ValueError:
        end = limit
    if end <= start:
        return None
    return buf[start:end].decode("utf-8", errors="replace")


def _open_by_handle(handle: bytes, mount_fds: list[int]) -> str | None:
    """Resuelve un file_handle a un path probando cada fd de montaje."""
    hbuf = ctypes.create_string_buffer(handle, len(handle))
    for mfd in mount_fds:
        fd = _libc.open_by_handle_at(mfd, hbuf, _O_PATH | _O_CLOEXEC)
        if fd >= 0:
            try:
                return os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                return None
            finally:
                _safe_close(fd)
        # EStale/ESRCH → probar el siguiente montaje
    return None

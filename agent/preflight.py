"""Preflight de escritura por watch_path (D36/RN-130, D-3/D-4 del design).

Clasifica cada watch_path en un vocabulario cerrado (RN-71) sin ningún efecto
lateral: NO escribe ningún archivo sonda dentro de un watch_path — eso generaría
eventos fanotify del propio agente (RN-68 solo autoexcluye /var/lib/fim-agent/**).

classify_path_writability es pura, con los tres probes que hacen falta para
testearla sin root: statvfs_fn (barrera de mount), access_fn (barrera DAC),
exists_fn (existencia). run_preflight aplica la clasificación sobre un conjunto
de paths. PreflightRegistry es el estado compartido explícito — NUNCA variable
de módulo — que agent/heartbeat.py lee en cada latido y que
agent/commands.py:handle_update_config actualiza tras cada recarga.
"""
from __future__ import annotations

import os
from typing import Callable

# Vocabulario cerrado (RN-71) — snake_case minúsculas.
WRITABLE = "writable"
READ_ONLY_MOUNT = "read_only_mount"
PERMISSION_DENIED = "permission_denied"
MISSING = "missing"


def classify_path_writability(
    path: str,
    *,
    statvfs_fn: Callable[[str], object] = os.statvfs,
    access_fn: Callable[[str, int], bool] = os.access,
    exists_fn: Callable[[str], bool] = os.path.exists,
) -> str:
    """Clasifica un watch_path: writable | read_only_mount | permission_denied | missing.

    Orden de evaluación normativo (D-3): missing -> read_only_mount ->
    permission_denied -> writable. Un mount de solo lectura también hace fallar
    el chequeo de acceso; la causa útil para el operador en ese caso es la del
    mount ("falta el drop-in"), no la de permisos ("faltan capabilities").

    Se evalúa el DIRECTORIO, no el archivo: remediar un archivo requiere
    escritura sobre su directorio padre (crear el tmp, hacer el rename), no
    sobre el archivo en sí. Si el watch_path nombra un archivo regular, se
    evalúa su directorio padre.
    """
    check_path = path
    # os.path.isfile es una comprobación estructural (no un "probe" de
    # privilegio) — inofensiva sobre un path falso en tests puros, que
    # simplemente no existirá en el filesystem real y devolverá False.
    if os.path.isfile(path):
        check_path = os.path.dirname(path) or "/"

    if not exists_fn(check_path):
        return MISSING

    try:
        st = statvfs_fn(check_path)
        read_only = bool(st.f_flag & os.ST_RDONLY)  # type: ignore[attr-defined]
    except OSError:
        return MISSING

    if read_only:
        return READ_ONLY_MOUNT

    if not access_fn(check_path, os.W_OK):
        return PERMISSION_DENIED

    return WRITABLE


def run_preflight(watch_paths: list[str], **probes: Callable) -> dict[str, str]:
    """Aplica classify_path_writability sobre cada watch_path configurado."""
    return {path: classify_path_writability(path, **probes) for path in watch_paths}


class PreflightRegistry:
    """Estado compartido explícito del preflight (D-4).

    Objeto pasado por referencia a HeartbeatPublisher y al dispatcher de
    comandos — nunca variable de módulo, para que ambos consumidores sean
    testeables en aislamiento y sin estado global compartido entre tests.
    """

    def __init__(self) -> None:
        self._status: dict[str, str] = {}
        self._config_persisted: bool | None = None

    def update(self, mapping: dict[str, str]) -> None:
        """Reemplaza el mapa completo path -> clasificación."""
        self._status = dict(mapping)

    def set_config_persisted(self, value: bool) -> None:
        """Registra si el último intento de persistir config.yaml tuvo éxito."""
        self._config_persisted = value

    def snapshot(self) -> dict[str, str]:
        return dict(self._status)

    @property
    def config_persisted(self) -> bool | None:
        """None hasta que handle_update_config corra al menos una vez."""
        return self._config_persisted

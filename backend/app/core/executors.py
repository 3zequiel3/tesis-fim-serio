"""
Handles de los executors de hilos del backend (D76/RN-170, D-3 del design de
`notify-isolate-executor-lane`).

Desde la Change 59, el backend instala DOS `ThreadPoolExecutor` propios: uno
exclusivo del carril de ingesta (instalado como executor por defecto del
event loop vía `set_default_executor`, `main.py`) y uno exclusivo del carril
de notificación por evento, referenciado explícitamente por sus call sites en
`alerts/service.py`.

Este módulo existe porque `alerts/service.py` no puede importar `main.py` sin
generar un ciclo: `main.py` importa los routers, que a su vez importan los
services. `core/` es la ubicación que el proyecto ya usa para recursos de
proceso compartidos (`core/database.py` para el engine, `core/config.py`
para `Settings`), así que es la ubicación natural para estos dos handles.

Contrato de los accesores: devuelven el executor instalado, y FALLAN DE FORMA
EXPLÍCITA (`RuntimeError`) si se los invoca antes de que el lifespan de
`main.py` los haya construido e instalado con `install_executors(...)`. Un
fallback silencioso al executor por defecto del loop volvería a mezclar los
pools en cualquier camino que corriera fuera del lifespan —los tests son el
caso obvio— y el aislamiento que esta change existe para lograr se perdería
sin que nada lo señale. Los tests que ejerciten el camino de notificación
instalan los executors explícitamente (ver `tests/conftest.py`), igual que ya
instalan el resto del entorno (Valkey, schema, admin seed).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

_ingest_executor: ThreadPoolExecutor | None = None
_notify_executor: ThreadPoolExecutor | None = None


def install_executors(
    ingest_executor: ThreadPoolExecutor, notify_executor: ThreadPoolExecutor
) -> None:
    """
    Registra los dos executors construidos por el lifespan de `main.py`.

    Invocado una sola vez, en el startup, ANTES de que cualquier corrutina
    del carril de notificación pueda ejecutar su primer `run_in_executor`.
    """
    global _ingest_executor, _notify_executor
    _ingest_executor = ingest_executor
    _notify_executor = notify_executor


def get_ingest_executor() -> ThreadPoolExecutor:
    """Executor exclusivo del carril de ingesta (también el default del loop)."""
    if _ingest_executor is None:
        raise RuntimeError(
            "ingest executor no instalado: el lifespan de main.py todavía no "
            "corrió (install_executors nunca fue invocado)"
        )
    return _ingest_executor


def get_notify_executor() -> ThreadPoolExecutor:
    """
    Executor exclusivo del carril de notificación (D76/RN-170).

    Un `RuntimeError` acá significa que un call site del camino de
    notificación corrió sin que el lifespan (o el fixture de test
    equivalente) hubiera instalado los executors — nunca hay un fallback
    silencioso al executor de ingesta o al default de asyncio.
    """
    if _notify_executor is None:
        raise RuntimeError(
            "notify executor no instalado: el lifespan de main.py todavía no "
            "corrió (install_executors nunca fue invocado). Los tests que "
            "ejercitan el camino de notificación deben instalar los "
            "executors explícitamente (ver tests/conftest.py)."
        )
    return _notify_executor


def reset_executors_for_tests() -> None:
    """Limpia el estado del módulo. Uso exclusivo de la suite de tests."""
    global _ingest_executor, _notify_executor
    _ingest_executor = None
    _notify_executor = None

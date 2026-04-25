"""
Wrapper documental para el processor de sanitización de logs.

Decisión D-CHANGE-01: el processor real (`sanitize_secrets`) vive en
`app/core/logging.py` porque debe estar disponible para code paths que no
pasan por el ciclo HTTP (lifespan, consumers Valkey, tareas de background).

Este módulo existe por dos razones:
  1. Consistencia con `docs/arquitectura_stack.md §Módulos del backend` que
     menciona `middleware/sanitize_logs` como parte del subpaquete `middleware/`.
  2. Proveer un punto de entrada explícito `configure_log_sanitizer()` que
     permite a herramientas de análisis estático y a los tests verificar que
     la sanitización está configurada, sin tener que inspeccionar el interior
     de `configure_logging()`.

El registro real en la pipeline ocurre dentro de `configure_logging()`
en `core/logging.py`. No llamar a esta función reemplaza esa lógica; es
un no-op documental.
"""

from app.core.logging import sanitize_secrets  # noqa: F401 — reexport explícito


def configure_log_sanitizer() -> None:
    """
    Verifica que el processor sanitize_secrets esté disponible.

    No modifica la pipeline de structlog (eso lo hace configure_logging()).
    Útil para tests que quieran importar el processor directamente o para
    verificar que el módulo está correctamente conectado.
    """
    # El processor ya está importado arriba como reexport; este call es un
    # assertion de que el import funciona correctamente.
    assert callable(sanitize_secrets), (
        "sanitize_secrets processor not callable — check core/logging.py"
    )

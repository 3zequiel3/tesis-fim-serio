"""
Tests de Change 60 (`notify-accepted-at-and-test-port-isolation`, D78/RN-172,
Caso A) — grupo 6 de tasks.md.

Cubre el aislamiento del puerto de escucha del lifespan: dos pruebas con
lifespan corriendo en la misma sesión sin colisionar (6.1), la suite produce
el mismo resultado con el puerto por defecto ocupado a propósito (6.2), una
prueba que necesita un listener real obtiene un puerto efímero explícito
(6.3), y las guardas sobre producción — el default del puerto y la
invocación del lifespan no cambian (6.4).

Los tests de configuración determinada (Caso B, 6.5-6.7) viven en
`tests/core/test_notification_settings.py`, junto al resto de la suite de
`Settings` que ya cubre D43/RN-137 — es el lugar natural, y evita duplicar el
patrón `_fresh_settings`.

Se saltea si psycopg/libpq no está disponible porque `conftest.py` lo exige a
nivel de sesión (mismo criterio que el resto de la suite).
"""

from __future__ import annotations

import inspect
import socket

import pytest
from fastapi.testclient import TestClient

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from tests.conftest import _free_port


# ── 6.1 — Dos pruebas con lifespan corren en la misma sesión sin colisionar ──


def test_two_sequential_lifespans_do_not_collide_on_shared_port() -> None:
    """
    Reproduce el escenario que producía `RuntimeError: This portal is not
    running`: dos `with TestClient(app)` seguidos, en el mismo proceso de
    pytest. Antes de esta change, el segundo lifespan intentaba volver a
    ligar 8443/8444 -ya liberados por el primero, pero el modo de falla
    original ocurría entre dos tests DISTINTOS de la suite real, no acá- y
    la fixture autouse de conftest.py hace que ninguno de los dos intente
    ligar el puerto en absoluto.
    """
    from app.main import app

    with TestClient(app) as client_a:
        resp_a = client_a.get("/alerts/stream?ticket=invalid-ticket")
    with TestClient(app) as client_b:
        resp_b = client_b.get("/alerts/stream?ticket=invalid-ticket")

    assert resp_a.status_code == 401
    assert resp_b.status_code == 401


# ── 6.2 — La suite corre con el puerto por defecto ya ocupado ────────────────


def _try_occupy_port(port: int) -> socket.socket | None:
    """
    Mejor esfuerzo: ligar y retener `port` durante el test. Si el puerto YA
    está ocupado por otra cosa en este entorno -sandbox, proceso del
    laboratorio, lo que sea-, eso NO es motivo para saltear: es, si acaso,
    una reproducción todavía más fiel del escenario que este test cubre
    -"la suite corre en una máquina donde otro proceso ya está escuchando en
    el puerto por defecto"-. Sólo un sandbox que prohíbe abrir sockets TCP
    locales por completo es motivo de skip.
    """
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        blocker.bind(("0.0.0.0", port))
        blocker.listen(1)
    except PermissionError:
        blocker.close()
        pytest.skip("sandbox does not permit local TCP sockets")
    except OSError:
        # Alguien más ya tiene el puerto — exactamente la condición que este
        # test ejercita. No hay nada que retener nosotros mismos.
        blocker.close()
        return None
    return blocker


@pytest.mark.parametrize("port", [8443, 8444])
def test_lifespan_ignores_occupied_default_listener_port(port: int) -> None:
    """
    El caso exacto del defecto: el puerto por defecto del servidor mTLS
    (8443) o del bootstrap (8444, task 3.4) YA está ocupado por otro proceso
    -por este test, o por lo que sea que ya lo tenga en este entorno-, y la
    suite debe producir el mismo resultado que con el puerto libre. Antes de
    esta change, esto era precisamente lo que el arnés de laboratorio evitaba
    bajando el backend real antes de correr
    (`scripts/correr_suites_candidato.sh:83-91`).
    """
    from app.main import app

    blocker = _try_occupy_port(port)
    try:
        with TestClient(app) as client:
            resp = client.get("/alerts/stream?ticket=invalid-ticket")
        assert resp.status_code == 401
    finally:
        if blocker is not None:
            blocker.close()


# ── 6.3 — Una prueba que necesita un listener real obtiene un puerto efímero ─


def test_free_port_helper_yields_bindable_ephemeral_port_not_default() -> None:
    """
    `_free_port()` (promovido a conftest.py, task 3.1) es el mecanismo que
    usan `test_mtls_transport.py` y `test_agent_cert_renewal_e2e.py` para
    obtener un listener real fuera del lifespan, con `port=` explícito — la
    prueba de handshake TLS completo vive ahí; esta pin la propiedad
    estructural: el puerto que entrega el sistema operativo nunca es uno de
    los dos defaults cableados, y es efectivamente bindable.
    """
    port = _free_port()

    assert port not in (8443, 8444)
    assert port > 0

    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))  # no debe levantar OSError


# ── 6.4 — Guardas sobre producción ───────────────────────────────────────────


def test_guard_mtls_server_default_port_unchanged() -> None:
    """
    Falla si alguien "arregla" la suite moviendo el default de producción de
    `start_mtls_server` en lugar de arreglar el arnés (D-5 del design,
    obligación dura del spec).
    """
    from app.core.pki import start_mtls_server

    sig = inspect.signature(start_mtls_server)
    assert sig.parameters["port"].default == 8443
    assert sig.parameters["host"].default == "0.0.0.0"


def test_guard_bootstrap_server_default_port_unchanged() -> None:
    """Misma guarda que la anterior, para el listener de bootstrap (8444)."""
    from app.core.pki import start_bootstrap_server

    sig = inspect.signature(start_bootstrap_server)
    assert sig.parameters["port"].default == 8444
    assert sig.parameters["host"].default == "0.0.0.0"


def test_guard_lifespan_invocation_does_not_pass_port() -> None:
    """
    Falla si alguien empieza a pasar `port=` desde el lifespan real
    (`app/main.py:93-103`) — eso convertiría el arreglo del arnés en un
    cambio de comportamiento de producción, exactamente lo que D-5 del
    design prohíbe.
    """
    from app import main as main_module

    source = inspect.getsource(main_module.lifespan)
    for call_name in ("start_mtls_server(", "start_bootstrap_server("):
        start = source.index(call_name)
        end = source.index(")", start)
        call_block = source[start:end]
        assert "port=" not in call_block, (
            f"{call_name} ahora pasa port= desde el lifespan real — eso "
            "mueve el default de producción para satisfacer el arnés, que "
            "es exactamente lo que esta change existe para no hacer"
        )

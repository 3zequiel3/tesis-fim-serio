"""
Fixtures compartidas para la suite de tests del backend FIM.

El fixture `client` monta la app FastAPI en memoria usando httpx + ASGI
transport — no levanta un servidor HTTP real, no necesita DB ni Valkey.
El lifespan se ejecuta de todos modos (SQLModel.metadata.create_all es
no-op sin modelos; seed_admin retorna temprano sin tabla users).

pytest-asyncio en modo `asyncio_mode = "auto"` (configurado en pyproject.toml)
permite decorar tests async sin el decorador @pytest.mark.asyncio en cada uno.
"""

import os

import pytest
from httpx import ASGITransport
from httpx import AsyncClient

# Inyectar variables de entorno mínimas ANTES de importar la app,
# porque config.py instancia Settings() al import-time.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")


@pytest.fixture
async def client():
    """
    httpx.AsyncClient montado sobre la app ASGI en memoria.

    Ejecuta el lifespan completo (startup + shutdown) en cada test que
    use este fixture, garantizando estado limpio.
    """
    # Import dentro del fixture para que los os.environ.setdefault de arriba
    # ya estén activos cuando Settings() se instancie.
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

"""
Engine SQLModel y Unit of Work por request.

`get_session` es una dependency FastAPI: yield-ea una Session y la cierra
al salir del context manager de SQLModel (incluyendo rollback automático si
el endpoint levanta excepción no capturada).

`engine` se crea con pool_pre_ping=True para detectar conexiones muertas
antes de usarlas, evitando errores silenciosos si PostgreSQL recicló la
conexión.
"""

from collections.abc import Generator

from sqlmodel import Session
from sqlmodel import create_engine

from app.core.config import settings

engine = create_engine(
    str(settings.database_url),
    pool_pre_ping=True,
    echo=False,
)


def get_session() -> Generator[Session, None, None]:
    """
    Dependency FastAPI que provee una sesión SQLModel por request.

    Uso::

        @app.get("/items")
        def list_items(session: Session = Depends(get_session)):
            ...
    """
    with Session(engine) as session:
        yield session

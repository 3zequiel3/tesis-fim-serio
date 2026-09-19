"""
Engine SQLModel y Unit of Work por request.

`get_session` es una dependency FastAPI: yield-ea una Session y la cierra
al salir del context manager de SQLModel (incluyendo rollback automático si
el endpoint levanta excepción no capturada).

`engine` se crea con pool_pre_ping=True para detectar conexiones muertas
antes de usarlas, evitando errores silenciosos si PostgreSQL recicló la
conexión.

Dimensionamiento del pool (D75/RN-169). Antes este módulo no pasaba
`pool_size` ni `max_overflow` a `create_engine`, así que regían los defaults
de SQLAlchemy (`pool_size=5` + `max_overflow=10` = 15 conexiones, verificado
en ejecución como `QueuePool size=5 overflow_max=10`) contra un executor por
defecto de asyncio de `min(32, cpu_count + 4)` = 16 hilos en el anfitrión de
medición — una combinación capaz de agotar el pool por construcción en cuanto
el carril de ingesta empezara a usar el executor. `pool_size` y
`max_overflow` pasan a ser explícitos y configurables vía `Settings`
(`db_pool_size`, `db_max_overflow`), con el número de hilos del executor
acotado por esa misma capacidad (ver `app/main.py` y el
`model_validator` de `Settings`).

`pool_timeout=30` se explicita aunque sea el default de SQLAlchemy: escribirlo
deja claro en el código que el agotamiento del pool falla de forma VISIBLE
con un `TimeoutError`, en vez de colgarse en silencio. Convertirlo en un knob
sería un parámetro nuevo que D75 no enumera — una suposición nueva que
iría al appendix de decisiones antes que acá.
"""

from collections.abc import Generator

from sqlmodel import Session
from sqlmodel import create_engine

from app.core.config import settings

engine = create_engine(
    str(settings.database_url),
    pool_pre_ping=True,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=30,
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

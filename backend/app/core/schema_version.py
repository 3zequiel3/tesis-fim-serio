"""
Expected database schema version and startup guard (D84/RN-178, Change 66).

`EXPECTED_SCHEMA_VERSION` is the number of the highest migration in
`backend/db/migrations/`. It lives here, inside `app/`, because the backend image copies
only `app/` (`backend/Dockerfile`): the migration files do not travel in the image, so the
version the code expects has to travel as code.

`tests/test_schema_version.py` fails when this constant differs from the highest migration
in the tree, which keeps both in sync. When you add a migration `NNN_*.sql`, raise this
constant to `NNN` in the same commit.

`check_schema_version(engine)` runs at the very start of the lifespan, before `create_all`:
it reads `max(version)` from `schema_migrations` and aborts the startup when the registry
does not exist or is behind. A registry ahead of the code does not abort (a rollback to an
older image must keep working). Install and upgrade procedure: `python3 scripts/migrar.py`.
"""

from typing import Final

import sqlalchemy
from sqlalchemy.engine import Engine

from app.core.logging import log

EXPECTED_SCHEMA_VERSION: Final[int] = 23


class SchemaVersionError(RuntimeError):
    """The database schema registry is missing or behind the version this code expects."""


def check_schema_version(engine: Engine) -> int:
    """Return the highest registered schema version, or raise `SchemaVersionError`."""
    found_version: int | None = None
    with engine.connect() as conn:
        # to_regclass avoids provoking an UndefinedTable error inside the connection.
        registry = conn.execute(
            sqlalchemy.text("SELECT to_regclass('public.schema_migrations')")
        ).scalar()
        if registry is not None:
            found_version = conn.execute(
                sqlalchemy.text("SELECT max(version) FROM schema_migrations")
            ).scalar()

    if found_version is None or found_version < EXPECTED_SCHEMA_VERSION:
        log.error(
            "backend.schema_outdated",
            expected_version=EXPECTED_SCHEMA_VERSION,
            found_version=found_version,
            remedy="python3 scripts/migrar.py",
        )
        raise SchemaVersionError(
            f"database schema is outdated: found version {found_version}, expected "
            f"{EXPECTED_SCHEMA_VERSION}; run `python3 scripts/migrar.py` "
            "(an existing database without a registry needs `--marcar-hasta N`)"
        )

    log.info(
        "backend.schema_version",
        expected_version=EXPECTED_SCHEMA_VERSION,
        found_version=found_version,
    )
    return found_version

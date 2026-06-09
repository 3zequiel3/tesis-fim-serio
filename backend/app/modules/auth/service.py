import sqlalchemy
from argon2 import PasswordHasher
from sqlmodel import Session, select

from app.core.database import engine
from app.core.logging import log

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def seed_admin() -> None:
    inspector = sqlalchemy.inspect(engine)
    if not inspector.has_table("users"):
        log.info("seed_admin.skipped", reason="users_table_not_yet_created")
        return

    from app.core.config import settings
    from app.modules.auth.models import User

    with Session(engine) as session:
        existing = session.exec(select(User)).first()
        if existing:
            return
        admin = User(
            username=settings.admin_username,
            password_hash=_ph.hash(settings.admin_password.get_secret_value()),
            role="admin",
            must_change_password=True,
        )
        session.add(admin)
        session.commit()
        log.info("seed_admin.created", username=settings.admin_username)

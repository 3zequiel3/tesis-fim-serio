import sqlalchemy
from sqlmodel import Session, select

from app.core.database import engine
from app.core.logging import log
from app.core.security import hash_password


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
            password_hash=hash_password(settings.admin_password.get_secret_value()),
            role="admin",
            is_active=True,
            must_change_password=False,
        )
        session.add(admin)
        session.commit()
        log.info("seed_admin.created", username=settings.admin_username)

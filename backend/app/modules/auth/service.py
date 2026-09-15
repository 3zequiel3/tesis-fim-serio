import sqlalchemy
from sqlmodel import Session, select

from app.core.database import engine
from app.core.logging import log
from app.core.security import hash_password, verify_password


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
            # D56/RN-150 finding 14.4: a pre-existing DB (e.g. a server that
            # already booted once) means ADMIN_PASSWORD from this boot's
            # .env was never applied — silently. Warn instead of staying
            # quiet, without touching the stored hash: only
            # `app.modules.auth.cli reset-admin-password` may change it.
            env_password = settings.admin_password.get_secret_value()
            if env_password:
                existing_admin = session.exec(
                    select(User).where(User.username == settings.admin_username)
                ).first()
                if existing_admin and not verify_password(env_password, existing_admin.password_hash):
                    log.warning(
                        "seed_admin.env_password_ignored",
                        username=settings.admin_username,
                    )
            return
        admin = User(
            username=settings.admin_username,
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password.get_secret_value()),
            role="admin",
            is_active=True,
            must_change_password=True,  # RN-62, RN-100/W20
        )
        session.add(admin)
        session.commit()
        log.info("seed_admin.created", username=settings.admin_username)

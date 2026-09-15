"""D56/RN-150 finding 14.4 — `python -m app.modules.auth.cli reset-admin-password`."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.core.security import hash_password, verify_password
from app.modules.audit.models import AuditLog
from app.modules.auth.cli import ACTION_RESET_ADMIN_PASSWORD, main, reset_admin_password
from app.modules.auth.models import User


def _set_admin_state(*, password_hash: str, must_change_password: bool = False) -> int:
    with Session(engine) as session:
        admin = session.exec(select(User).where(User.username == settings.admin_username)).first()
        assert admin is not None
        admin.password_hash = password_hash
        admin.must_change_password = must_change_password
        session.add(admin)
        session.commit()
        session.refresh(admin)
        return admin.id  # type: ignore[return-value]


def test_reset_admin_password_applies_env_password_and_forces_change() -> None:
    _set_admin_state(password_hash=hash_password("some-stale-hash-value"))

    exit_code = main(["reset-admin-password"])
    assert exit_code == 0

    with Session(engine) as session:
        admin = session.exec(select(User).where(User.username == settings.admin_username)).first()
    assert admin is not None
    assert verify_password(settings.admin_password.get_secret_value(), admin.password_hash)
    assert admin.must_change_password is True


def test_reset_admin_password_writes_audit_log() -> None:
    admin_id = _set_admin_state(password_hash=hash_password("some-stale-hash-value"))

    exit_code = reset_admin_password()
    assert exit_code == 0

    with Session(engine) as session:
        entries = session.exec(
            select(AuditLog).where(AuditLog.action == ACTION_RESET_ADMIN_PASSWORD)
        ).all()
    assert len(entries) == 1
    assert entries[0].user_id == admin_id
    assert entries[0].detail == f"username={settings.admin_username}"


def test_reset_admin_password_missing_env_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "admin_password", SecretStr(""))

    exit_code = main(["reset-admin-password"])
    assert exit_code == 1
    assert "ADMIN_PASSWORD" in capsys.readouterr().err


def test_reset_admin_password_no_matching_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "admin_username", "someone-else-entirely")

    exit_code = main(["reset-admin-password"])
    assert exit_code == 1
    assert "someone-else-entirely" in capsys.readouterr().err


def test_reset_admin_password_idempotent_to_run_twice() -> None:
    assert main(["reset-admin-password"]) == 0
    assert main(["reset-admin-password"]) == 0

    with Session(engine) as session:
        entries = session.exec(
            select(AuditLog).where(AuditLog.action == ACTION_RESET_ADMIN_PASSWORD)
        ).all()
    assert len(entries) == 2

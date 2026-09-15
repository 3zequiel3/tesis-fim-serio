"""Server-side admin password reset CLI (D56/RN-150 finding 14.4).

Usage: `python -m app.modules.auth.cli reset-admin-password`

`seed_admin()` only creates the admin user once — on every later boot, if
`ADMIN_PASSWORD` in `.env` does not match the stored hash, it now logs
`seed_admin.env_password_ignored` (app/modules/auth/service.py) but leaves
the password untouched, since applying an environment value silently on
every boot would let a stale/leaked `.env` value overwrite an
operator-chosen password without consent. This CLI is the supported,
explicit way to apply the current `ADMIN_PASSWORD` when that is actually
what the operator wants: it hashes it with the same Argon2id function
`seed_admin()` uses, forces `must_change_password=True` (RN-62, RN-100/W20 —
the same flag a first `seed_admin()` sets), and records the change in
`audit_log` (RN-94) with the admin acting on itself, since a server
operator with shell access — not a browser session — performs this action.
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, select

from app.core.audit import write_audit_log
from app.core.config import settings
from app.core.database import engine
from app.core.logging import log
from app.core.security import hash_password
from app.modules.auth.models import User

ACTION_RESET_ADMIN_PASSWORD = "reset_admin_password_cli"


def reset_admin_password() -> int:
    """Applies the current `ADMIN_PASSWORD` to `settings.admin_username`,
    forces a password change on next login, and audits it. Returns a process
    exit code (0 on success, non-zero if there is nothing to apply)."""
    admin_password = settings.admin_password.get_secret_value()
    if not admin_password:
        print(
            "cli.reset-admin-password: ADMIN_PASSWORD is not set in the environment",
            file=sys.stderr,
        )
        return 1

    with Session(engine) as session:
        admin = session.exec(
            select(User).where(User.username == settings.admin_username)
        ).first()
        if admin is None:
            print(
                f"cli.reset-admin-password: no user named {settings.admin_username!r} found",
                file=sys.stderr,
            )
            return 1

        admin.password_hash = hash_password(admin_password)
        admin.must_change_password = True  # RN-62, RN-100/W20
        session.add(admin)
        session.commit()
        session.refresh(admin)

        write_audit_log(
            session,
            ACTION_RESET_ADMIN_PASSWORD,
            admin.id,  # type: ignore[arg-type]
            extra=f"username={admin.username}",
        )

    log.info("reset_admin_password_cli.applied", username=settings.admin_username)
    print(
        f"cli.reset-admin-password: password reset for {settings.admin_username!r}; "
        "must_change_password=True"
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.modules.auth.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset-admin-password")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "reset-admin-password":
        return reset_admin_password()
    return 1  # pragma: no cover — argparse enforces the choice set above


if __name__ == "__main__":
    sys.exit(main())

from sqlmodel import Session

from app.modules.audit.models import AuditLog


def write_audit_log(
    session: Session,
    action: str,
    user_id: int | None,
    extra: str | None = None,
) -> None:
    """Write one audit_log entry.

    `user_id=None` records a system-originated action (D67/RN-161) — no
    human operator behind it, e.g. an agent renewing its own certificate
    over mTLS. Callers passing `None` SHALL identify the actor in `extra`;
    an entry with neither is invalid by convention.
    """
    session.add(AuditLog(user_id=user_id, action=action, detail=extra))
    session.commit()

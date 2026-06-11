from sqlmodel import Session

from app.modules.audit.models import AuditLog


def write_audit_log(
    session: Session,
    action: str,
    user_id: int,
    extra: str | None = None,
) -> None:
    session.add(AuditLog(user_id=user_id, action=action, detail=extra))
    session.commit()

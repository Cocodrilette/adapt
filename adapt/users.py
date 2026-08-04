"""User account lifecycle helpers."""

from sqlmodel import Session, select

from .storage import DBSession, User


def set_user_active(db: Session, user: User, is_active: bool) -> int:
    """Set a user's active status and revoke sessions on deactivation.

    Returns the number of browser sessions that were revoked.
    """
    revoked_sessions = 0
    if not is_active:
        sessions = db.exec(
            select(DBSession).where(DBSession.user_id == user.id)
        ).all()
        revoked_sessions = len(sessions)
        for session in sessions:
            db.delete(session)

    user.is_active = is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return revoked_sessions

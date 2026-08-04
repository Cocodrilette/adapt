from pathlib import Path
import logging

from sqlmodel import Session, select

from ...auth.password import update_password
from ...config import AdaptConfig
from ...storage import User, init_database
from ..passwords import resolve_password

logger = logging.getLogger(__name__)


def run_change_password(
    root: Path,
    username: str,
    password: str | None,
    password_confirm: str | None = None,
    allow_weak_password: bool = False,
) -> None:
    """Change a user password and revoke all browser sessions."""
    config = AdaptConfig(root=root)
    engine = init_database(config.db_path)

    password = resolve_password(
        username=username,
        password=password,
        password_confirm=password_confirm,
        allow_weak_password=allow_weak_password,
    )
    if password is None:
        logger.warning("Aborted password change for %s due to password validation", username)
        return

    with Session(engine) as db:
        user = db.exec(select(User).where(User.username == username)).first()
        if not user:
            logger.warning("User '%s' not found", username)
            print(f"User '{username}' not found")
            return
        update_password(db, user, password)

    print(f"Changed password for user '{username}' and revoked all browser sessions")

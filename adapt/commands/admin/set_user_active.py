from pathlib import Path
import logging

from sqlmodel import Session, select

from ...config import AdaptConfig
from ...storage import User, init_database
from ...users import set_user_active

logger = logging.getLogger(__name__)


def run_set_user_active(root: Path, username: str, is_active: bool) -> None:
    """Activate or deactivate a user account by username."""
    config = AdaptConfig(root=root)
    engine = init_database(config.db_path)

    with Session(engine) as db:
        user = db.exec(select(User).where(User.username == username)).first()
        if not user:
            logger.warning("User '%s' not found", username)
            print(f"User '{username}' not found")
            return

        revoked_sessions = set_user_active(db, user, is_active)

    status = "Activated" if is_active else "Deactivated"
    logger.info("%s user '%s'", status, username)
    if is_active:
        print(f"Activated user '{username}'")
    else:
        print(f"Deactivated user '{username}' and revoked {revoked_sessions} browser session(s)")

from pathlib import Path
import logging

from sqlmodel import Session, select

from ...auth.password import hash_password
from ...config import AdaptConfig
from ...storage import User, init_database
from ..passwords import resolve_password

logger = logging.getLogger(__name__)


def run_create_user(
    root: Path,
    username: str,
    password: str | None,
    password_confirm: str | None = None,
    is_superuser: bool = False,
    allow_weak_password: bool = False,
) -> None:
    """Create a user account."""
    config = AdaptConfig(root=root)
    engine = init_database(config.db_path)

    password = resolve_password(
        username=username,
        password=password,
        password_confirm=password_confirm,
        allow_weak_password=allow_weak_password,
    )
    if password is None:
        logger.warning("Aborted user creation for %s due to password validation", username)
        return

    with Session(engine) as db:
        existing = db.exec(select(User).where(User.username == username)).first()
        if existing:
            logger.warning("User '%s' already exists", username)
            print(f"User '{username}' already exists")
            return

        user = User(
            username=username,
            password_hash=hash_password(password),
            is_active=True,
            is_superuser=is_superuser,
        )
        db.add(user)
        db.commit()

    role = "superuser" if is_superuser else "user"
    logger.info("Created %s '%s'", role, username)
    print(f"Created {role} '{username}'")

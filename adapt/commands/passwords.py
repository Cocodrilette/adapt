from __future__ import annotations

import getpass
import logging
import re
import sys

logger = logging.getLogger(__name__)

_COMMON_PASSWORDS = {
    "123456",
    "12345678",
    "123456789",
    "admin",
    "admin123",
    "changeme",
    "letmein",
    "password",
    "password1",
    "password123",
    "qwerty",
    "welcome",
}
_COMMON_SEQUENCES = ("12345", "54321", "abcdef", "fedcba", "qwerty", "asdf", "zxcv")


def is_weak_password(password: str, username: str | None = None) -> bool:
    """Return True when the password is easily guessed by common heuristics."""
    normalized = password.casefold()
    compact = re.sub(r"[^a-z0-9]", "", normalized)

    if len(password) < 10:
        return True
    if normalized in _COMMON_PASSWORDS or compact in _COMMON_PASSWORDS:
        return True
    if username and username.casefold() in normalized:
        return True
    if len(set(normalized)) <= 2:
        return True
    if any(sequence in compact for sequence in _COMMON_SEQUENCES):
        return True

    classes = sum(
        (
            any(ch.islower() for ch in password),
            any(ch.isupper() for ch in password),
            any(ch.isdigit() for ch in password),
            any(not ch.isalnum() for ch in password),
        )
    )
    if len(password) >= 12 and classes >= 3:
        return False
    return not (len(password) >= 10 and classes == 4)


def resolve_password(
    *,
    username: str,
    password: str | None,
    password_confirm: str | None = None,
    allow_weak_password: bool = False,
) -> str | None:
    """Collect, confirm, and validate a password for CLI user creation."""
    if password is None:
        return _prompt_for_password(username=username)

    if password_confirm is None:
        if not sys.stdin.isatty():
            print("Password confirmation required. Re-run with --password-confirm for non-interactive use.")
            return None
        password_confirm = getpass.getpass("Confirm password: ")

    if password != password_confirm:
        logger.warning("Password confirmation mismatch for user %s", username)
        print("Passwords do not match.")
        return None

    if is_weak_password(password, username=username):
        if allow_weak_password:
            return password
        if not sys.stdin.isatty():
            print(
                "This password appears weak and may be easily guessed. "
                "Choose a stronger password or re-run with --allow-weak-password."
            )
            return None
        if not _confirm_weak_password():
            print("Password not accepted.")
            return None

    return password


def _prompt_for_password(*, username: str) -> str:
    while True:
        password = getpass.getpass("Password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            logger.warning("Password confirmation mismatch for user %s", username)
            print("Passwords do not match. Please try again.")
            continue
        if is_weak_password(password, username=username) and not _confirm_weak_password():
            print("Please choose a stronger password.")
            continue
        return password


def _confirm_weak_password() -> bool:
    while True:
        answer = input("This password appears weak and may be easily guessed. Use it anyway? [y/N]: ")
        normalized = answer.strip().casefold()
        if normalized in {"y", "yes"}:
            return True
        if normalized in {"", "n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")

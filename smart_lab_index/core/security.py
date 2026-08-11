"""Local operator credential creation and validation."""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

OPERATOR_USERNAME = "operator"
MIN_OPERATOR_TOKEN_LENGTH = 32
MAX_OPERATOR_TOKEN_LENGTH = 256


class CredentialError(ValueError):
    pass


def create_operator_token(path: str | Path, *, force: bool = False) -> str:
    """Create an owner-only token file and return the one-time token value."""
    target = _absolute(path)
    parent_existed = target.parent.exists()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not parent_existed:
        os.chmod(target.parent, 0o700)
    if os.path.lexists(target) and not force:
        raise CredentialError(f"operator token already exists: {target}")
    if target.is_symlink():
        raise CredentialError("operator token path must not be a symbolic link")
    if target.exists() and target.stat().st_nlink != 1:
        raise CredentialError("operator token must not have hard links")
    token = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    if not force:
        flags |= os.O_EXCL
    descriptor = os.open(target, flags, 0o600)
    try:
        os.write(descriptor, f"{token}\n".encode("ascii"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(target, 0o600)
    return token


def load_operator_token(path: str | Path) -> str:
    """Load a regular, private token file without following a final symlink."""
    target = _absolute(path)
    try:
        value = target.lstat()
    except OSError as exc:
        raise CredentialError(f"operator token cannot be opened: {target}") from exc
    if stat.S_ISLNK(value.st_mode):
        raise CredentialError("operator token path must not be a symbolic link")
    if not stat.S_ISREG(value.st_mode):
        raise CredentialError("operator token must be a regular file")
    if value.st_nlink != 1:
        raise CredentialError("operator token must not have hard links")
    if os.name == "posix":
        if value.st_mode & 0o077:
            raise CredentialError("operator token permissions must be 0600 or stricter")
        if hasattr(os, "geteuid") and value.st_uid != os.geteuid():
            raise CredentialError("operator token must be owned by the service account")
    try:
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (value.st_dev, value.st_ino):
                raise CredentialError("operator token changed while it was opened")
            content = os.read(descriptor, MAX_OPERATOR_TOKEN_LENGTH + 2)
        finally:
            os.close(descriptor)
        token = content.decode("ascii").strip()
    except CredentialError:
        raise
    except (OSError, UnicodeError) as exc:
        raise CredentialError(
            "operator token must contain an ASCII access key"
        ) from exc
    validate_operator_token(token)
    return token


def validate_operator_token(token: str) -> None:
    if not isinstance(token, str):
        raise CredentialError("operator token must be text")
    if not MIN_OPERATOR_TOKEN_LENGTH <= len(token) <= MAX_OPERATOR_TOKEN_LENGTH:
        raise CredentialError(
            f"operator token must contain {MIN_OPERATOR_TOKEN_LENGTH} to "
            f"{MAX_OPERATOR_TOKEN_LENGTH} characters"
        )
    if any(
        character.isspace() or ord(character) < 33 or ord(character) > 126
        for character in token
    ):
        raise CredentialError("operator token contains invalid characters")


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))

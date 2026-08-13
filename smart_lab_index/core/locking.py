"""Cross-process ownership lease for one writable LabOverlay database."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import IO


class DatabaseBusyError(RuntimeError):
    pass


class DatabaseLease:
    """Hold a non-blocking OS lock while an indexing application owns a database."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self.path: Path | None = None
        self._stream: IO[bytes] | None = None

    def acquire(self) -> DatabaseLease:
        if self.database == ":memory:" or self._stream is not None:
            return self
        requested = Path(os.path.abspath(os.fspath(Path(self.database).expanduser())))
        if os.path.lexists(requested) and requested.is_symlink():
            raise DatabaseBusyError("database path must not be a symbolic link")
        database = requested.parent.resolve() / requested.name
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = Path(f"{database}.lock")
        descriptor = os.open(
            self.path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        opened = os.fstat(descriptor)
        if opened.st_nlink != 1:
            os.close(descriptor)
            raise DatabaseBusyError("database lease file must not have hard links")
        os.chmod(self.path, 0o600)
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            _lock(stream)
        except OSError as exc:
            stream.close()
            raise DatabaseBusyError(
                f"another LabOverlay process owns this database: {database}"
            ) from exc
        self._stream = stream
        metadata = json.dumps(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=True,
            sort_keys=True,
        ).encode("ascii")
        stream.seek(0)
        stream.truncate()
        stream.write(metadata)
        stream.flush()
        os.fsync(stream.fileno())
        return self

    def close(self) -> None:
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        try:
            _unlock(stream)
        finally:
            stream.close()

    def __enter__(self) -> DatabaseLease:  # noqa: PYI034 - Python 3.10 lacks Self
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _lock(stream: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        if not stream.read(1):
            stream.seek(0)
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(stream: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

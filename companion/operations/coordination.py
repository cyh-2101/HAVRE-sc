"""Cross-process serialization for backups and owner erasure."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os


BACKUP_ERASURE_ADVISORY_LOCK = 5206538407623921665


@contextmanager
def backup_erasure_lock(connection):
    connection.execute(
        "SELECT pg_advisory_lock(%s)",
        (BACKUP_ERASURE_ADVISORY_LOCK,),
    )
    try:
        yield
    finally:
        connection.execute(
            "SELECT pg_advisory_unlock(%s)",
            (BACKUP_ERASURE_ADVISORY_LOCK,),
        )


@contextmanager
def local_erasure_lock(ledger_path: Path):
    """Cross-process host lock shared by backup, restore replay, and erasure."""

    path = ledger_path.resolve().with_suffix(ledger_path.suffix + ".coordination.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o600)
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

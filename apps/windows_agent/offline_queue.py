"""DPAPI-protected bounded queue for already-minimized signed drafts."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import threading
from typing import Literal, Protocol
from uuid import uuid4

if os.name == "nt":
    import msvcrt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from companion.hashing import canonical_json
from companion.life_context import ContextObservationDraft, ContextSourceHealthDraft


_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


class QueueProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(value: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class WindowsDPAPIProtector:
    CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("DPAPI queue protection is supported only on Windows")
        self.crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def protect(self, value: bytes) -> bytes:
        source, source_buffer = _blob(value)
        output = _DataBlob()
        if not self.crypt32.CryptProtectData(
            ctypes.byref(source), None, None, None, None,
            self.CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
        ):
            raise OSError(ctypes.get_last_error(), "DPAPI protect failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self.kernel32.LocalFree(output.pbData)

    def unprotect(self, value: bytes) -> bytes:
        source, source_buffer = _blob(value)
        output = _DataBlob()
        if not self.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None,
            self.CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
        ):
            raise OSError(ctypes.get_last_error(), "DPAPI unprotect failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self.kernel32.LocalFree(output.pbData)


def write_dpapi_secret(path: Path, secret: bytes) -> None:
    if len(secret) < 32:
        raise ValueError("device signing secret must contain at least 32 bytes")
    protector = WindowsDPAPIProtector()
    encoded = base64.b64encode(protector.protect(secret))
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, destination)


def read_dpapi_secret(path: Path) -> bytes:
    encrypted = base64.b64decode(path.resolve().read_bytes(), validate=True)
    secret = WindowsDPAPIProtector().unprotect(encrypted)
    if len(secret) < 32:
        raise ValueError("protected device signing secret is invalid")
    return secret

class QueuedDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    queue_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sequence: int = Field(gt=0)
    kind: Literal["observation", "health"]
    enqueued_at: datetime
    expires_at: datetime
    payload: dict[str, object]

    @field_validator("enqueued_at", "expires_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("queue timestamps must be timezone-aware")
        return value.astimezone(UTC)


class ProtectedOfflineQueue:
    def __init__(self, *, path: Path, protector: QueueProtector | None = None) -> None:
        self.path = path.resolve()
        self.protector = protector or WindowsDPAPIProtector()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with _PROCESS_LOCKS_GUARD:
            self.process_lock = _PROCESS_LOCKS.setdefault(
                str(self.lock_path).casefold(), threading.RLock()
            )

    @contextmanager
    def _locked(self):
        if os.name != "nt":
            raise RuntimeError("protected queue locking requires Windows")
        with self.process_lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+b") as handle:
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def enqueue(
        self, *, kind: Literal["observation", "health"],
        draft: ContextObservationDraft | ContextSourceHealthDraft,
        max_age_seconds: int, max_items: int = 100,
    ) -> QueuedDraft:
        if max_age_seconds <= 0:
            raise ValueError("consent does not permit normalized offline buffering")
        with self._locked():
            now = datetime.now(UTC)
            items = list(self._load_unlocked(as_of=now))
            if len(items) >= max_items:
                raise OverflowError("protected context queue reached its bounded capacity")
            item = QueuedDraft(
                queue_id=uuid4().hex,
                sequence=(0 if not items else max(item.sequence for item in items)) + 1,
                kind=kind,
                enqueued_at=now,
                expires_at=now + timedelta(seconds=max_age_seconds),
                payload=draft.model_dump(mode="json"),
            )
            items.append(item)
            self._write_unlocked(tuple(items))
            return item

    def load(self, *, as_of: datetime | None = None) -> tuple[QueuedDraft, ...]:
        with self._locked():
            return self._load_unlocked(as_of=as_of)

    def _load_unlocked(
        self, *, as_of: datetime | None = None
    ) -> tuple[QueuedDraft, ...]:
        now = (as_of or datetime.now(UTC)).astimezone(UTC)
        if not self.path.exists():
            return ()
        encrypted = base64.b64decode(self.path.read_bytes(), validate=True)
        payload = json.loads(self.protector.unprotect(encrypted).decode("utf-8"))
        items = tuple(QueuedDraft.model_validate(item) for item in payload)
        current = tuple(item for item in items if item.expires_at > now)
        if current != items:
            self._write_unlocked(current)
        return tuple(sorted(current, key=lambda item: item.sequence))

    def remove(self, queue_id: str) -> None:
        with self._locked():
            items = tuple(
                item for item in self._load_unlocked() if item.queue_id != queue_id
            )
            self._write_unlocked(items)

    def prune_expired(self) -> int:
        with self._locked():
            before = len(self._load_unlocked(as_of=datetime.min.replace(tzinfo=UTC)))
            after = len(self._load_unlocked())
            return before - after

    def erase(self) -> None:
        with self._locked():
            self._erase_unlocked()

    def _erase_unlocked(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def _write_unlocked(self, items: tuple[QueuedDraft, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not items:
            self._erase_unlocked()
            return
        plaintext = canonical_json([item.model_dump(mode="json") for item in items]).encode(
            "utf-8"
        )
        encoded = base64.b64encode(self.protector.protect(plaintext))
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, self.path)

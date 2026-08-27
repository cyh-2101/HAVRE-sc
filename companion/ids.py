"""Stable identifiers used by HAVRE domain contracts."""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_lock = threading.Lock()
_last_millis = 0
_sequence = 0


def uuid7() -> uuid.UUID:
    """Generate a monotonic UUIDv7 without relying on a database extension."""

    global _last_millis, _sequence
    with _lock:
        millis = int(time.time() * 1000)
        if millis == _last_millis:
            _sequence = (_sequence + 1) & 0x0FFF
            if _sequence == 0:
                while millis <= _last_millis:
                    millis = int(time.time() * 1000)
        else:
            _sequence = secrets.randbits(12)
        _last_millis = millis

        random_b = secrets.randbits(62)
        value = (millis & ((1 << 48) - 1)) << 80
        value |= 0x7 << 76
        value |= _sequence << 64
        value |= 0b10 << 62
        value |= random_b
        return uuid.UUID(int=value)


def new_trace_id() -> str:
    while True:
        value = secrets.token_hex(16)
        if value != "0" * 32:
            return value


def new_span_id() -> str:
    while True:
        value = secrets.token_hex(8)
        if value != "0" * 16:
            return value

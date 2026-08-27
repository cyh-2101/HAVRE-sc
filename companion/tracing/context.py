"""Minimal vendor-neutral W3C Trace Context implementation."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

from companion.ids import new_span_id, new_trace_id

TRACEPARENT_RE = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    parent_span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    name: str
    kind: Literal["server", "internal", "client"]
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    status: Literal["ok", "error"]
    attributes: dict[str, str | int | float | bool]


class TraceContext:
    def __init__(
        self,
        *,
        trace_id: str,
        parent_span_id: str | None,
        trace_flags: str = "01",
    ) -> None:
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.trace_flags = trace_flags
        self.spans: list[Span] = []

    @classmethod
    def from_traceparent(cls, value: str | None) -> "TraceContext":
        parsed = parse_traceparent(value) if value else None
        if parsed is None:
            return cls(trace_id=new_trace_id(), parent_span_id=None)
        trace_id, parent_span_id, trace_flags = parsed
        return cls(
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            trace_flags=trace_flags,
        )

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: Literal["server", "internal", "client"] = "internal",
        parent_span_id: str | None = None,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> Iterator[str]:
        span_id = new_span_id()
        started_at = datetime.now(UTC)
        started_ns = perf_counter_ns()
        status: Literal["ok", "error"] = "ok"
        try:
            yield span_id
        except Exception:
            status = "error"
            raise
        finally:
            ended_at = datetime.now(UTC)
            duration_ms = (perf_counter_ns() - started_ns) / 1_000_000
            self.spans.append(
                Span(
                    trace_id=self.trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id or self.parent_span_id,
                    name=name,
                    kind=kind,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=round(duration_ms, 3),
                    status=status,
                    attributes=attributes or {},
                )
            )

    def traceparent(self, span_id: str) -> str:
        return f"00-{self.trace_id}-{span_id}-{self.trace_flags}"


def parse_traceparent(value: str) -> tuple[str, str, str] | None:
    match = TRACEPARENT_RE.fullmatch(value.strip())
    if not match:
        return None
    trace_id, parent_span_id, flags = match.groups()
    if trace_id == "0" * 32 or parent_span_id == "0" * 16:
        return None
    return trace_id, parent_span_id, flags

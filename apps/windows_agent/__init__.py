"""Owner-controlled Windows ContextSource host for Stage 12A."""

from apps.windows_agent.coarse_context import (
    CoarseWindowAggregator,
    LocalActivitySample,
    elapsed_tick_seconds,
    WindowsCoarseContextAdapter,
    WindowsForegroundProbe,
)
from apps.windows_agent.offline_queue import ProtectedOfflineQueue
from apps.windows_agent.runner import WindowsAgentRunner
from apps.windows_agent.transport import WindowsAgentTransport

__all__ = [
    "CoarseWindowAggregator",
    "LocalActivitySample",
    "elapsed_tick_seconds",
    "WindowsCoarseContextAdapter",
    "WindowsForegroundProbe",
    "ProtectedOfflineQueue",
    "WindowsAgentRunner",
    "WindowsAgentTransport",
]

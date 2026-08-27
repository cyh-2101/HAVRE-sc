"""Minimum-sufficient Windows activity categorization.

Exact process identity exists only as a short-lived local variable needed to
map the foreground process into the approved coarse taxonomy. It is never part
of a model, draft, log, exception, cache, or return value.
"""

from __future__ import annotations

from collections import Counter
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import platform
import time
from typing import Callable
from uuid import UUID

from companion.ids import new_trace_id
from companion.life_context import (
    ConsentScopeRevision,
    ContextCollectionPermit,
    ContextObservationDraft,
    ContextSourceHealthDraft,
    ContextSourceCapability,
    ContextSourceDescriptor,
    DeviceActivitySummary,
    sign_observation_draft,
    sign_health_draft,
)


ADAPTER_VERSION = "windows-coarse-context-v1"


def elapsed_tick_seconds(current_tick: int, last_input_tick: int) -> int:
    """Return wrap-safe elapsed seconds for Windows 32-bit tick counters."""

    return ((int(current_tick) - int(last_input_tick)) & 0xFFFFFFFF) // 1000

_CATEGORY_BY_EXECUTABLE = {
    "code.exe": "development",
    "devenv.exe": "development",
    "idea64.exe": "development",
    "pycharm64.exe": "development",
    "rider64.exe": "development",
    "wt.exe": "development",
    "windowsterminal.exe": "development",
    "slack.exe": "communication",
    "teams.exe": "communication",
    "ms-teams.exe": "communication",
    "discord.exe": "communication",
    "outlook.exe": "communication",
    "chrome.exe": "browser",
    "firefox.exe": "browser",
    "msedge.exe": "browser",
    "brave.exe": "browser",
    "winword.exe": "office",
    "excel.exe": "office",
    "powerpnt.exe": "office",
    "onenote.exe": "office",
    "vlc.exe": "media",
    "spotify.exe": "media",
    "wmplayer.exe": "media",
    "steam.exe": "game",
    "epicgameslauncher.exe": "game",
    "explorer.exe": "system",
    "taskmgr.exe": "system",
    "searchhost.exe": "system",
    "shellexperiencehost.exe": "system",
}


@dataclass(frozen=True)
class LocalActivitySample:
    observed_at: datetime
    category: str | None
    idle: bool | None
    safe_error_category: str | None = None


class CollectionNotAuthorized(PermissionError):
    """The source must not inspect foreground state without a live permit."""


class ProbeUnavailable(RuntimeError):
    def __init__(self, safe_error_category: str) -> None:
        super().__init__(safe_error_category)
        self.safe_error_category = safe_error_category


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class WindowsForegroundProbe:
    """Reads only the transient process basename and system idle duration."""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self, *, idle_threshold_seconds: int) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("Windows coarse context is supported only on Windows")
        self.idle_threshold_seconds = idle_threshold_seconds
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        )
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel32.OpenProcess.argtypes = (
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
        )
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.user32.GetLastInputInfo.argtypes = (ctypes.POINTER(_LastInputInfo),)
        self.user32.GetLastInputInfo.restype = wintypes.BOOL
        self.kernel32.GetTickCount.restype = wintypes.DWORD

    def sample(self) -> LocalActivitySample:
        now = datetime.now(UTC)
        process_name = self._foreground_process_basename()
        idle_seconds = self._idle_seconds()
        if process_name is None:
            return LocalActivitySample(
                observed_at=now, category=None, idle=None,
                safe_error_category="foreground_unavailable",
            )
        if idle_seconds is None:
            process_name = ""
            return LocalActivitySample(
                observed_at=now, category=None, idle=None,
                safe_error_category="idle_state_unavailable",
            )
        try:
            category = _CATEGORY_BY_EXECUTABLE.get(process_name.lower(), "other")
        finally:
            process_name = ""
        return LocalActivitySample(
            observed_at=now,
            category=category,
            idle=idle_seconds >= self.idle_threshold_seconds,
        )

    def _foreground_process_basename(self) -> str | None:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return None
        handle = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value
        )
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32_768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return None
            return Path(buffer.value).name
        finally:
            self.kernel32.CloseHandle(handle)

    def _idle_seconds(self) -> int | None:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        current_tick = self.kernel32.GetTickCount()
        return elapsed_tick_seconds(current_tick, info.dwTime)


class CoarseWindowAggregator:
    def __init__(self, *, sample_interval_seconds: int, window_seconds: int) -> None:
        if window_seconds % sample_interval_seconds:
            raise ValueError("window must be divisible by sample interval")
        self.sample_interval_seconds = sample_interval_seconds
        self.window_seconds = window_seconds

    def summarize(self, samples: tuple[LocalActivitySample, ...]) -> DeviceActivitySummary:
        expected = self.window_seconds // self.sample_interval_seconds
        if len(samples) != expected:
            raise ValueError("sample count does not cover the exact bounded window")
        if any(
            item.category is None or item.idle is None or item.safe_error_category
            for item in samples
        ):
            first = next(item for item in samples if item.safe_error_category)
            raise ProbeUnavailable(first.safe_error_category or "foreground_unavailable")
        for prior, current in zip(samples, samples[1:]):
            elapsed = (current.observed_at - prior.observed_at).total_seconds()
            if not (
                self.sample_interval_seconds * 0.8
                <= elapsed
                <= self.sample_interval_seconds * 1.2
            ):
                raise ValueError("sample timestamps do not cover the bounded interval")
        covered_span = (samples[-1].observed_at - samples[0].observed_at).total_seconds()
        expected_span = self.window_seconds - self.sample_interval_seconds
        if abs(covered_span - expected_span) > self.sample_interval_seconds * 0.2:
            raise ValueError("sample timestamps do not cover the bounded interval")
        active = sum(not item.idle for item in samples) * self.sample_interval_seconds
        idle = sum(item.idle for item in samples) * self.sample_interval_seconds
        active_categories = Counter(item.category for item in samples if not item.idle)
        dominant = (
            sorted(active_categories.items(), key=lambda item: (-item[1], item[0]))[0][0]
            if active_categories
            else "unknown"
        )
        state = "active" if active > idle else "idle" if idle > active else "unknown"
        return DeviceActivitySummary(
            dominant_category=dominant,
            activity_state=state,
            active_seconds=active,
            idle_seconds=idle,
            sample_count=len(samples),
            window_seconds=self.window_seconds,
        )


class WindowsCoarseContextAdapter:
    def __init__(
        self,
        *,
        source: ContextSourceDescriptor,
        capability: ContextSourceCapability,
        consent: ConsentScopeRevision,
        signing_secret: bytes,
        probe_factory: Callable[[int], WindowsForegroundProbe] | None = None,
        authorization_resolver: Callable[[], ContextCollectionPermit] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if source.source_kind != "windows" or source.adapter_version != ADAPTER_VERSION:
            raise ValueError("Windows adapter requires the exact source descriptor")
        if capability.source_instance_id != source.source_instance_id:
            raise ValueError("capability/source mismatch")
        if consent.source_instance_id != source.source_instance_id:
            raise ValueError("consent/source mismatch")
        self.source = source
        self.capability = capability
        self.consent = consent
        self.signing_secret = signing_secret
        self.probe_factory = probe_factory or (
            lambda threshold: WindowsForegroundProbe(idle_threshold_seconds=threshold)
        )
        self.authorization_resolver = authorization_resolver
        self.sleep_fn = sleep_fn
        self.clock = clock

    def _require_live_authorization(self, *, at: datetime) -> None:
        if self.authorization_resolver is None:
            raise CollectionNotAuthorized("a live Core authorization resolver is required")
        permit = self.authorization_resolver()
        if (
            permit.source.content_hash != self.source.content_hash
            or permit.capability.content_hash != self.capability.content_hash
            or permit.consent.content_hash != self.consent.content_hash
            or not (permit.issued_at <= at < permit.valid_until)
        ):
            raise CollectionNotAuthorized("current source/capability/consent is not active")

    def collect_window(self) -> ContextObservationDraft:
        policy = self.consent.sampling_policy
        start = self.clock()
        self._require_live_authorization(at=start)
        probe = self.probe_factory(policy.idle_threshold_seconds)
        count = policy.summary_window_seconds // policy.sample_interval_seconds
        samples: list[LocalActivitySample] = []
        for _ in range(count):
            self.sleep_fn(policy.sample_interval_seconds)
            self._require_live_authorization(at=self.clock())
            samples.append(probe.sample())
        observed_at = self.clock()
        end = start + timedelta(seconds=policy.summary_window_seconds)
        if observed_at < end:
            raise ProbeUnavailable("foreground_unavailable")
        summary = CoarseWindowAggregator(
            sample_interval_seconds=policy.sample_interval_seconds,
            window_seconds=policy.summary_window_seconds,
        ).summarize(tuple(samples))
        tolerance = policy.sample_interval_seconds * 0.2
        if (
            abs(
                (samples[0].observed_at - (
                    start + timedelta(seconds=policy.sample_interval_seconds)
                )).total_seconds()
            ) > tolerance
            or abs((samples[-1].observed_at - end).total_seconds()) > tolerance
        ):
            raise ProbeUnavailable("foreground_unavailable")
        self._require_live_authorization(at=observed_at)
        return self.build_draft(
            summary=summary,
            occurred_from=start,
            occurred_to=end,
            source_observed_at=max(observed_at, end),
        )

    def build_health_draft(
        self, *, status: str, safe_error_category: str, checked_at: datetime
    ) -> ContextSourceHealthDraft:
        draft = ContextSourceHealthDraft(
            owner_id=self.source.owner_id,
            source_instance_id=self.source.source_instance_id,
            device_binding_id=self.source.device_binding_id,
            capability_revision_id=self.capability.capability_revision_id,
            status=status,
            checked_at=checked_at,
            safe_error_category=safe_error_category,
            adapter_version=self.source.adapter_version,
            source_version=self.source.source_version,
            idempotency_key=(
                f"windows-health:{self.source.source_instance_id}:"
                f"{int(checked_at.timestamp())}:{status}"
            ),
            trace_id=new_trace_id(),
        )
        return sign_health_draft(draft, secret=self.signing_secret)

    def build_draft(
        self, *, summary: DeviceActivitySummary, occurred_from: datetime,
        occurred_to: datetime, source_observed_at: datetime,
    ) -> ContextObservationDraft:
        draft = ContextObservationDraft(
            owner_id=self.source.owner_id,
            source_instance_id=self.source.source_instance_id,
            device_binding_id=self.source.device_binding_id,
            capability_revision_id=self.capability.capability_revision_id,
            capability_id=self.capability.capability_id,
            observation_kind=self.capability.observation_kind,
            value=summary,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            source_observed_at=source_observed_at,
            consent_scope_revision_id=self.consent.consent_scope_revision_id,
            sampling_policy_version=self.consent.sampling_policy.policy_version,
            retention_policy_version=self.consent.retention_policy.policy_version,
            adapter_version=self.source.adapter_version,
            data_policy=self.consent.data_policy,
            idempotency_key=(
                f"windows-summary:{self.source.source_instance_id}:"
                f"{int(occurred_from.timestamp())}:{int(occurred_to.timestamp())}"
            ),
            trace_id=new_trace_id(),
        )
        return sign_observation_draft(draft, secret=self.signing_secret)

    @staticmethod
    def content_free_probe_evidence() -> dict[str, object]:
        probe = WindowsForegroundProbe(idle_threshold_seconds=300)
        return {
            "schema_version": 1,
            "adapter_version": ADAPTER_VERSION,
            "platform": platform.system(),
            "platform_release": platform.release(),
            "foreground_api_bound": probe.user32.GetForegroundWindow is not None,
            "idle_api_bound": probe.user32.GetLastInputInfo is not None,
            "activity_sample_collected": False,
            "exact_process_identity_retained": False,
            "window_title_collected": False,
            "content_collected": False,
            "screenshot_collected": False,
            "keyboard_or_clipboard_collected": False,
            "microphone_collected": False,
        }

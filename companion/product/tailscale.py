"""Fail-closed attestation for the owner-local Tailscale Serve boundary."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _contains_truthy(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_truthy(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_truthy(item) for item in value)
    return bool(value)


class TailscaleServeAttestor:
    """Verify that the accepted private HTTPS origin is Serve, never Funnel."""

    max_output_bytes = 64 * 1024

    def __init__(
        self, *, executable: Path, origin: str,
        target: str = "http://127.0.0.1:8765", timeout_seconds: float = 5.0,
        cache_seconds: float = 5.0, negative_cache_seconds: float = 1.0,
        runner: Runner = subprocess.run,
    ) -> None:
        self.executable = executable.resolve()
        self.origin = origin.rstrip("/")
        self.target = target.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self.negative_cache_seconds = negative_cache_seconds
        self.runner = runner
        self._checked_at = 0.0
        self._cached = False
        self._lock = threading.Lock()

    @staticmethod
    def _json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        if result.returncode != 0:
            raise ValueError("Tailscale command failed")
        if not isinstance(result.stdout,str):
            raise ValueError("Tailscale command output is not text")
        raw = result.stdout.encode("utf-8","strict")
        if not raw or len(raw)>TailscaleServeAttestor.max_output_bytes:
            raise ValueError("Tailscale command output is empty or oversized")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("Tailscale command did not return an object")
        return value

    def _run(self, *arguments: str) -> dict[str, Any]:
        child_environment = {
            name:os.environ[name]
            for name in ("SystemRoot","WINDIR","PROGRAMDATA")
            if name in os.environ
        }
        result = self.runner(
            [str(self.executable), *arguments], check=False, capture_output=True,
            text=True, timeout=self.timeout_seconds, shell=False,
            env=child_environment,
        )
        return self._json(result)

    def _verify(self) -> bool:
        parsed = urlsplit(self.origin)
        host = (parsed.hostname or "").lower().rstrip(".")
        status = self._run("status", "--json")
        self_status = status.get("Self")
        if status.get("BackendState") != "Running" or not isinstance(self_status, dict):
            return False
        dns_name = str(self_status.get("DNSName") or "").lower().rstrip(".")
        if dns_name != host:
            return False

        serve = self._run("serve", "status", "--json")
        allow_funnel = serve.get("AllowFunnel", {})
        if not isinstance(allow_funnel, dict) or _contains_truthy(allow_funnel):
            return False
        web = serve.get("Web")
        if not isinstance(web, dict):
            return False
        host_config = web.get(f"{host}:443")
        if not isinstance(host_config, dict):
            return False
        handlers = host_config.get("Handlers")
        if not isinstance(handlers, dict):
            return False
        root = handlers.get("/")
        return (
            isinstance(root, dict)
            and str(root.get("Proxy") or "").rstrip("/") == self.target
        )

    def __call__(self) -> bool:
        with self._lock:
            now = time.monotonic()
            cache_for = (
                self.cache_seconds if self._cached else self.negative_cache_seconds
            )
            if now - self._checked_at < cache_for:
                return self._cached
            try:
                self._cached = self._verify()
            except (OSError, ValueError, subprocess.SubprocessError):
                self._cached = False
            self._checked_at = time.monotonic()
            return self._cached


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--target", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    attestor = TailscaleServeAttestor(
        executable=args.executable, origin=args.origin, target=args.target,
        cache_seconds=0,
    )
    verified = attestor()
    print(json.dumps({"private_serve_attested": verified}))
    return 0 if verified else 2


if __name__ == "__main__":
    raise SystemExit(main())

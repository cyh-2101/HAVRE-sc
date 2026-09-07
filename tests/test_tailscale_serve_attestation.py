from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import threading
import time
import unittest

from companion.product.tailscale import TailscaleServeAttestor


class TailscaleServeAttestationTests(unittest.TestCase):
    origin = "https://havre-device.opaque-tail.ts.net"
    executable = Path("C:/Program Files/Tailscale/tailscale.exe")

    def _attestor(
        self, *, backend: str = "Running", dns_name: str | None = None,
        proxy: str = "http://127.0.0.1:8765", funnel: bool = False,
        malformed: bool = False,
    ) -> TailscaleServeAttestor:
        responses = [
            {
                "BackendState": backend,
                "Self": {"DNSName": dns_name or "havre-device.opaque-tail.ts.net."},
            },
            {
                "Web": {
                    "havre-device.opaque-tail.ts.net:443": {
                        "Handlers": {"/": {"Proxy": proxy}}
                    }
                },
                "AllowFunnel": {
                    "havre-device.opaque-tail.ts.net:443": funnel
                },
            },
        ]

        def runner(args, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertTrue(kwargs["capture_output"])
            self.assertNotIn("TS_SOCKET",kwargs["env"])
            self.assertNotIn("HTTP_PROXY",kwargs["env"])
            payload = "not-json" if malformed else json.dumps(responses.pop(0))
            return subprocess.CompletedProcess(args, 0, stdout=payload, stderr="")

        return TailscaleServeAttestor(
            executable=self.executable, origin=self.origin, runner=runner,
            cache_seconds=0,
        )

    def test_exact_private_serve_attests(self) -> None:
        self.assertTrue(self._attestor()())

    def test_funnel_wrong_target_offline_dns_and_malformed_fail_closed(self) -> None:
        cases = (
            {"funnel": True},
            {"funnel": 1},
            {"proxy": "http://127.0.0.1:9999"},
            {"backend": "Stopped"},
            {"dns_name": "other.opaque-tail.ts.net"},
            {"malformed": True},
        )
        for case in cases:
            with self.subTest(case=case):
                self.assertFalse(self._attestor(**case)())

    def test_concurrent_checks_are_singleflight_and_negative_is_short_cached(self) -> None:
        active = 0
        peak = 0
        calls = 0
        lock = threading.Lock()

        def runner(args, **kwargs):
            nonlocal active, peak, calls
            with lock:
                active += 1
                calls += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return subprocess.CompletedProcess(
                args, 0,
                stdout=json.dumps({"BackendState": "Stopped", "Self": {}}),
                stderr="",
            )

        attestor = TailscaleServeAttestor(
            executable=self.executable, origin=self.origin, runner=runner,
            cache_seconds=0, negative_cache_seconds=1,
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: attestor(), range(16)))
        self.assertEqual(results, [False] * 16)
        self.assertEqual(peak, 1)
        self.assertEqual(calls, 1)

    def test_oversized_cli_output_fails_closed(self) -> None:
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(
                args,0,stdout="{"+(" "*TailscaleServeAttestor.max_output_bytes)+"}",
                stderr="",
            )
        attestor = TailscaleServeAttestor(
            executable=self.executable,origin=self.origin,runner=runner,cache_seconds=0,
        )
        self.assertFalse(attestor())


if __name__ == "__main__":
    unittest.main()

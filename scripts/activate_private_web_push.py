"""Create or inspect one owner-local DPAPI-protected VAPID key version."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
import json

from cryptography.hazmat.primitives.asymmetric import ec

from apps.windows_agent.offline_queue import read_dpapi_secret, write_dpapi_secret
from companion.hashing import content_hash


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _derive_public(private_value: bytes) -> str:
    number = int.from_bytes(private_value, "big")
    private_key = ec.derive_private_key(number, ec.SECP256R1())
    public = private_key.public_key().public_numbers()
    return _b64url(b"\x04" + public.x.to_bytes(32, "big") + public.y.to_bytes(32, "big"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-root", required=True, type=Path)
    parser.add_argument("--key-version", default="vapid-owner-20260827")
    parser.add_argument("--subject", required=True)
    args = parser.parse_args()
    root = args.secret_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    secret_path = root / "vapid-private.dpapi"
    config_path = root / "web-push-config.json"
    if secret_path.exists():
        protected_value = read_dpapi_secret(secret_path)
        private_value = base64.urlsafe_b64decode(
            protected_value + b"=" * (-len(protected_value) % 4)
        )
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        private_value = key.private_numbers().private_value.to_bytes(32, "big")
        encoded = _b64url(private_value).encode("ascii")
        write_dpapi_secret(secret_path, encoded)
    public_key = _derive_public(private_value)
    material = {
        "schema_version": 1,
        "vapid_key_version": args.key_version,
        "vapid_public_key": public_key,
        "vapid_public_key_hash": content_hash({"public_key": public_key}),
        "vapid_subject": args.subject,
        "private_key_storage": "Windows DPAPI current-user scope",
        "private_key_file": str(secret_path),
    }
    temporary = config_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(material, indent=2), encoding="utf-8")
    temporary.replace(config_path)
    print(json.dumps({
        "status": "ready",
        "vapid_key_version": args.key_version,
        "public_key_hash": material["vapid_public_key_hash"],
        "private_key_storage": material["private_key_storage"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

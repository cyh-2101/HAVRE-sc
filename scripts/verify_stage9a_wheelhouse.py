"""Cross-check the Stage 9A TUNA wheelhouse against official PyPI metadata."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from companion.hashing import content_hash
from mlsys.training.stage9a_provenance import STAGE9A_ROOT, assert_private_stage9a_path


WHEELHOUSE = STAGE9A_ROOT / "wheelhouse" / "tuna"
EVIDENCE = STAGE9A_ROOT / "evidence" / "tuna-wheelhouse-verification.json"
HASHED_REQUIREMENTS = WHEELHOUSE / "requirements-hashed.txt"
PINS = (
    ("bitsandbytes", "0.46.1", "bitsandbytes-0.46.1-py3-none-win_amd64.whl"),
    ("numpy", "2.5.2", "numpy-2.5.2-cp312-cp312-win_amd64.whl"),
    ("MarkupSafe", "3.0.3", "markupsafe-3.0.3-cp312-cp312-win_amd64.whl"),
    ("certifi", "2026.7.22", "certifi-2026.7.22-py3-none-any.whl"),
    ("charset-normalizer", "3.5.1", "charset_normalizer-3.5.1-cp312-cp312-win_amd64.whl"),
    ("idna", "3.19", "idna-3.19-py3-none-any.whl"),
    ("urllib3", "2.7.0", "urllib3-2.7.0-py3-none-any.whl"),
    ("sympy", "1.14.0", "sympy-1.14.0-py3-none-any.whl"),
    ("mpmath", "1.3.0", "mpmath-1.3.0-py3-none-any.whl"),
    ("colorama", "0.4.6", "colorama-0.4.6-py2.py3-none-any.whl"),
    ("regex", "2026.7.19", "regex-2026.7.19-cp312-cp312-win_amd64.whl"),
    ("tokenizers", "0.21.4", "tokenizers-0.21.4-cp39-abi3-win_amd64.whl"),
    ("pydantic", "2.13.4", "pydantic-2.13.4-py3-none-any.whl"),
    ("pydantic-core", "2.46.4", "pydantic_core-2.46.4-cp312-cp312-win_amd64.whl"),
    ("annotated-types", "0.8.0", "annotated_types-0.8.0-py3-none-any.whl"),
    ("typing-inspection", "0.4.2", "typing_inspection-0.4.2-py3-none-any.whl"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify() -> dict:
    wheelhouse = assert_private_stage9a_path(WHEELHOUSE)
    evidence_path = assert_private_stage9a_path(EVIDENCE)
    hashed_requirements = assert_private_stage9a_path(HASHED_REQUIREMENTS)
    actual_names = {path.name for path in wheelhouse.glob("*.whl")}
    expected_names = {filename for _, _, filename in PINS}
    if actual_names != expected_names:
        raise ValueError(
            f"wheelhouse file set mismatch: missing={expected_names - actual_names}, "
            f"unexpected={actual_names - expected_names}"
        )
    files = []
    lock_lines = []
    for package, version, filename in PINS:
        url = (
            "https://pypi.org/pypi/"
            + urllib.parse.quote(package, safe="")
            + "/"
            + urllib.parse.quote(version, safe="")
            + "/json"
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "HAVRE-Stage9A-Wheelhouse-Verification/1"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            metadata = json.load(response)
        candidates = [item for item in metadata["urls"] if item["filename"] == filename]
        if len(candidates) != 1:
            raise ValueError(f"official PyPI metadata has no unique match for {filename}")
        official = candidates[0]
        path = wheelhouse / filename
        actual_size = path.stat().st_size
        actual_sha256 = _sha256(path)
        expected_size = official["size"]
        expected_sha256 = official["digests"]["sha256"]
        if actual_size != expected_size:
            raise ValueError(f"official size mismatch for {filename}")
        if actual_sha256 != expected_sha256:
            raise ValueError(f"official SHA-256 mismatch for {filename}")
        files.append({
            "package": package,
            "version": version,
            "filename": filename,
            "size_bytes": actual_size,
            "sha256": "sha256:" + actual_sha256,
            "official_metadata_url": url,
            "official_upload_time": official["upload_time_iso_8601"],
            "verified": True,
        })
        lock_lines.append(f"{package}=={version} --hash=sha256:{actual_sha256}")
    hashed_requirements.write_text("\n".join(lock_lines) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "status": "verified",
        "download_index": "https://pypi.tuna.tsinghua.edu.cn/simple",
        "metadata_authority": "https://pypi.org/pypi/{package}/{version}/json",
        "wheelhouse": str(wheelhouse),
        "file_count": len(files),
        "files": files,
        "hashed_requirements": str(hashed_requirements),
        "hashed_requirements_sha256": "sha256:" + _sha256(hashed_requirements),
        "verified_at": datetime.now(UTC).isoformat(),
    }
    report["content_hash"] = content_hash(report)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, sort_keys=True))

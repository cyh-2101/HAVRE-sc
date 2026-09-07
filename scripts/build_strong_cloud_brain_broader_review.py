"""Build the blinded broader companion-quality review packet."""

from pathlib import Path

from evals.strong_cloud_brain_broader_review import build_broader_review_evidence
from mlsys.training.stage9a_provenance import PROJECT_ROOT


def main() -> None:
    root = PROJECT_ROOT / "evals/reports/strong_cloud_brain_20260826"
    packet, key = build_broader_review_evidence(
        cloud_report_path=root / "deepseek-v4-pro-thinking-broader-v3-final.json",
        packet_path=root / "broader-companion-blind-review-v2-final.json",
        key_path=root / "broader-companion-blinding-key-v2-final.json",
    )
    print(packet["content_hash"])
    print(key["content_hash"])


if __name__ == "__main__":
    main()

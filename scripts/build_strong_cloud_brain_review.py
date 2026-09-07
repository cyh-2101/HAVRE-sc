"""Build the identified comparison and blinded semantic-review packet."""

from evals.strong_cloud_brain_review import REPORT_DIR, build_review_evidence


def main() -> None:
    comparison, blind_packet, blinding_key = build_review_evidence(
        comparison_path=REPORT_DIR / "focused-comparison-v1.json",
        blind_packet_path=REPORT_DIR / "focused-blind-review-v1.json",
        blinding_key_path=REPORT_DIR / "focused-blinding-key-v1.json",
    )
    print(comparison["content_hash"])
    print(blind_packet["content_hash"])
    print(blinding_key["content_hash"])


if __name__ == "__main__":
    main()

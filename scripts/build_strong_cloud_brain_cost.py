from evals.strong_cloud_brain_cost import REPORT_DIR, build_cost_evidence


if __name__ == "__main__":
    result = build_cost_evidence(
        output_path=REPORT_DIR / "formal-cost-evidence-v1.json"
    )
    print(result["content_hash"])

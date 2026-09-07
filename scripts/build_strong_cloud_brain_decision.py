from evals.strong_cloud_brain_decision import REPORT_DIR, build_decision_evidence


if __name__ == "__main__":
    result = build_decision_evidence(output_path=REPORT_DIR / "decision-evidence-v1.json")
    print(result["content_hash"])

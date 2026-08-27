"""Run the immutable four-arm Stage 9A v6 unseen evaluation."""

from __future__ import annotations

import json

from mlsys.training.stage9a_evaluation_v6 import run_evaluation


if __name__ == "__main__":
    result = run_evaluation()
    print(json.dumps({"status": result["status"], "content_hash": result["content_hash"]}, sort_keys=True))

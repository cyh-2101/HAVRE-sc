"""Additively rescore the frozen Stage 9A v6 evaluation outputs."""

from __future__ import annotations

import json

from mlsys.training.stage9a_evaluation_v6 import rescore_evaluation


if __name__ == "__main__":
    result = rescore_evaluation()
    print(json.dumps({"status": result["status"], "content_hash": result["content_hash"]}, sort_keys=True))

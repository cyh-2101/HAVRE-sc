"""Focused paired evaluation for natural, useful, truthful Memory use."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from companion.context import (
    CONTEXT_PRESENTATION_VERSION,
    render_memory_evidence,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "relevant_memory_use_v1.json"
SCORER_VERSION = "relevant-memory-use-scorer-v2-surface-plus-review"
LEGACY_PRESENTATION_VERSION = "legacy-context-sections-v8"
NATURAL_MEMORY_PRESENTATION_VERSION = (
    "context-presentation-v2-natural-memory-linking"
)
UNCERTAINTY_MARKERS = (
    "谁",
    "哪个",
    "哪件",
    "哪种",
    "对不上",
    "没对上",
    "不确定",
    "是指",
    "吗",
    "？",
)
CALLBACK_MARKERS = ("我记得", "你之前说", "上次你说", "还记得")
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


def load_suite(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    if (
        suite.get("schema_version") != 1
        or suite.get("contains_user_data") is not False
        or suite.get("training_eligible") is not False
        or suite.get("validation_for_training") is not False
    ):
        raise ValueError("Memory-use suite violates its synthetic evaluation boundary")
    required = set(suite["pair_contract"]["required_variants"])
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for case in suite["cases"]:
        if case["case_id"] in seen:
            raise ValueError("Memory-use suite contains duplicate case IDs")
        seen.add(case["case_id"])
        by_pair[case["pair_id"]].append(case)
    for pair_id, cases in by_pair.items():
        if {case["variant"] for case in cases} != required:
            raise ValueError(f"{pair_id} does not contain the exact counterfactual variants")
        if len({case["user_message"] for case in cases}) != 1:
            raise ValueError(f"{pair_id} does not preserve the same user message")
    if not suite.get("multi_memory_cases") or any(
        len(case.get("memory_context", [])) < 2
        for case in suite["multi_memory_cases"]
    ):
        raise ValueError("Memory-use suite lacks a multi-Memory interference slice")
    return suite


def prompt_messages(
    case: dict[str, Any],
    *,
    system_text: str,
    presentation_version: str,
) -> list[dict[str, str]]:
    memories = tuple(str(value) for value in case.get("memory_context", []))
    if presentation_version == LEGACY_PRESENTATION_VERSION:
        return [
            {"role": "system", "content": system_text},
            *[{"role": "system", "content": value} for value in memories],
            {"role": "user", "content": case["user_message"]},
        ]
    if presentation_version not in {
        NATURAL_MEMORY_PRESENTATION_VERSION,
        CONTEXT_PRESENTATION_VERSION,
    }:
        raise ValueError("unknown context presentation version")
    if memories:
        system_text = (
            f"{system_text}\n\n"
            + render_memory_evidence(
                tuple(("episodic", value) for value in memories),
                legacy=presentation_version == NATURAL_MEMORY_PRESENTATION_VERSION,
            )
        )
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": case["user_message"]},
    ]


def _groups_pass(groups: list[list[str]], output: str) -> bool | None:
    if not groups:
        return None
    return all(any(marker in output for marker in group) for group in groups)


def _normalized_text(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _copied_memory_span(memory_context: list[str], output: str) -> int:
    normalized_output = _normalized_text(output)
    return max(
        (
            SequenceMatcher(
                None, _normalized_text(memory), normalized_output, autojunk=False
            ).find_longest_match().size
            for memory in memory_context
        ),
        default=0,
    )


def _language_continuity(user_message: str, output: str) -> bool:
    if not CJK_PATTERN.search(user_message):
        return True
    cjk_count = len(CJK_PATTERN.findall(output))
    return cjk_count >= 2 and cjk_count / max(1, len(output)) >= 0.15


def score_case(
    case: dict[str, Any],
    output: str,
    *,
    global_forbidden_meta_phrases: list[str],
) -> dict[str, Any]:
    expected = case["expected"]
    forbidden = [
        value
        for value in (
            *global_forbidden_meta_phrases,
            *expected["forbidden_phrases"],
        )
        if value in output
    ]
    required_groups = _groups_pass(expected["required_any_groups"], output)
    uncertainty = any(marker in output for marker in UNCERTAINTY_MARKERS)
    uncertainty_pass = (
        uncertainty if expected["uncertainty_required"] else None
    )
    forced_callback = (
        case["variant"] in {"irrelevant", "none"}
        and any(marker in output for marker in CALLBACK_MARKERS)
    )
    copied_span = _copied_memory_span(case.get("memory_context", []), output)
    if case["variant"] in {"irrelevant", "stale_conflicting"} and copied_span >= 6:
        forced_callback = True
    language_continuity = _language_continuity(case["user_message"], output)
    naturalness = (
        not forbidden
        and len(output) <= expected["max_output_chars"]
        and language_continuity
    )
    checks = {
        "naturalness_diagnostic": naturalness,
        "usefulness_required_groups": required_groups,
        "provenance_truth": not forbidden,
        "fabricated_familiarity": None,
        "forced_callback": not forced_callback,
        "ignored_relevant_history": (
            required_groups if case["variant"] == "relevant" else None
        ),
        "current_message_precedence": (
            required_groups
            if case["variant"] == "stale_conflicting"
            and expected["required_any_groups"]
            else (not forbidden if case["variant"] == "stale_conflicting" else None)
        ),
        "partial_uncertainty": (
            uncertainty_pass if case["variant"] == "partial" else None
        ),
        "language_continuity": language_continuity,
    }
    applicable = [value for value in checks.values() if value is not None]
    return {
        "checks": checks,
        "deterministic_pass": all(applicable),
        "output_chars": len(output),
        "forbidden_phrase_hits": forbidden,
        "uncertainty_marker_present": uncertainty,
        "longest_copied_memory_span": copied_span,
        "scorer_version": SCORER_VERSION,
        "semantic_review_required": True,
        "semantic_review_dimensions": [
            "naturalness",
            "usefulness",
            "provenance_truth",
            "fabricated_familiarity",
            "forced_callback",
            "ignored_relevant_history",
            "current_message_precedence"
        ],
        "limitations": (
            "This is an automated surface/property screen. It deliberately does not "
            "claim final semantic passage; blind paired review is required."
        ),
    }


def score_casual_case(
    case: dict[str, Any],
    output: str,
    *,
    global_forbidden_meta_phrases: list[str],
) -> dict[str, Any]:
    forbidden = [
        marker
        for marker in (*global_forbidden_meta_phrases, *case["forbidden_phrases"])
        if marker in output
    ]
    return {
        "deterministic_pass": not forbidden and len(output) <= case["max_output_chars"],
        "output_chars": len(output),
        "forbidden_phrase_hits": forbidden,
        "within_max_chars": len(output) <= case["max_output_chars"],
        "scorer_version": SCORER_VERSION,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [row for row in results if row["kind"] == "paired_memory"]
    multi = [row for row in results if row["kind"] == "multi_memory"]
    casual = [row for row in results if row["kind"] == "casual_regression"]
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in paired:
        by_variant[row["variant"]].append(row)

    def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "case_count": len(rows),
            "deterministic_pass_count": sum(
                bool(row["scores"]["deterministic_pass"]) for row in rows
            ),
        }

    return {
        "paired_memory": counts(paired),
        "by_variant": {
            variant: counts(by_variant[variant])
            for variant in sorted(by_variant)
        },
        "casual_regression": counts(casual),
        "multi_memory": counts(multi),
        "semantic_review_required": True,
        "no_single_quality_composite": True,
    }

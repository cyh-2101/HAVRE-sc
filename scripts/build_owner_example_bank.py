"""Derive the explicitly authorized OA70 cases 1-70 runtime example bank."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from companion.context.examples import (
    OWNER_EXAMPLE_AUTHORIZATION_REF,
    OWNER_EXAMPLE_CASE_IDS,
    OWNER_EXAMPLE_SOURCE_SHA256,
    BehaviorExampleMessage,
    OwnerBehaviorExample,
    OwnerExampleBank,
)
from companion.policy import DataPolicy, PrivacyClass


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build_bank(*, source: Path, owner_id: UUID) -> OwnerExampleBank:
    source_hash = _file_sha256(source)
    if source_hash != OWNER_EXAMPLE_SOURCE_SHA256:
        raise ValueError(
            "OA70 source hash changed; refuse to derive examples from an unknown artifact"
        )
    payload = json.loads(source.read_text(encoding="utf-8"))
    if (
        payload.get("case_count") != 70
        or payload.get("privacy_class") != "PRIVATE"
        or payload.get("local_only") is not True
        or payload.get("evaluation_only") is not True
        or payload.get("training_eligible") is not False
        or payload.get("prompt_tuning_eligible") is not False
    ):
        raise ValueError("OA70 source governance flags do not match the frozen artifact")
    source_cases = tuple(payload.get("cases", ()))
    if tuple(case.get("case_id") for case in source_cases) != OWNER_EXAMPLE_CASE_IDS:
        raise ValueError("OA70 case IDs do not match the authorized all-70 selection")
    examples = tuple(
        OwnerBehaviorExample(
            case_id=case["case_id"],
            title=case["title"],
            messages=tuple(
                BehaviorExampleMessage(role=message["role"], content=message["content"])
                for message in case["messages"]
            ),
            preferred_reply=case["expected_text"],
            source_case_content_hash=case["content_hash"],
        )
        for case in source_cases
    )
    policy_revision_id = uuid5(NAMESPACE_URL, OWNER_EXAMPLE_AUTHORIZATION_REF)
    return OwnerExampleBank(
        owner_id=owner_id,
        source_case_ids=OWNER_EXAMPLE_CASE_IDS,
        data_policy=DataPolicy(
            policy_revision_id=policy_revision_id,
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=False,
            cloud_eligible=True,
            decision_source="owner_explicit",
            authorization_ref=OWNER_EXAMPLE_AUTHORIZATION_REF,
        ),
        examples=examples,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-id", type=UUID, required=True)
    args = parser.parse_args()
    bank = build_bank(source=args.source.resolve(), owner_id=args.owner_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bank.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "example_bank_version": bank.example_bank_version,
                "example_count": len(bank.examples),
                "content_hash": bank.content_hash,
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

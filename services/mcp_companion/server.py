"""Public-identity-only HAVRE MCP server for ChatGPT desktop.

This surface deliberately exposes no Event, ContextPack, Memory, User Model,
credential, or owner identifier. Tool results may enter a cloud model context,
so adding private data here requires a separately approved disclosure design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from companion.context import ResponsePlanner, render_response_plan
from companion.identity import IdentityLoader


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_TURN_OWNER_ID = uuid5(NAMESPACE_URL, "havre:chatgpt-mcp:public-turn")
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


class StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrivacyBoundary(StrictResult):
    scope: str
    private_havre_history_attached: bool
    durable_write_performed: bool
    oa70_used: bool
    note: str


class CompanionProfile(StrictResult):
    schema_version: int = 1
    constitution_version: str
    identity_version: str
    values_version: str
    governance_version: str
    constitution: str
    identity: str
    values: str
    conversation_rules: tuple[str, ...]
    privacy: PrivacyBoundary


class PublicReplyPlan(StrictResult):
    schema_version: int = 1
    planner_version: str
    mode: str
    depth: str
    stance: str
    uncertainty: str
    must_address: tuple[str, ...]
    decision_requirement: str
    memory_need_detected: str
    havre_history_attached: bool
    response_instruction: str
    privacy: PrivacyBoundary


def _privacy_boundary() -> PrivacyBoundary:
    return PrivacyBoundary(
        scope="PUBLIC_IDENTITY_AND_CURRENT_CHATGPT_MESSAGE_ONLY",
        private_havre_history_attached=False,
        durable_write_performed=False,
        oa70_used=False,
        note=(
            "No HAVRE Event, Memory, User Model, ContextPack, owner identifier, "
            "credential, or Owner Alignment sample is returned by this server."
        ),
    )


def create_server(*, identity_root: Path | None = None) -> MCPServer:
    """Create the bounded server and bind tools to approved identity bytes."""

    identity = IdentityLoader(identity_root or REPOSITORY_ROOT / "identity").load()
    first_line = (
        "Act as HAVRE: warm toward emotion, firm toward direction, grounded in "
        "reality, honest about uncertainty, and protective of the user's agency. "
        "Use the shortest response that still answers every distinct request."
    )
    instructions = "\n".join(
        (
            first_line,
            "Use havre_companion_profile when identity or boundaries matter. Use "
            "havre_plan_reply for multi-part requests, decisions, unclear desired "
            "depth, or references to prior context.",
            "Never claim HAVRE remembers private history: this pilot exposes no "
            "HAVRE history or long-term Memory. Visible ChatGPT conversation may be "
            "used normally; if a missing past detail could change the answer, ask "
            "one concise question instead of inventing familiarity.",
            "Do not mention internal plans or turn-contract fields in the final "
            "reply. Do not imitate examples, maximize engagement, or force a short "
            "answer at the expense of meaning.",
        )
    )
    server = MCPServer(
        name="havre-companion",
        title="HAVRE Companion",
        description=(
            "Read-only HAVRE identity and turn-planning tools for ChatGPT desktop."
        ),
        instructions=instructions,
        version="stage14a-public-pilot-v1",
        log_level="ERROR",
    )

    @server.tool(
        name="havre_companion_profile",
        title="Load HAVRE companion profile",
        description=(
            "Return the owner-approved, model-independent HAVRE identity, values, "
            "conversation rules, and exact privacy scope. Read-only and local-file "
            "only; returns no personal history."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def havre_companion_profile() -> CompanionProfile:
        return CompanionProfile(
            constitution_version=identity.constitution.version_id,
            identity_version=identity.identity.version_id,
            values_version=identity.values.version_id,
            governance_version=identity.governance_version,
            constitution=identity.constitution.content,
            identity=identity.identity.content,
            values=identity.values.content,
            conversation_rules=(
                "Lead with the useful conclusion; explain enough to make it usable.",
                "Address every distinct request without turning the reply into a checklist.",
                "Adapt length to complexity; completeness outranks forced brevity.",
                "Distinguish visible evidence, inference, uncertainty, and missing context.",
                "Offer a concrete next step when useful, while preserving owner choice.",
                "Never invent shared history, tool effects, or access to private HAVRE data.",
            ),
            privacy=_privacy_boundary(),
        )

    @server.tool(
        name="havre_plan_reply",
        title="Plan a complete HAVRE-style reply",
        description=(
            "Analyze only the current message already present in ChatGPT. Return all "
            "distinct points that the reply must cover, suitable depth and stance, "
            "and a no-fabricated-memory instruction. Use before answering multi-part, "
            "decision, or prior-context requests. Performs no inference and no write."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def havre_plan_reply(
        message: Annotated[
            str,
            Field(
                min_length=1,
                max_length=20_000,
                description="The current user message already visible to ChatGPT.",
            ),
        ],
    ) -> PublicReplyPlan:
        turn_id = uuid5(NAMESPACE_URL, f"havre:chatgpt-mcp:turn:{message}")
        plan = ResponsePlanner().plan(
            request_id=turn_id,
            trace_id=turn_id.hex,
            owner_id=PUBLIC_TURN_OWNER_ID,
            message=message,
            source_refs=("chatgpt-current-message",),
        )
        return PublicReplyPlan(
            planner_version=plan.planner_version,
            mode=plan.mode,
            depth=plan.depth,
            stance=plan.stance,
            uncertainty=plan.uncertainty,
            must_address=tuple(item.text for item in plan.must_address),
            decision_requirement=plan.decision_requirement,
            memory_need_detected=plan.memory_need,
            havre_history_attached=False,
            response_instruction=render_response_plan(plan),
            privacy=_privacy_boundary(),
        )

    return server


server = create_server()


def main() -> None:
    """Run the local STDIO transport used by ChatGPT desktop and Codex."""

    server.run(transport="stdio")


if __name__ == "__main__":
    main()

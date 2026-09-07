# ADR-0028: ChatGPT desktop MCP companion surface

- Status: Accepted
- Accepted: 2026-09-03 by Product Owner
- Date: 2026-09-03
- Decision owners: Product Owner/System Architect
- Extends: ADR-0005, ADR-0009, ADR-0011, ADR-0014, ADR-0022, ADR-0027

## Context

The local 8B/14B experiments have not yet produced a Replyer the owner would
choose over a strong general chat product. The owner explicitly authorized a
direct ChatGPT MCP implementation as a practical route that uses the existing
ChatGPT subscription rather than an OpenAI API key.

MCP connects a host model to tools and context; it does not turn the ChatGPT
subscription into HAVRE's provider-neutral inference endpoint. In particular,
the host produces the final response outside HAVRE's ordinary ContextPack,
Event, and Core-delivery path.

## Decision

Add a local STDIO MCP server using the exact official Python SDK
`mcp==2.1.1`. ChatGPT desktop and Codex may launch the same server from the
shared host MCP configuration.

Stage 14A exposes only:

1. the already owner-approved, model-independent PUBLIC Constitution, Identity,
   Values, and conversation rules; and
2. deterministic Turn Contract planning over the current message that is
   already present in the ChatGPT conversation.

Both tools are read-only, idempotent, and closed-world. Their structured
results state that no private HAVRE history is attached and no durable write is
performed. The server has no database, network, owner-token, credential,
inference, delivery, or tool-effect capability.

The 70-case PRIVATE Owner Alignment Set remains physically and logically
excluded. It is not read, uploaded, copied into server instructions, used as
few-shot context, transformed into style rules, or used for prompt tuning.

Server instructions ask the host to preserve HAVRE's fixed warmth, firmness,
reality orientation, agency, completeness, adaptive length, and no-fabricated-
memory behavior. These instructions guide generation; they are not a Core
enforcement boundary.

## Consequences and limits

- ChatGPT supplies the strong Replyer and visible-thread short-term context
  under the user's ChatGPT account. No OpenAI API key is required by HAVRE.
- The result can be useful immediately for conversation-quality testing without
  waiting for the 35B local candidate.
- ChatGPT decides whether to call MCP tools. Its final answer is not currently
  returned to HAVRE, persisted in the Event Store, passed through ADR-0022 Core,
  or admitted into governed HAVRE Memory.
- The pilot therefore does not prove HAVRE long-term continuity, privacy-safe
  personalized context, proactive behavior, tool truthfulness, or local/offline
  operation.
- ChatGPT web does not consume the host's local MCP configuration. This decision
  covers the desktop application on the same host only.
- A future private-context tool, response-capture bridge, write tool, automatic
  routing rule, or long-term Memory connection requires a separately accepted
  Stage 14B disclosure and lifecycle design. Cloud eligibility must be explicit;
  redaction or summarization alone cannot authorize disclosure.

## Validation

- in-process protocol test for server instructions, tool schemas, annotations,
  structured results, and public identity versions;
- real subprocess STDIO initialization and tool-call test;
- regressions for multi-request preservation, missing-history handling, and
  explicit OA70/private-history absence;
- dependency integrity, compilation, diff checks, and the complete zero-skip
  PostgreSQL-backed suite before checkpoint closure;
- owner-visible desktop conversations are required to establish usefulness.

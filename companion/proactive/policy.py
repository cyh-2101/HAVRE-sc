"""Explicit fail-closed Core-owned Stage 6 Interruption Policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from companion.policy import PrivacyClass
from companion.proactive.models import (
    InterruptionDecision,
    InterruptionInputs,
    InterruptionOutcome,
    ProactivePreferenceRevision,
    ProactiveProposal,
)


class InterruptionPolicy:
    version = "interruption-policy-conservative-v1"

    def __init__(self, *, constitution_version_id: str, identity_version_id: str) -> None:
        self.constitution_version_id = constitution_version_id
        self.identity_version_id = identity_version_id

    def decide(
        self,
        *,
        proposal: ProactiveProposal,
        preference: ProactivePreferenceRevision,
        now: datetime,
        delivered_global_24h: int,
        delivered_category_24h: int,
        last_equivalent_delivery_at: datetime | None,
        duplicate_active: bool,
        prior_response_result: str = "none",
        snooze_until: datetime | None = None,
    ) -> InterruptionDecision:
        if now.utcoffset() is None:
            raise ValueError("policy evaluation time must be timezone-aware")
        now = now.astimezone(UTC)
        if proposal.owner_id != preference.owner_id:
            raise ValueError("proposal and preference owner mismatch")

        permission = preference.category_permissions.get(proposal.category, "unresolved")
        expiration = (
            "not_yet" if now < proposal.earliest_eligible_at
            else "expired" if now >= proposal.expires_at
            else "eligible"
        )
        inside_quiet = any(
            (window.start_local <= now.time() < window.end_local)
            if window.start_local <= window.end_local
            else (now.time() >= window.start_local or now.time() < window.end_local)
            for window in preference.quiet_hours
        )
        quiet_result = "inside" if inside_quiet else "outside"
        global_budget = (
            "unresolved" if preference.global_budget_per_24h is None
            else "available" if delivered_global_24h < preference.global_budget_per_24h
            else "exhausted"
        )
        category_limit = preference.category_budget_per_24h.get(proposal.category)
        category_budget = (
            "unresolved" if category_limit is None
            else "available" if delivered_category_24h < category_limit
            else "exhausted"
        )
        cooldown = "unresolved"
        if preference.cooldown_seconds is not None:
            cooldown = (
                "active"
                if last_equivalent_delivery_at is not None
                and now < last_equivalent_delivery_at + timedelta(seconds=preference.cooldown_seconds)
                else "clear"
            )
        channel = (
            "eligible"
            if "web_inbox" in proposal.candidate_channels
            and "web_inbox" in preference.allowed_channels
            else "ineligible"
        )
        privacy = (
            "eligible"
            if proposal.data_policy.privacy_class
            in {
                PrivacyClass.PUBLIC,
                PrivacyClass.NORMAL,
                PrivacyClass.PRIVATE,
                PrivacyClass.HIGHLY_PRIVATE,
                PrivacyClass.LOCAL_ONLY,
            }
            else "ineligible"
        )
        stopped = any(ref in preference.stopped_subject_refs for ref in proposal.subject_refs)
        inputs = InterruptionInputs(
            global_permission="enabled" if preference.global_enabled else "disabled",
            category_permission=permission,
            quiet_hours_result=quiet_result,
            global_budget_result=global_budget,
            category_budget_result=category_budget,
            cooldown_result=cooldown,
            deduplication_result="duplicate" if duplicate_active else "unique",
            expiration_result=expiration,
            channel_eligibility=channel,
            privacy_eligibility=privacy,
            subject_stop_result="stopped" if stopped else "clear",
            prior_response_result=prior_response_result,
        )

        decision, reasons, explanation, defer_until = self._outcome(
            proposal=proposal,
            preference=preference,
            inputs=inputs,
            now=now,
            snooze_until=snooze_until,
        )
        return InterruptionDecision(
            owner_id=proposal.owner_id,
            proposal_id=proposal.proposal_id,
            decision=decision,
            reason_codes=reasons,
            human_explanation=explanation,
            preference_revision_id=preference.preference_revision_id,
            constitution_version_id=self.constitution_version_id,
            identity_version_id=self.identity_version_id,
            inputs_snapshot=inputs,
            defer_until=defer_until,
            expires_at=proposal.expires_at,
            rendering_constraints=(
                "exact_authorized_purpose_only",
                "no_emotional_hook_or_manufactured_urgency",
                "no_call_to_continue_talking",
                "local_web_inbox_only",
            ),
            trace_id=proposal.trace_id,
        )

    @staticmethod
    def _outcome(*, proposal, preference, inputs, now, snooze_until):
        if inputs.expiration_result == "expired":
            return InterruptionOutcome.DROP, ("proposal_expired",), "The useful window ended.", None
        if inputs.subject_stop_result == "stopped":
            return InterruptionOutcome.DROP, ("owner_stopped_subject",), "The owner stopped this reminder subject.", None
        if inputs.prior_response_result in {"dismissed", "stopped"}:
            return (
                InterruptionOutcome.DROP,
                ("owner_control_suppressed",),
                "An explicit owner control suppresses an equivalent follow-up.",
                None,
            )
        if inputs.prior_response_result == "non_response":
            return (
                InterruptionOutcome.DROP,
                ("non_response_frequency_suppressed",),
                "No cadence is approved after non-response; an equivalent follow-up is suppressed.",
                None,
            )
        if inputs.prior_response_result == "snoozed":
            if snooze_until is None or snooze_until >= proposal.expires_at:
                return (
                    InterruptionOutcome.DROP,
                    ("snooze_outlives_proposal",),
                    "The owner snoozed beyond the proposal's useful window.",
                    None,
                )
            return (
                InterruptionOutcome.DEFER,
                ("owner_snoozed",),
                "The owner explicitly snoozed this equivalent proposal.",
                snooze_until,
            )
        if inputs.category_permission == "denied" or inputs.global_permission == "disabled":
            return InterruptionOutcome.DROP, ("permission_denied",), "Proactive contact is disabled for this scope.", None
        if inputs.privacy_eligibility == "ineligible" or inputs.channel_eligibility == "ineligible":
            return InterruptionOutcome.DROP, ("channel_or_privacy_ineligible",), "No eligible local delivery path exists.", None
        if inputs.deduplication_result == "duplicate":
            return InterruptionOutcome.DROP, ("duplicate_suppressed",), "An equivalent proposal already exists.", None
        if inputs.category_permission in {"confirmation_required", "unresolved"}:
            return (
                InterruptionOutcome.REQUEST_OWNER_CONFIRMATION,
                ("owner_confirmation_required",),
                "The owner must confirm this category in the review surface; no outreach is sent.",
                None,
            )
        if inputs.expiration_result == "not_yet":
            return InterruptionOutcome.DEFER, ("not_yet_eligible",), "The proposal is early.", proposal.earliest_eligible_at
        if inputs.quiet_hours_result == "inside":
            return InterruptionOutcome.DEFER, ("quiet_hours",), "Quiet hours are active.", min(proposal.expires_at, now + timedelta(hours=1))
        if "exhausted" in {inputs.global_budget_result, inputs.category_budget_result}:
            return InterruptionOutcome.DEFER, ("budget_exhausted",), "The outreach ceiling is exhausted.", min(proposal.expires_at, now + timedelta(hours=24))
        if inputs.cooldown_result == "active":
            return InterruptionOutcome.DEFER, ("cooldown_active",), "An equivalent delivery is cooling down.", min(proposal.expires_at, now + timedelta(hours=1))
        unresolved = {
            inputs.global_budget_result,
            inputs.category_budget_result,
            inputs.cooldown_result,
        }
        if "unresolved" in unresolved:
            return (
                InterruptionOutcome.REQUEST_OWNER_CONFIRMATION,
                ("binding_limit_unresolved",),
                "A binding owner control is unresolved; no outreach is sent.",
                None,
            )
        return InterruptionOutcome.SEND_NOW, ("all_hard_controls_passed",), "The owner-authorized local Web/inbox fixture passed every hard control.", None

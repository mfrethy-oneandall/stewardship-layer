"""Core StewardshipGate implementation.

Implements Propose → Explain → Confirm → Execute → Learn.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from audit_log import AuditEntry, AuditLog, now_ts
from policies import (
    Allowlist,
    PolicyDecision,
    RateLimiter,
    allowlist_policy,
    explain_policy_results,
    reversibility_required,
    safe_domain_policy,
)


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    actor: str
    action: str
    resource: str
    domain: str
    rationale: str
    rollback_plan: str | None
    trace_id: str


@dataclass(frozen=True)
class Decision:
    proposal_id: str
    approved: bool
    reason: str
    approver: str
    timestamp: float


@dataclass(frozen=True)
class ExecutionResult:
    proposal_id: str
    status: str
    details: str
    started_at: float
    ended_at: float


class Executor(Protocol):
    def __call__(self, proposal: Proposal) -> str:  # returns details
        ...


class StewardshipGate:
    def __init__(
        self,
        audit_log: AuditLog,
        allowlist: Allowlist,
        safe_domains: Iterable[str],
        rate_limiter: RateLimiter,
    ) -> None:
        self.audit_log = audit_log
        self.allowlist = allowlist
        self.safe_domains = set(safe_domains)
        self.rate_limiter = rate_limiter

    # Propose
    def propose(
        self, actor: str, action: str, resource: str, domain: str, rationale: str, rollback_plan: str | None
    ) -> Proposal:
        proposal = Proposal(
            proposal_id=f"pl-{uuid.uuid4().hex[:8]}",
            actor=actor,
            action=action,
            resource=resource,
            domain=domain,
            rationale=rationale,
            rollback_plan=rollback_plan,
            trace_id=f"tr-{uuid.uuid4().hex[:8]}",
        )
        self.audit_log.append(
            AuditEntry(proposal.proposal_id, proposal.trace_id, "propose", proposal.__dict__, now_ts())
        )
        return proposal

    # Explain
    def explain(self, proposal: Proposal) -> str:
        policy_results = {
            "allowlist": allowlist_policy(proposal.action, proposal.resource, self.allowlist),
            "safe_domain": safe_domain_policy(proposal.domain, self.safe_domains),
            "reversible": reversibility_required(proposal.rollback_plan is not None),
        }
        summary = (
            f"Action: {proposal.action} on {proposal.resource} in {proposal.domain}. "
            f"Rationale: {proposal.rationale}. Rollback: {proposal.rollback_plan or 'none'}. "
            f"Policies -> {explain_policy_results(policy_results)}"
        )
        self.audit_log.append(
            AuditEntry(proposal.proposal_id, proposal.trace_id, "explain", {"summary": summary}, now_ts())
        )
        return summary

    # Decide
    def decide(
        self, proposal: Proposal, approver: str, decision_fn: Callable[[str], bool]
    ) -> Decision:
        # Always generate an explanation so the decision path is auditable.
        explanation = self.explain(proposal)

        # Automated approvals if allowlisted AND safe domain AND reversible.
        policy_results = {
            "allowlist": allowlist_policy(proposal.action, proposal.resource, self.allowlist),
            "safe_domain": safe_domain_policy(proposal.domain, self.safe_domains),
            "reversible": reversibility_required(proposal.rollback_plan is not None),
        }
        auto_approve = all(pd.allowed for pd in policy_results.values())
        approved = auto_approve or decision_fn(explanation)
        reason = "auto-approved" if auto_approve else ("human approved" if approved else "human denied")
        decision = Decision(
            proposal_id=proposal.proposal_id,
            approved=approved,
            reason=reason,
            approver=approver,
            timestamp=now_ts(),
        )
        self.audit_log.append(
            AuditEntry(proposal.proposal_id, proposal.trace_id, "decision", decision.__dict__, decision.timestamp)
        )
        return decision

    # Execute
    def execute(self, proposal: Proposal, decision: Decision, executor: Executor) -> ExecutionResult:
        start = now_ts()
        if not decision.approved:
            result = ExecutionResult(
                proposal.proposal_id, "SKIPPED", decision.reason, start, now_ts()
            )
            self.audit_log.append(
                AuditEntry(proposal.proposal_id, proposal.trace_id, "execute", result.__dict__, now_ts())
            )
            return result

        rate_result: PolicyDecision = self.rate_limiter.accept(proposal.actor, now=start)
        if not rate_result.allowed:
            result = ExecutionResult(
                proposal.proposal_id, "SKIPPED", rate_result.reason, start, now_ts()
            )
            self.audit_log.append(
                AuditEntry(proposal.proposal_id, proposal.trace_id, "execute", result.__dict__, now_ts())
            )
            return result

        details = executor(proposal)
        result = ExecutionResult(proposal.proposal_id, "SUCCESS", details, start, now_ts())
        self.audit_log.append(
            AuditEntry(proposal.proposal_id, proposal.trace_id, "execute", result.__dict__, now_ts())
        )
        return result

    # Learn
    def learn(self, proposal: Proposal, execution: ExecutionResult, feedback: str | None = None) -> None:
        payload = {
            "execution_status": execution.status,
            "details": execution.details,
            "feedback": feedback or "",
        }
        self.audit_log.append(
            AuditEntry(proposal.proposal_id, proposal.trace_id, "learn", payload, now_ts())
        )


__all__ = [
    "Proposal",
    "Decision",
    "ExecutionResult",
    "StewardshipGate",
]

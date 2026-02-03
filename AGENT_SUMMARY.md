# Agent Summary

This document describes the stewardship layer API for agents that integrate with it.

## What the Gate Does

The `StewardshipGate` class receives proposals, evaluates them against configured policies, and either auto-approves (if all policies pass) or delegates to a decision function. Approved proposals are executed through a provided executor. All stages are logged to an append-only audit log.

## The Five-Step Loop

The gate implements this sequence:

1. **Propose**: Create a `Proposal` with actor, action, resource, domain, rationale, and optional rollback plan. Returns a proposal with generated `proposal_id` and `trace_id`.

2. **Explain**: Generate a human-readable summary of the proposal including policy evaluation results. Called automatically during `decide()`.

3. **Decide**: Evaluate policies (allowlist, safe_domain, reversibility). If all pass, auto-approve. Otherwise, call the provided `decision_fn` with the explanation. Returns a `Decision`.

4. **Execute**: If approved and rate limit allows, call the executor. Returns an `ExecutionResult` with status (SUCCESS, SKIPPED, FAILURE).

5. **Learn**: Record execution outcome and optional feedback to the audit log.

## Interfaces

```python
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
    status: str  # SUCCESS, SKIPPED, FAILURE
    details: str
    started_at: float
    ended_at: float
```

## Usage Example

```python
from stewardship_gate import StewardshipGate, Proposal

# Initialize gate with dependencies
gate = StewardshipGate(
    audit_log=my_audit_log,
    allowlist=my_allowlist,
    safe_domains=["lights", "switches"],
    rate_limiter=my_rate_limiter,
)

# Create proposal
proposal = gate.propose(
    actor="my-agent",
    action="turn_on",
    resource="light.living_room",
    domain="lights",
    rationale="User requested lights on",
    rollback_plan="turn_off light.living_room",
)

# Get decision (auto-approves if policies pass, otherwise calls decision_fn)
decision = gate.decide(
    proposal,
    approver="system",
    decision_fn=lambda explanation: ask_human(explanation),
)

# Execute if approved
result = gate.execute(proposal, decision, executor=my_executor)

# Record outcome
gate.learn(proposal, result, feedback="completed successfully")
```

## Policies

The gate evaluates three policies:

- **Allowlist**: Action and resource must match configured allowlist entries
- **Safe domain**: Domain must be in the configured safe_domains set
- **Reversibility**: `rollback_plan` must not be None

Auto-approval requires all three policies to pass. Otherwise, the `decision_fn` is called.

## References

- [SPEC.md](SPEC.md) - Full interface specification
- [STEWARD.md](STEWARD.md) - Behavior contract
- [schemas/](schemas/) - JSON Schema definitions

# Stewardship Patterns
Each pattern includes intent, when to use it, typical failure modes, and minimal pseudocode.

## Human Confirmation Gate
- **Intent**: Require explicit human approval before execution.
- **When**: Any change outside predefined safe domains; production-impacting steps.
- **Failure modes**: Decision fatigue, rubber-stamping, unclear summaries.
- **Pseudocode**:
```pseudo
decision = prompt_human(proposal.summary, proposal.risks)
if decision != APPROVE: return DENY
execute(proposal)
```

## Allowlist / Safe Domains
- **Intent**: Auto-approve only well-defined, low-risk actions/resources.
- **When**: Idempotent reads, sandboxed environments, mock/test systems.
- **Failure modes**: Stale allowlists, overly broad patterns, silent drift.
- **Pseudocode**:
```pseudo
if proposal.action in ALLOW_ACTIONS and proposal.resource in SAFE_RESOURCES:
    return APPROVE_AUTOMATIC
else:
    return REQUIRE_HUMAN
```

## Explainability
- **Intent**: Make the proposal understandable; surface blast radius and rollback.
- **When**: Before human decision; anytime an automated policy denies.
- **Failure modes**: Missing context, jargon, hidden assumptions.
- **Pseudocode**:
```pseudo
message = render({intent, steps, rollback, risks, prereqs})
log_explanation(proposal.id, message)
```

## Reversibility-First
- **Intent**: Prefer actions with clear rollback and bounded impact.
- **When**: Applying config, migrations, deployments.
- **Failure modes**: Irreversible first steps, missing backups.
- **Pseudocode**:
```pseudo
if not proposal.rollback_plan:
    deny("no rollback")
execute(reversible_subset(proposal))
```

## Rate Limits / Blast Radius
- **Intent**: Throttle changes and constrain scope.
- **When**: Bulk operations, wide config edits, schedule-driven automation.
- **Failure modes**: Queues backing up, unaware of multi-tenant impact.
- **Pseudocode**:
```pseudo
if requests_in_window(actor) > LIMIT: deny("rate limit")
proposal.targets = sample(proposal.targets, BLAST_RADIUS)
```

## Audit Logs / Feedback
- **Intent**: Preserve decisions and outcomes; enable postmortems and tuning.
- **When**: Every proposal, decision, and execution result.
- **Failure modes**: Logs not shipped, PII leakage, unsearchable formats.
- **Pseudocode**:
```pseudo
audit.write({proposal_id, trace_id, stage, decision, reason, timestamp})
```

## Refuse Safely
- **Intent**: Deny with a clear, actionable reason and next steps.
- **When**: Policy violations, missing context, suspected injection/overreach.
- **Failure modes**: Silent failure, vague errors, loops of retries.
- **Pseudocode**:
```pseudo
if suspected_injection(proposal) or missing_context(proposal):
    return deny_with_reason("needs human review", remediations)
```

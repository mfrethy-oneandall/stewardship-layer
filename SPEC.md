# Stewardship Layer Specification

## Actors
- **Agent**: Produces proposals; cannot self-execute without approval.
- **Stewardship Gate**: Mediates proposals, enforces policies, records audit entries.
- **Human Steward**: Reviews explanations, issues APPROVE/DENY.
- **Execution Target**: System being acted upon (e.g., Home Assistant, CI job).

## Interfaces

- **Request**: inbound agent request (intent, params, context).
- **Proposal**: normalized structure {proposal_id, actor, action, resources, rollback_plan, rationale, trace_id}.
- **Decision**: {proposal_id, decision (APPROVE|DENY), reason, approver, timestamp}.
- **ExecutionResult**: {proposal_id, status (SUCCESS|FAILURE|SKIPPED), details, started_at, ended_at}.
- **FeedbackEvent**: {proposal_id, observation, severity, follow_up}.

JSON Schema definitions for Proposal and Decision are available in [schemas/](schemas/).

## State machine
```
          +-----------+
          | Proposed  |
          +-----------+
                |
                v (explain)
          +-----------+
          | Pending   |<-- rate limit/backoff
          +-----------+
          /           \
   (approve)         (deny)
        v              v
+-------------+   +-----------+
| Approved    |   | Rejected  |
+-------------+   +-----------+
        |
        v (execute)
+-------------+
| Executing   |
+-------------+
        |
        v (result)
+-------------+
| Completed   |
+-------------+
        |
        v (feedback)
+-------------+
| Learning    |
+-------------+
```

## Threat model & controls
- **Prompt injection / overreach**: Normalize proposals, strip untrusted instructions, require allowlist match; human confirmation before execution.
- **Privilege escalation**: Run gate with least-privilege credentials; map actions to roles; enforce per-actor rate limits and safe domains.
- **Silent failure**: Mandatory audit logging for every stage; health checks on logger; surfaced reasons on deny.
- **Irreversible actions**: Reversibility-required policy; block if rollback_plan missing or unsafe; prefer dry-runs and staged rollout.

## Metrics
- Approval rate, denial reasons (top N), time-to-decision, execution success rate, rollback incidence, rate-limit hits, audit log durability checks.

## Controls summary
- Human confirmation gate with default DENY.
- Allowlist/safe-domain auto-approval for low-risk operations only.
- Rate limiting and blast-radius sampling on target sets.
- Explainability: human-readable summaries and risk callouts.
- Append-only audit logs with proposal_id and trace_id across stages.
- Feedback loop: execution results feed policy tuning and allowlist updates.

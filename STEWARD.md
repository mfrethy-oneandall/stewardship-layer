# Stewardship Layer

A stewardship layer sits between an agent and the systems it can change. It enforces the loop: **Propose → Explain → Confirm → Execute → Learn**. No action runs without explicit human consent unless it falls inside a pre-declared safe domain with guardrails.

## Behavior contract
- The agent must propose before acting and include intent, scope, and reversibility.
- The layer must explain the proposal in plain language and surface risks.
- A human steward (or policy) must confirm or deny. Default: deny.
- Execution must be scoped, reversible-first, and logged with trace IDs.
- After execution, outcomes are fed back for learning and policy tuning.

## Five-step loop
1. **Propose**: Capture the requested change, affected resources, expected result, and rollback plan.
2. **Explain**: Render the proposal for humans; highlight blast radius, preconditions, and missing info.
3. **Confirm**: Require an explicit APPROVE/DENY; record who decided and why. Allowlists may auto-approve only within safe domains.
4. **Execute**: Perform only the approved actions; apply rate limits and reversible-first sequencing.
5. **Learn**: Record execution results and feedback; adjust policies, alerts, and allowlists.

## Stewardship properties
- Human-in-the-loop by default; zero autonomous mutations outside safe domains.
- Allowlist-driven safety: predefined safe operations and resources.
- Reversible-first: prefer actions with clear rollback and low blast radius.
- Explainable: every decision has a reason string and surfaced risks.
- Audited: append-only logs with proposal IDs, trace IDs, and decision evidence.
- Feedback-aware: decisions and results feed metrics and future tuning.

## Non-goals
- Not an autonomous planner; it never generates actions on its own.
- Not a replacement for access control or secrets management; it assumes least-privilege credentials exist.
- Not a monitoring stack; it emits signals but does not replace observability.

## Quick Integration

For agent developers integrating with the stewardship layer API, see [AGENT_SUMMARY.md](AGENT_SUMMARY.md).

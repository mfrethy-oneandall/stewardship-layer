"""Interactive stewardship demo.

Run from repository root:
    python REFERENCE_IMPL/python/cli_demo.py
"""
from __future__ import annotations

import os
from typing import Callable

from audit_log import AuditLog
from policies import Allowlist, RateLimiter
from stewardship_gate import Decision, Proposal, StewardshipGate


def input_decider(prompt: str) -> bool:
    print("\n--- PROPOSAL ---")
    print(prompt)
    choice = input("Approve? [y/N]: ").strip().lower()
    return choice == "y"


def mock_executor(_: Proposal) -> str:
    return "simulated execution (no side effects)"


def main() -> None:
    allowlist = Allowlist(actions=frozenset({"turn_on", "turn_off"}), resources=frozenset({"porch_light"}))
    safe_domains = {"lighting"}
    rate_limiter = RateLimiter(limit=5, window_seconds=60)
    log_path = os.path.join(os.path.dirname(__file__), "audit_log.jsonl")
    gate = StewardshipGate(AuditLog(log_path), allowlist, safe_domains, rate_limiter)

    proposal = gate.propose(
        actor="agent-alpha",
        action="turn_on",
        resource="porch_light",
        domain="lighting",
        rationale="illuminate entryway for visitor",
        rollback_plan="turn_off after 10 minutes",
    )

    decision: Decision = gate.decide(proposal, approver="human-steward", decision_fn=input_decider)
    execution = gate.execute(proposal, decision, executor=mock_executor)
    gate.learn(proposal, execution, feedback="demo complete")

    print("\nResult:", execution.status, execution.details)
    print("Audit log:", log_path)


if __name__ == "__main__":
    main()

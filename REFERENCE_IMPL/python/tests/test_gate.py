import os
import tempfile
import unittest
import sys
from pathlib import Path

# Ensure local imports resolve when running via pytest from repo root
MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from audit_log import AuditLog  # noqa: E402
from policies import Allowlist, RateLimiter  # noqa: E402
from stewardship_gate import StewardshipGate  # noqa: E402


class StewardshipGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        log_path = os.path.join(self.tmp.name, "audit.jsonl")
        allowlist = Allowlist(actions=frozenset({"turn_on"}), resources=frozenset({"safe_light"}))
        safe_domains = {"lighting"}
        rate_limiter = RateLimiter(limit=2, window_seconds=60)
        self.gate = StewardshipGate(AuditLog(log_path), allowlist, safe_domains, rate_limiter)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_denies_when_human_rejects(self) -> None:
        proposal = self.gate.propose(
            actor="agent",
            action="turn_on",
            resource="unsafe_switch",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
        )
        decision = self.gate.decide(proposal, approver="tester", decision_fn=lambda _: False)
        execution = self.gate.execute(proposal, decision, executor=lambda _: "noop")
        self.gate.learn(proposal, execution)
        self.assertFalse(decision.approved)
        self.assertEqual(execution.status, "SKIPPED")

    def test_auto_approves_allowlisted_safe_domain(self) -> None:
        proposal = self.gate.propose(
            actor="agent",
            action="turn_on",
            resource="safe_light",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
        )
        decision = self.gate.decide(proposal, approver="tester", decision_fn=lambda _: False)
        execution = self.gate.execute(proposal, decision, executor=lambda _: "ok")
        self.gate.learn(proposal, execution)
        self.assertTrue(decision.approved)
        self.assertEqual(execution.status, "SUCCESS")

    def test_audit_log_writes_all_stages(self) -> None:
        proposal = self.gate.propose(
            actor="agent",
            action="turn_on",
            resource="safe_light",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
        )
        decision = self.gate.decide(proposal, approver="tester", decision_fn=lambda _: True)
        execution = self.gate.execute(proposal, decision, executor=lambda _: "ok")
        self.gate.learn(proposal, execution)
        entries = self.gate.audit_log.entries()
        stages = {e.stage for e in entries}
        self.assertTrue({"propose", "explain", "decision", "execute", "learn"}.issubset(stages))


if __name__ == "__main__":
    unittest.main()

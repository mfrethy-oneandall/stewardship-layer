import os
import tempfile
import time
import unittest
import sys
from pathlib import Path

# Ensure local imports resolve when running via pytest from repo root
MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from audit_log import AuditLog  # noqa: E402
from policies import Allowlist, RateLimiter  # noqa: E402
from stewardship_gate import (  # noqa: E402
    ExpectedOutcome,
    StewardshipGate,
    VerifySpec,
)


class StewardshipGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        log_path = os.path.join(self.tmp.name, "audit.jsonl")
        allowlist = Allowlist(
            actions=frozenset({"turn_on", "toggle_entity"}),
            resources=frozenset({"safe_light"}),
        )
        safe_domains = {"lighting"}
        rate_limiter = RateLimiter(limit=2, window_seconds=60)
        self.gate = StewardshipGate(
            AuditLog(log_path),
            allowlist,
            safe_domains,
            rate_limiter,
            decision_ttl_seconds=86400,  # 24h — avoids expiry in tests
        )

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
        self.assertTrue(decision.decision_id.startswith("dc-"))

    def test_auto_approves_allowlisted_safe_domain(self) -> None:
        proposal = self.gate.propose(
            actor="agent",
            action="turn_on",
            resource="safe_light",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
            expected_outcome=ExpectedOutcome(verify=VerifySpec(equals="ok")),
        )
        decision = self.gate.decide(proposal, approver="tester", decision_fn=lambda _: False)
        execution = self.gate.execute(proposal, decision, executor=lambda _: "ok")
        self.gate.learn(proposal, execution)
        self.assertTrue(decision.approved)
        self.assertEqual(execution.status, "SUCCESS")
        self.assertTrue(decision.decision_id.startswith("dc-"))

    def test_audit_log_writes_all_stages(self) -> None:
        proposal = self.gate.propose(
            actor="agent",
            action="turn_on",
            resource="safe_light",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
            expected_outcome=ExpectedOutcome(verify=VerifySpec(equals="ok")),
        )
        decision = self.gate.decide(proposal, approver="tester", decision_fn=lambda _: True)
        execution = self.gate.execute(proposal, decision, executor=lambda _: "ok")
        self.gate.learn(proposal, execution)
        entries = self.gate.audit_log.entries()
        stages = {e.stage for e in entries}
        self.assertTrue({"propose", "explain", "decision", "execute", "learn"}.issubset(stages))
        # decision_id is present in decision audit entries
        decision_entries = [e for e in entries if e.stage == "decision"]
        self.assertTrue(any("decision_id" in e.payload for e in decision_entries))
        # decision_id is present in execute audit entries
        execute_entries = [e for e in entries if e.stage == "execute"]
        self.assertTrue(any("decision_id" in e.payload for e in execute_entries))

    def test_toggle_entity_requires_expected_outcome(self) -> None:
        """toggle_entity without expected_outcome must be REJECTED."""
        proposal = self.gate.propose(
            actor="agent",
            action="toggle_entity",
            resource="safe_light",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
        )
        decision = self.gate.decide(proposal, approver="tester", decision_fn=lambda _: True)
        execution = self.gate.execute(proposal, decision, executor=lambda _: "ok")
        self.assertEqual(execution.status, "REJECTED")
        self.assertIn("expected_outcome", execution.details)

    def test_toggle_entity_with_expected_outcome_succeeds(self) -> None:
        """toggle_entity with explicit expected_outcome proceeds normally."""
        proposal = self.gate.propose(
            actor="agent",
            action="toggle_entity",
            resource="safe_light",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
            expected_outcome=ExpectedOutcome(verify=VerifySpec(equals="toggled")),
        )
        decision = self.gate.decide(proposal, approver="tester", decision_fn=lambda _: True)
        execution = self.gate.execute(proposal, decision, executor=lambda _: "toggled")
        self.assertEqual(execution.status, "SUCCESS")

    def test_decision_ttl_expiry(self) -> None:
        """Expired decisions must return EXPIRED status."""
        gate = StewardshipGate(
            self.gate.audit_log,
            self.gate.allowlist,
            self.gate.safe_domains,
            RateLimiter(limit=10, window_seconds=60),
            decision_ttl_seconds=0,  # instant expiry
        )
        proposal = gate.propose(
            actor="agent",
            action="turn_on",
            resource="safe_light",
            domain="lighting",
            rationale="",
            rollback_plan="turn_off",
        )
        decision = gate.decide(proposal, approver="tester", decision_fn=lambda _: True)
        time.sleep(0.01)  # ensure clock advances past TTL
        execution = gate.execute(proposal, decision, executor=lambda _: "ok")
        self.assertEqual(execution.status, "EXPIRED")
        self.assertIn("TTL", execution.details)


if __name__ == "__main__":
    unittest.main()

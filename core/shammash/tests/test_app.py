"""
Tests for Shammash MVP — POST /execute/proposal.

All HA calls are mocked; no live Home Assistant required.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proposal(
    entity_id: str = "light.test_lamp",
    action_type: str = "toggle_entity",
    blast_radius: str = "single_device",
    verify_entity_id: str | None = None,
    verify_attribute: str = "state",
    verify_equals: str = "on",
    timeout_seconds: int = 5,
) -> dict:
    """Build a valid ExecutionProposal dict."""
    return {
        "schema_version": "v1",
        "proposal_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": {"service": "samuel", "instance": "samuel-1"},
        "action": {
            "domain": "home_assistant",
            "type": action_type,
            "target": {"entity_id": entity_id},
            "parameters": {},
            "metadata": {
                "reversibility": "reversible",
                "blast_radius": blast_radius,
                "safety_tags": [],
            },
            "expected_outcome": {
                "verify": {
                    "entity_id": verify_entity_id or entity_id,
                    "attribute": verify_attribute,
                    "equals": verify_equals,
                },
                "timeout_seconds": timeout_seconds,
            },
        },
        "justification": "Test justification for automated test.",
        "expected_outcome": {},
    }


def _mock_ha_state(entity_id: str, state: str = "on", attributes: dict | None = None):
    """Create a mock HA state response."""
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {},
        "last_changed": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env_and_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up env vars and a temp audit file for each test."""
    audit_path = tmp_path / "audit" / "events.jsonl"
    monkeypatch.setenv("SHAMMASH_INSTANCE", "test-shammash")
    monkeypatch.setenv("HA_URL", "http://ha-test.local:8123")
    monkeypatch.setenv("HA_TOKEN", "test-token-abc")
    monkeypatch.setenv("SHAMMASH_ALLOWLIST", "light.test_lamp,switch.test_switch")
    monkeypatch.setenv("AUDIT_JSONL_PATH", str(audit_path))

    # Reload config in the app module
    import core.shammash.src.app as app_module
    app_module.SHAMMASH_INSTANCE = "test-shammash"
    app_module.HA_URL = "http://ha-test.local:8123"
    app_module.HA_TOKEN = "test-token-abc"
    app_module.SHAMMASH_ALLOWLIST = {"light.test_lamp", "switch.test_switch"}
    app_module.AUDIT_JSONL_PATH = audit_path

    yield

    # Check audit file was written
    if audit_path.exists():
        lines = audit_path.read_text().strip().splitlines()
        for line in lines:
            parsed = json.loads(line)
            assert parsed["schema_version"] == "v1"
            assert parsed["service"] == "shammash"


@pytest.fixture
def client():
    from core.shammash.src.app import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: Denied Proposals
# ---------------------------------------------------------------------------

class TestDeniedProposals:
    """Proposals that should be denied by the law stub."""

    def test_entity_not_in_allowlist(self, client: TestClient):
        """Entity not in SHAMMASH_ALLOWLIST → denied with law.v1.entity_not_allowlisted."""
        proposal = _make_proposal(entity_id="light.forbidden_lamp")
        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "denied"
        assert "law.v1.default_deny" in data["policy_basis"]
        assert "law.v1.entity_not_allowlisted" in data["policy_basis"]
        assert data["verification"]["pass"] is False

    def test_action_type_not_in_enum(self, client: TestClient):
        """set_scene is not in v1 ActionType enum → Pydantic rejects with 422."""
        proposal = _make_proposal(
            entity_id="light.test_lamp",
            action_type="set_scene",
        )
        resp = client.post("/execute/proposal", json=proposal)
        # set_scene was removed from the enum, so Pydantic rejects before Law
        assert resp.status_code == 422

    def test_target_verify_entity_mismatch(self, client: TestClient):
        """target.entity_id != verify.entity_id → denied with law.v1.target_verify_mismatch."""
        proposal = _make_proposal(
            entity_id="light.test_lamp",
            verify_entity_id="switch.test_switch",
        )
        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "denied"
        assert "law.v1.default_deny" in data["policy_basis"]
        assert "law.v1.target_verify_mismatch" in data["policy_basis"]

    def test_no_token_fails_fast(self, client: TestClient):
        """If HA_TOKEN is empty, /execute/proposal returns failed immediately."""
        import core.shammash.src.app as app_module
        app_module.HA_TOKEN = ""

        proposal = _make_proposal(entity_id="light.test_lamp")
        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "failed"
        assert "law.v1.misconfigured.no_token" in data["policy_basis"]
        assert "HA_TOKEN" in data["verification"]["evidence"]

    def test_blast_radius_exceeded(self, client: TestClient):
        """blast_radius=whole_home > policy max (room) → denied."""
        proposal = _make_proposal(
            entity_id="light.test_lamp",
            blast_radius="whole_home",
        )
        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "denied"
        assert "law.v1.blast_radius_exceeded" in data["policy_basis"]

    def test_blast_radius_within_limit(self, client: TestClient):
        """blast_radius=single_device <= policy max (room) → not denied by radius.

        Will fail at HA call (no live HA), but won't be denied for blast radius.
        A denied-for-radius response would mean the check is wrong.
        """
        import core.shammash.src.app as app_module
        # Use an entity NOT in allowlist to confirm blast_radius check
        # happens after allowlist check (law evaluation order: step 5 after step 4).
        # single_device with an allowed entity should pass blast_radius.
        proposal = _make_proposal(
            entity_id="light.test_lamp",
            blast_radius="single_device",
        )
        # If this reaches HA (it won't, test HA is down), it would fail there,
        # but it should NOT be denied for blast_radius.
        resp = client.post("/execute/proposal", json=proposal)
        data = resp.json()
        # Should not be denied for blast radius
        assert "law.v1.blast_radius_exceeded" not in data.get("policy_basis", [])


# ---------------------------------------------------------------------------
# Tests: Allowed Proposals (mocked HA)
# ---------------------------------------------------------------------------

class TestAllowedProposal:
    """Proposals that pass law and execute against mocked HA."""

    @patch("core.shammash.src.app.ha_call_service", new_callable=AsyncMock)
    @patch("core.shammash.src.app.ha_get_state", new_callable=AsyncMock)
    def test_toggle_allowed_and_verified(
        self,
        mock_get_state: AsyncMock,
        mock_call_service: AsyncMock,
        client: TestClient,
    ):
        """Allowed toggle with mocked HA → decision=allowed, verification passes."""
        before = _mock_ha_state("light.test_lamp", state="off")
        after = _mock_ha_state("light.test_lamp", state="on")

        mock_get_state.side_effect = [before, after]
        mock_call_service.return_value = {
            "endpoint": "/api/services/homeassistant/toggle",
            "domain_service": "homeassistant/toggle",
            "payload": {"entity_id": "light.test_lamp"},
            "status_code": 200,
        }

        proposal = _make_proposal(
            entity_id="light.test_lamp",
            action_type="toggle_entity",
            verify_attribute="state",
            verify_equals="on",
        )

        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "allowed"
        assert data["verification"]["pass"] is True
        assert data["before_state"]["state"] == "off"
        assert data["after_state"]["state"] == "on"
        assert "law.v1.allowlist_match" in data["policy_basis"]

        # Improvement #5: evidence includes elapsed/polls
        assert "poll" in data["verification"]["evidence"]

        # Improvement #7: action_taken includes explicit endpoint
        assert data["action_taken"]["endpoint"] == "/api/services/homeassistant/toggle"
        assert data["action_taken"]["domain_service"] == "homeassistant/toggle"
        assert data["action_taken"]["payload"] == {"entity_id": "light.test_lamp"}

    @patch("core.shammash.src.app.ha_call_service", new_callable=AsyncMock)
    @patch("core.shammash.src.app.ha_get_state", new_callable=AsyncMock)
    def test_turn_on_allowed(
        self,
        mock_get_state: AsyncMock,
        mock_call_service: AsyncMock,
        client: TestClient,
    ):
        """turn_on a switch in the allowlist → allowed."""
        before = _mock_ha_state("switch.test_switch", state="off")
        after = _mock_ha_state("switch.test_switch", state="on")

        mock_get_state.side_effect = [before, after]
        mock_call_service.return_value = {
            "endpoint": "/api/services/homeassistant/turn_on",
            "domain_service": "homeassistant/turn_on",
            "payload": {"entity_id": "switch.test_switch"},
            "status_code": 200,
        }

        proposal = _make_proposal(
            entity_id="switch.test_switch",
            action_type="turn_on",
            verify_attribute="state",
            verify_equals="on",
        )

        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "allowed"
        assert data["verification"]["pass"] is True

    @patch("core.shammash.src.app.ha_call_service", new_callable=AsyncMock)
    @patch("core.shammash.src.app.ha_get_state", new_callable=AsyncMock)
    def test_verification_timeout(
        self,
        mock_get_state: AsyncMock,
        mock_call_service: AsyncMock,
        client: TestClient,
    ):
        """Verification times out when state never changes → decision=failed."""
        stuck_state = _mock_ha_state("light.test_lamp", state="off")
        mock_get_state.return_value = stuck_state
        mock_call_service.return_value = {
            "endpoint": "/api/services/homeassistant/toggle",
            "domain_service": "homeassistant/toggle",
            "payload": {"entity_id": "light.test_lamp"},
            "status_code": 200,
        }

        proposal = _make_proposal(
            entity_id="light.test_lamp",
            action_type="toggle_entity",
            verify_attribute="state",
            verify_equals="on",
            timeout_seconds=2,  # short timeout for fast test
        )

        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "failed"
        assert data["verification"]["pass"] is False
        # Improvement #5: timeout evidence includes elapsed + polls
        evidence = data["verification"]["evidence"]
        assert "Timeout" in evidence
        assert "poll" in evidence
        assert "expected 'on'" in evidence
        assert "observed 'off'" in evidence


# ---------------------------------------------------------------------------
# Tests: Invalid Input
# ---------------------------------------------------------------------------

class TestInvalidInput:
    """Malformed requests should return 422."""

    def test_missing_required_field(self, client: TestClient):
        resp = client.post("/execute/proposal", json={"schema_version": "v1"})
        assert resp.status_code == 422

    def test_invalid_entity_id_format(self, client: TestClient):
        proposal = _make_proposal(entity_id="INVALID FORMAT!")
        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 422

    def test_empty_body(self, client: TestClient):
        resp = client.post("/execute/proposal", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Health & Ready Endpoints
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Health check."""

    def test_health(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "shammash"
        assert data["status"] == "ok"


class TestReadyEndpoint:
    """Readiness check (improvement #8)."""

    def test_ready_without_ha(self, client: TestClient):
        """Without live HA, ready should report ha_reachable=False."""
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "shammash"
        assert data["ha_token_configured"] is True  # test token is set
        assert data["ha_reachable"] is False  # test HA URL doesn't exist
        assert data["ready"] is False
        # Never expose the actual token value
        assert "test-token-abc" not in json.dumps(data)

    def test_ready_without_token(self, client: TestClient):
        """Without HA token, ready=False and ha_reachable=False."""
        import core.shammash.src.app as app_module
        app_module.HA_TOKEN = ""
        resp = client.get("/ready")
        data = resp.json()
        assert data["ha_token_configured"] is False
        assert data["ready"] is False


# ---------------------------------------------------------------------------
# Tests: Audit Log
# ---------------------------------------------------------------------------

class TestAuditLog:
    """Audit JSONL is written correctly."""

    def test_denied_proposal_creates_audit_entries(self, client: TestClient):
        """A denied proposal should produce audit events with correct structure."""
        import core.shammash.src.app as app_module

        proposal = _make_proposal(entity_id="light.forbidden_lamp")
        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200

        audit_path = app_module.AUDIT_JSONL_PATH
        assert audit_path.exists()

        lines = audit_path.read_text().strip().splitlines()
        assert len(lines) >= 3  # proposal.in, law_decision, receipt.out

        event_types = [json.loads(line)["event_type"] for line in lines]
        assert "execution_proposal.in" in event_types
        assert "law_decision" in event_types
        assert "execution_receipt.out" in event_types

        # Improvement #4: every event has both request_id and proposal_id
        for line in lines:
            event = json.loads(line)
            assert "request_id" in event["correlation"]
            assert "proposal_id" in event["correlation"]

    def test_audit_does_not_contain_tokens(self, client: TestClient):
        """Improvement #2: audit log must never contain HA tokens or auth secrets."""
        import core.shammash.src.app as app_module

        proposal = _make_proposal(entity_id="light.forbidden_lamp")
        # Add a confirmation_token to verify it gets stripped
        proposal["confirmation_token"] = "secret-confirmation-token"
        proposal["steward_key_token"] = "secret-steward-key"
        resp = client.post("/execute/proposal", json=proposal)
        assert resp.status_code == 200

        audit_path = app_module.AUDIT_JSONL_PATH
        raw = audit_path.read_text()
        assert "test-token-abc" not in raw  # HA token
        assert "secret-confirmation-token" not in raw
        assert "secret-steward-key" not in raw


# ---------------------------------------------------------------------------
# Tests: Secret Sanitization
# ---------------------------------------------------------------------------

class TestSanitization:
    """Improvement #2: HA tokens must never leak."""

    def test_sanitize_error_strips_token(self):
        from core.shammash.src.app import _sanitize_error
        import core.shammash.src.app as app_module

        app_module.HA_TOKEN = "my-secret-token-123"
        exc = Exception("Connection failed with Bearer my-secret-token-123 on host")
        result = _sanitize_error(exc)
        assert "my-secret-token-123" not in result
        assert "[REDACTED]" in result

    def test_sanitize_error_strips_authorization_header(self):
        from core.shammash.src.app import _sanitize_error
        exc = Exception("Headers: {'Authorization': 'Bearer xyzabc123'}")
        result = _sanitize_error(exc)
        assert "xyzabc123" not in result
        assert "[REDACTED]" in result

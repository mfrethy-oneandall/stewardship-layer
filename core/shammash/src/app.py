"""
Shammash MVP — Executive Suite for the Stewardship Stack.

POST /execute/proposal
  Validates proposal → Law check → HA REST call → Verify outcome → Audit → Receipt.

Only Shammash touches Home Assistant.  Everything else is advisory.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional, Union

import yaml

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, conlist


# ---------------------------------------------------------------------------
# Configuration (from env + policy YAML)
# ---------------------------------------------------------------------------
#
# Policy precedence (override, NOT merge):
#   1. If SHAMMASH_ALLOWLIST env var is set and non-empty → use it for entities.
#   2. Else load allow_entities from the policy YAML.
#   3. If neither → empty allowlist (everything denied by default).
#
# The env var WINS — it does not merge with the YAML.  This is by design
# so you can pin entities for a specific deploy without editing YAML.

SHAMMASH_INSTANCE = os.getenv("SHAMMASH_INSTANCE", "shammash-1")
HA_URL = os.getenv("HA_URL", "http://ha.lan:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
AUDIT_JSONL_PATH = Path(
    os.getenv("AUDIT_JSONL_PATH", "shared/audit/events.jsonl")
)

# Verification polling
POLL_INTERVAL_SECONDS = 1.0

# Entity ID format regex for defense-in-depth (matches Pydantic pattern)
_ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

# Blast radius ordering — semantic levels, not string comparison
_BLAST_RADIUS_ORDER = ["single_device", "room", "whole_home", "network_wide"]


# ---------------------------------------------------------------------------
# Policy Loader — YAML parsed once at startup
# ---------------------------------------------------------------------------

def _load_policy() -> dict[str, Any]:
    """
    Load shammash_policy.yaml.  Returns a dict with defaults if the file
    doesn't exist or can't be parsed.
    """
    policy_path = Path(
        os.getenv("SHAMMASH_POLICY_PATH", "shared/policy/v1/shammash_policy.yaml")
    )
    defaults: dict[str, Any] = {
        "default_decision": "deny",
        "allow_actions": ["toggle_entity", "turn_on", "turn_off"],
        "allow_entities": [],
        "enforce_target_verify_equality": True,
        "max_blast_radius": "room",
        "verification": {
            "max_timeout_seconds": 60,
            "default_timeout_seconds": 10,
            "poll_interval_seconds": 1,
        },
    }
    if not policy_path.exists():
        return defaults
    try:
        with open(policy_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # Merge missing keys from defaults
        for key, val in defaults.items():
            data.setdefault(key, val)
        return data
    except Exception as exc:
        warnings.warn(f"Failed to parse policy YAML ({policy_path}): {exc}")
        return defaults


# Load policy once at import time
_POLICY = _load_policy()

# Allowed action types — from policy YAML
ALLOWED_ACTION_TYPES: set[str] = set(_POLICY.get("allow_actions", []))

# Entity allowlist — env var overrides YAML (not merged)
_env_allowlist = os.getenv("SHAMMASH_ALLOWLIST", "").strip()
if _env_allowlist:
    SHAMMASH_ALLOWLIST: set[str] = set(
        e.strip() for e in _env_allowlist.split(",") if e.strip()
    )
else:
    SHAMMASH_ALLOWLIST: set[str] = set(_POLICY.get("allow_entities", []))

# policy-level caps
POLICY_MAX_BLAST_RADIUS: str = _POLICY.get("max_blast_radius", "room")
POLICY_MAX_TIMEOUT: int = _POLICY.get("verification", {}).get("max_timeout_seconds", 60)
POLICY_ENFORCE_TARGET_VERIFY: bool = _POLICY.get("enforce_target_verify_equality", True)


# ---------------------------------------------------------------------------
# Secret Sanitization
# ---------------------------------------------------------------------------

def _sanitize_error(exc: Exception) -> str:
    """
    Sanitize an exception message to ensure HA tokens and auth headers
    are never leaked into audit logs or receipts.
    """
    msg = str(exc)
    if HA_TOKEN and HA_TOKEN in msg:
        msg = msg.replace(HA_TOKEN, "[REDACTED]")
    # Strip any Bearer tokens that might appear in httpx error messages
    msg = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", msg)
    # Strip any Authorization header values
    msg = re.sub(r"['\"]?Authorization['\"]?\s*:\s*['\"]?[^'\"}\]]+['\"]?", "Authorization: [REDACTED]", msg)
    return msg


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    """v1 action types.  Only toggle/on/off are implemented and allowed by Law."""
    toggle_entity = "toggle_entity"
    turn_on = "turn_on"
    turn_off = "turn_off"


class ActionTarget(BaseModel):
    entity_id: str = Field(pattern=r"^[a-z0-9_]+\.[a-z0-9_]+$")


class ActionParameters(BaseModel):
    value: Optional[Union[float, int, str, bool, None]] = None
    min: Optional[Union[float, int]] = None
    max: Optional[Union[float, int]] = None

    model_config = {"extra": "forbid"}


class ActionMetadata(BaseModel):
    reversibility: Literal["reversible", "semi", "irreversible"]
    blast_radius: Literal["single_device", "room", "whole_home", "network_wide"]
    safety_tags: conlist(str, max_length=10) = []

    model_config = {"extra": "forbid"}


class VerifySpec(BaseModel):
    entity_id: str = Field(pattern=r"^[a-z0-9_]+\.[a-z0-9_]+$")
    attribute: str = Field(max_length=64)
    equals: Optional[Union[str, float, int, bool, None]] = None

    model_config = {"extra": "forbid"}


class ExpectedOutcome(BaseModel):
    verify: VerifySpec
    timeout_seconds: int = Field(ge=1, le=120)

    model_config = {"extra": "forbid"}


class HAAction(BaseModel):
    domain: Literal["home_assistant"]
    type: ActionType
    target: ActionTarget
    parameters: ActionParameters = Field(default_factory=ActionParameters)
    metadata: ActionMetadata
    expected_outcome: ExpectedOutcome

    model_config = {"extra": "forbid"}


class Source(BaseModel):
    service: str
    instance: str

    model_config = {"extra": "forbid"}


class ExecutionProposal(BaseModel):
    schema_version: Literal["v1"]
    proposal_id: str  # uuid
    request_id: str   # uuid
    timestamp: str     # ISO 8601
    source: Source
    action: HAAction
    justification: str = Field(min_length=1, max_length=600)
    confirmation_token: Optional[str] = Field(default=None, max_length=500)
    steward_key_token: Optional[str] = Field(default=None, max_length=500)
    expected_outcome: Optional[dict[str, Any]] = None

    model_config = {"extra": "forbid"}


class Verification(BaseModel):
    pass_: bool = Field(alias="pass")
    evidence: str = Field(max_length=1500)

    model_config = {"extra": "forbid", "populate_by_name": True}


class ExecutionReceipt(BaseModel):
    schema_version: Literal["v1"] = "v1"
    proposal_id: str
    timestamp: str
    source: dict[str, str]
    decision: Literal["allowed", "denied", "allowed_with_conditions", "failed"]
    policy_basis: list[str]
    action_taken: Optional[dict[str, Any]] = None
    verification: Verification
    before_state: Optional[dict[str, Any]] = None
    after_state: Optional[dict[str, Any]] = None
    audit_ref: str
    failure_language_hint: Optional[str] = None

    model_config = {"extra": "forbid"}


class AuditEvent(BaseModel):
    schema_version: Literal["v1"] = "v1"
    event_id: str
    timestamp: str
    service: Literal["samuel", "nathan", "openclaw", "shammash"]
    event_type: str
    correlation: dict[str, str]
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Audit Logger — append-only JSONL
# ---------------------------------------------------------------------------

def _ensure_audit_dir() -> None:
    """Create audit directory if it doesn't exist (mkdir -p)."""
    AUDIT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)


def append_audit_event(event: AuditEvent) -> None:
    """
    Append a single audit event as one JSON line.  Best-effort, single write.

    Improvement #3: single .write() + .flush() so each line is atomic-ish
    even without file locks (single instance for v1).
    """
    _ensure_audit_dir()
    line = event.model_dump_json() + "\n"
    with open(AUDIT_JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


def _make_audit_event(
    event_type: str,
    request_id: str,
    proposal_id: str,
    payload: dict[str, Any],
) -> AuditEvent:
    """
    Build an AuditEvent.  Always includes both request_id and proposal_id
    in correlation (improvement #4).
    """
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        service="shammash",
        event_type=event_type,
        correlation={
            "request_id": request_id,
            "proposal_id": proposal_id,
        },
        payload=payload,
    )


def _sanitize_proposal_for_audit(proposal: ExecutionProposal) -> dict[str, Any]:
    """
    Dump a proposal for audit, stripping tokens that could contain secrets
    (improvement #2: never log secrets).
    """
    data = proposal.model_dump()
    # Strip tokens — they may contain steward keys or confirmation codes
    data.pop("confirmation_token", None)
    data.pop("steward_key_token", None)
    return data


# ---------------------------------------------------------------------------
# Law Engine
# ---------------------------------------------------------------------------

class LawDecision:
    """Result of the Law check."""

    def __init__(self, allowed: bool, policy_basis: list[str], reason: str = ""):
        self.allowed = allowed
        self.policy_basis = policy_basis
        self.reason = reason


def _blast_radius_level(radius: str) -> int:
    """Return the ordinal level of a blast radius (higher = wider scope)."""
    try:
        return _BLAST_RADIUS_ORDER.index(radius)
    except ValueError:
        return len(_BLAST_RADIUS_ORDER)  # unknown = treat as worst case


def evaluate_law(proposal: ExecutionProposal) -> LawDecision:
    """
    Law engine.  Default deny.  All deny conditions run before any allow.

    Evaluation order (strict — no short-circuit to allow):
      1) entity_id format valid (defense-in-depth)
      2) target.entity_id == verify.entity_id
      3) action.type in ALLOWED_ACTION_TYPES
      4) entity_id in SHAMMASH_ALLOWLIST
      5) blast_radius <= POLICY_MAX_BLAST_RADIUS (semantic ordering)

    If ALL pass → allow.  Rule IDs use law.v1.* namespace.
    """
    action = proposal.action
    entity_id = action.target.entity_id
    verify_entity_id = action.expected_outcome.verify.entity_id
    action_type = action.type.value

    # 1) Defense-in-depth: entity_id format check
    if not _ENTITY_ID_RE.match(entity_id):
        return LawDecision(
            allowed=False,
            policy_basis=["law.v1.default_deny", "law.v1.invalid_entity_format"],
            reason=f"Entity ID '{entity_id}' does not match required format",
        )
    if not _ENTITY_ID_RE.match(verify_entity_id):
        return LawDecision(
            allowed=False,
            policy_basis=["law.v1.default_deny", "law.v1.invalid_entity_format"],
            reason=f"Verify entity ID '{verify_entity_id}' does not match required format",
        )

    # 2) target == verify entity (no cross-entity tricks)
    if POLICY_ENFORCE_TARGET_VERIFY and entity_id != verify_entity_id:
        return LawDecision(
            allowed=False,
            policy_basis=["law.v1.default_deny", "law.v1.target_verify_mismatch"],
            reason=(
                f"target.entity_id ({entity_id}) != "
                f"verify.entity_id ({verify_entity_id}). "
                "In v1 they must match."
            ),
        )

    # 3) action type is allowed by policy
    if action_type not in ALLOWED_ACTION_TYPES:
        return LawDecision(
            allowed=False,
            policy_basis=["law.v1.default_deny", "law.v1.action_not_allowed"],
            reason=f"Action type '{action_type}' is not in allowed set: {sorted(ALLOWED_ACTION_TYPES)}",
        )

    # 4) entity is in allowlist
    if entity_id not in SHAMMASH_ALLOWLIST:
        return LawDecision(
            allowed=False,
            policy_basis=["law.v1.default_deny", "law.v1.entity_not_allowlisted"],
            reason=f"Entity '{entity_id}' is not in SHAMMASH_ALLOWLIST",
        )

    # 5) blast radius within policy limits (semantic ordering)
    action_radius = action.metadata.blast_radius
    if _blast_radius_level(action_radius) > _blast_radius_level(POLICY_MAX_BLAST_RADIUS):
        return LawDecision(
            allowed=False,
            policy_basis=["law.v1.default_deny", "law.v1.blast_radius_exceeded"],
            reason=(
                f"Blast radius '{action_radius}' exceeds policy max "
                f"'{POLICY_MAX_BLAST_RADIUS}'"
            ),
        )

    # --- All deny checks passed → allow ---
    return LawDecision(
        allowed=True,
        policy_basis=[
            "law.v1.allowlist_match",
            f"entity={entity_id}",
            f"type={action_type}",
        ],
    )


# ---------------------------------------------------------------------------
# Home Assistant REST Client
# ---------------------------------------------------------------------------

def _ha_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


# HA service routing table — maps action type to service path.
# v1: only toggle/on/off.  When Law allows new types, add them here.
_HA_SERVICE_MAP: dict[str, str] = {
    "toggle_entity": "homeassistant/toggle",
    "turn_on": "homeassistant/turn_on",
    "turn_off": "homeassistant/turn_off",
}


async def ha_get_state(entity_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
    """GET /api/states/{entity_id} → full state dict."""
    resp = await client.get(
        f"{HA_URL}/api/states/{entity_id}",
        headers=_ha_headers(),
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


async def ha_call_service(action: HAAction, client: httpx.AsyncClient) -> dict[str, Any]:
    """
    Call the appropriate HA service based on action.type.

    v1 supports only toggle_entity, turn_on, turn_off — matching Law's
    ALLOWED_ACTION_TYPES exactly.  No dead-code paths.

    Returns a dict with the exact endpoint, domain/service, payload (minus
    secrets), and status code — so receipts are actually receipts.
    """
    entity_id = action.target.entity_id
    action_type = action.type.value

    if action_type not in _HA_SERVICE_MAP:
        raise ValueError(f"Unknown action type: {action_type}")

    service_path = _HA_SERVICE_MAP[action_type]
    payload = {"entity_id": entity_id}
    url = f"{HA_URL}/api/services/{service_path}"

    resp = await client.post(
        url,
        headers=_ha_headers(),
        json=payload,
        timeout=10.0,
    )
    resp.raise_for_status()

    return {
        "endpoint": f"/api/services/{service_path}",
        "domain_service": service_path,
        "payload": payload,
        "status_code": resp.status_code,
    }


# ---------------------------------------------------------------------------
# Verification — poll until expected state or timeout
# ---------------------------------------------------------------------------

async def verify_outcome(expected: ExpectedOutcome) -> tuple[bool, str, dict[str, Any]]:
    """
    Poll HA state until expected_outcome matches or timeout.

    Per user feedback #3 (round 1):
      attribute == "state" → read top-level "state" key
      otherwise           → read attributes[attribute]

    Timeout is clamped to POLICY_MAX_TIMEOUT so proposals cannot request
    arbitrarily long verification windows.

    Returns (passed, evidence_string, final_state_dict).
    """
    verify = expected.verify
    loop = asyncio.get_event_loop()
    # Clamp timeout to policy max — never trust the proposal's value
    effective_timeout = min(expected.timeout_seconds, POLICY_MAX_TIMEOUT)
    deadline = loop.time() + effective_timeout
    start_time = loop.time()
    last_state: dict[str, Any] = {}
    poll_count = 0

    while loop.time() < deadline:
        poll_count += 1
        try:
            state_data = await ha_get_state(verify.entity_id, _get_http_client())
            last_state = state_data

            # Extract the value to compare
            if verify.attribute == "state":
                actual = state_data.get("state")
            else:
                actual = state_data.get("attributes", {}).get(verify.attribute)

            # Coerce types for comparison (HA returns strings for most values)
            expected_val = verify.equals
            if isinstance(expected_val, bool):
                passed = actual == expected_val or str(actual).lower() == str(expected_val).lower()
            elif isinstance(expected_val, (int, float)):
                try:
                    passed = float(actual) == float(expected_val)
                except (TypeError, ValueError):
                    passed = False
            else:
                passed = str(actual) == str(expected_val)

            if passed:
                elapsed = round(loop.time() - start_time, 2)
                return (
                    True,
                    f"Verified: {verify.entity_id}.{verify.attribute} "
                    f"expected {expected_val!r}; observed {actual!r} "
                    f"after {elapsed}s ({poll_count} poll{'s' if poll_count != 1 else ''})",
                    last_state,
                )

        except Exception as exc:
            last_state = {"error": _sanitize_error(exc)}

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # Timeout — build a rich evidence string (improvement #5)
    elapsed = round(loop.time() - start_time, 2)
    if verify.attribute == "state":
        final_actual = last_state.get("state", "<unknown>")
    else:
        final_actual = last_state.get("attributes", {}).get(verify.attribute, "<unknown>")

    return (
        False,
        f"Timeout: {verify.entity_id}.{verify.attribute} "
        f"expected {verify.equals!r}; observed {final_actual!r} "
        f"after {elapsed}s ({poll_count} poll{'s' if poll_count != 1 else ''})",
        last_state,
    )


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared httpx.AsyncClient — created once, reused for connection pooling.
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx client.  Falls back to a fresh client in tests."""
    if _http_client is not None:
        return _http_client
    # Fallback for tests that don't go through lifespan
    return httpx.AsyncClient()


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Create shared httpx client and ensure audit directory at startup."""
    global _http_client
    _ensure_audit_dir()
    _http_client = httpx.AsyncClient()
    try:
        yield
    finally:
        await _http_client.aclose()
        _http_client = None


app = FastAPI(
    title="Shammash",
    description="Executive suite for the Stewardship Stack. Only Shammash touches Home Assistant.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {
        "service": "shammash",
        "instance": SHAMMASH_INSTANCE,
        "status": "ok",
        "allowlist_size": len(SHAMMASH_ALLOWLIST),
    }


@app.get("/ready")
async def ready():
    """
    Readiness check (improvement #8).

    Reports whether Shammash can actually serve proposals:
      - Is HA_TOKEN configured?
      - Is HA_URL reachable?

    Returns 200 with ready=true/false.  Never exposes the token.
    """
    checks: dict[str, Any] = {
        "service": "shammash",
        "instance": SHAMMASH_INSTANCE,
        "ha_token_configured": bool(HA_TOKEN),
        "ha_url": HA_URL,
    }

    # Probe HA reachability with a lightweight GET /api/
    ha_reachable = False
    if HA_TOKEN:
        try:
            client = _get_http_client()
            resp = await client.get(
                f"{HA_URL}/api/",
                headers=_ha_headers(),
                timeout=5.0,
            )
            ha_reachable = resp.status_code == 200
        except Exception:
            ha_reachable = False

    checks["ha_reachable"] = ha_reachable
    checks["ready"] = bool(HA_TOKEN) and ha_reachable

    return checks


@app.post("/execute/proposal", response_model=ExecutionReceipt)
async def execute_proposal(proposal: ExecutionProposal):
    """
    Receive an ExecutionProposal, run it through Law, execute via HA REST,
    verify outcome, log audit events, and return an ExecutionReceipt.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    request_id = proposal.request_id
    proposal_id = proposal.proposal_id
    client = _get_http_client()

    # --- 0. Fail fast if HA_TOKEN is not configured ---
    if not HA_TOKEN:
        receipt = ExecutionReceipt(
            proposal_id=proposal_id,
            timestamp=now_iso,
            source={"service": "shammash", "instance": SHAMMASH_INSTANCE},
            decision="failed",
            policy_basis=["law.v1.misconfigured.no_token"],
            verification=Verification(**{
                "pass": False,
                "evidence": "HA_TOKEN is not configured. Cannot reach Home Assistant.",
            }),
            audit_ref=f"audit:{proposal_id}",
            failure_language_hint="Shammash is misconfigured: HA_TOKEN is empty.",
        )
        append_audit_event(_make_audit_event(
            event_type="execution_receipt.out",
            request_id=request_id,
            proposal_id=proposal_id,
            payload=receipt.model_dump(by_alias=True),
        ))
        return receipt

    # --- 1. Audit: proposal received (improvement #2: sanitized, no secrets) ---
    append_audit_event(_make_audit_event(
        event_type="execution_proposal.in",
        request_id=request_id,
        proposal_id=proposal_id,
        payload=_sanitize_proposal_for_audit(proposal),
    ))

    # --- 2. Law check ---
    law = evaluate_law(proposal)

    append_audit_event(_make_audit_event(
        event_type="law_decision",
        request_id=request_id,
        proposal_id=proposal_id,
        payload={
            "allowed": law.allowed,
            "policy_basis": law.policy_basis,
            "reason": law.reason,
        },
    ))

    if not law.allowed:
        receipt = ExecutionReceipt(
            proposal_id=proposal_id,
            timestamp=now_iso,
            source={"service": "shammash", "instance": SHAMMASH_INSTANCE},
            decision="denied",
            policy_basis=law.policy_basis,
            verification=Verification(**{"pass": False, "evidence": law.reason}),
            audit_ref=f"audit:{proposal_id}",
            failure_language_hint=law.reason,
        )
        append_audit_event(_make_audit_event(
            event_type="execution_receipt.out",
            request_id=request_id,
            proposal_id=proposal_id,
            payload=receipt.model_dump(by_alias=True),
        ))
        return receipt

    # --- 3. GET before state ---
    entity_id = proposal.action.target.entity_id
    try:
        before_state = await ha_get_state(entity_id, client)
    except Exception as exc:
        safe_msg = _sanitize_error(exc)
        receipt = ExecutionReceipt(
            proposal_id=proposal_id,
            timestamp=now_iso,
            source={"service": "shammash", "instance": SHAMMASH_INSTANCE},
            decision="failed",
            policy_basis=law.policy_basis,
            verification=Verification(**{
                "pass": False,
                "evidence": f"Failed to read before-state: {safe_msg}",
            }),
            audit_ref=f"audit:{proposal_id}",
            failure_language_hint=f"Could not reach HA to read state for {entity_id}",
        )
        append_audit_event(_make_audit_event(
            event_type="execution_receipt.out",
            request_id=request_id,
            proposal_id=proposal_id,
            payload=receipt.model_dump(by_alias=True),
        ))
        return receipt

    # --- 4. Execute service call ---
    append_audit_event(_make_audit_event(
        event_type="execution_attempt",
        request_id=request_id,
        proposal_id=proposal_id,
        payload={
            "action_type": proposal.action.type.value,
            "entity_id": entity_id,
        },
    ))

    try:
        service_result = await ha_call_service(proposal.action, client)
    except Exception as exc:
        safe_msg = _sanitize_error(exc)
        receipt = ExecutionReceipt(
            proposal_id=proposal_id,
            timestamp=now_iso,
            source={"service": "shammash", "instance": SHAMMASH_INSTANCE},
            decision="failed",
            policy_basis=law.policy_basis,
            verification=Verification(**{
                "pass": False,
                "evidence": f"Service call failed: {safe_msg}",
            }),
            before_state=before_state,
            audit_ref=f"audit:{proposal_id}",
            failure_language_hint=f"HA service call failed for {entity_id}",
        )
        append_audit_event(_make_audit_event(
            event_type="execution_receipt.out",
            request_id=request_id,
            proposal_id=proposal_id,
            payload=receipt.model_dump(by_alias=True),
        ))
        return receipt

    # --- 5. Verify outcome ---
    passed, evidence, after_state = await verify_outcome(proposal.action.expected_outcome)

    decision = "allowed" if passed else "failed"

    # Improvement #7: action_taken includes exact endpoint, domain/service, payload
    receipt = ExecutionReceipt(
        proposal_id=proposal_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        source={"service": "shammash", "instance": SHAMMASH_INSTANCE},
        decision=decision,
        policy_basis=law.policy_basis,
        action_taken={
            "type": proposal.action.type.value,
            "entity_id": entity_id,
            "endpoint": service_result.get("endpoint"),
            "domain_service": service_result.get("domain_service"),
            "payload": service_result.get("payload"),
            "status_code": service_result.get("status_code"),
        },
        verification=Verification(**{"pass": passed, "evidence": evidence}),
        before_state=before_state,
        after_state=after_state,
        audit_ref=f"audit:{proposal_id}",
        failure_language_hint=evidence if not passed else None,
    )

    # --- 6. Audit: receipt ---
    append_audit_event(_make_audit_event(
        event_type="execution_receipt.out",
        request_id=request_id,
        proposal_id=proposal_id,
        payload=receipt.model_dump(by_alias=True),
    ))

    return receipt

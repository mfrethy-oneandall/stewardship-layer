"""Stewardship policies: allowlist, safe domains, rate limits, reversibility."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class Allowlist:
    actions: frozenset[str]
    resources: frozenset[str]


@dataclass
class RateLimiter:
    limit: int
    window_seconds: float
    _hits: dict[str, list[float]]

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits = {}

    def accept(self, actor: str, now: float | None = None) -> PolicyDecision:
        now = now or time.time()
        window_start = now - self.window_seconds
        hits = self._hits.setdefault(actor, [])
        hits[:] = [ts for ts in hits if ts >= window_start]
        if len(hits) >= self.limit:
            return PolicyDecision(False, "rate limit exceeded")
        hits.append(now)
        return PolicyDecision(True, "within rate limit")


def allowlist_policy(action: str, resource: str, allowlist: Allowlist) -> PolicyDecision:
    if action in allowlist.actions and resource in allowlist.resources:
        return PolicyDecision(True, "allowlisted")
    return PolicyDecision(False, "not allowlisted")


def safe_domain_policy(domain: str, safe_domains: Iterable[str]) -> PolicyDecision:
    if domain in safe_domains:
        return PolicyDecision(True, "safe domain")
    return PolicyDecision(False, "domain requires confirmation")


def reversibility_required(has_rollback: bool) -> PolicyDecision:
    if has_rollback:
        return PolicyDecision(True, "rollback available")
    return PolicyDecision(False, "missing rollback plan")


def explain_policy_results(results: Mapping[str, PolicyDecision]) -> str:
    return "; ".join(f"{name}: {pd.reason}" for name, pd in results.items())

"""Append-only JSON Lines audit logger.

Lightweight, dependency-free; each call writes a single line so it can survive process crashes.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, TextIO


@dataclass(frozen=True)
class AuditEntry:
    proposal_id: str
    trace_id: str
    stage: str
    payload: Dict[str, Any]
    timestamp: float


class AuditLog:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def append(self, entry: AuditEntry) -> None:
        line = json.dumps(asdict(entry), separators=(",", ":"))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def entries(self) -> list[AuditEntry]:
        if not os.path.exists(self.path):
            return []
        results: list[AuditEntry] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for raw in fh:
                data = json.loads(raw)
                results.append(
                    AuditEntry(
                        proposal_id=data["proposal_id"],
                        trace_id=data["trace_id"],
                        stage=data["stage"],
                        payload=data.get("payload", {}),
                        timestamp=float(data["timestamp"]),
                    )
                )
        return results


def now_ts() -> float:
    return time.time()

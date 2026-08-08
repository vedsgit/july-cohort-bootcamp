from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4


@dataclass(frozen=True)
class AuditEvent:
    audit_id: str
    occurred_at: datetime
    trace_id: str
    request_id: str
    actor_id: str
    tenant_id: str
    tool_name: str
    outcome: str
    reason_code: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["occurred_at"] = self.occurred_at.isoformat()
        return payload


class AuditSink(Protocol):
    events: list[AuditEvent]
    path: Path | None

    def record(
        self,
        *,
        trace_id: str,
        request_id: str,
        actor_id: str,
        tenant_id: str,
        tool_name: str,
        outcome: str,
        reason_code: str,
        details: dict[str, Any] | None = None,
    ) -> str: ...


class InMemoryAuditSink:
    """Test / ephemeral sink (no durable file)."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self.path: Path | None = None

    def record(
        self,
        *,
        trace_id: str,
        request_id: str,
        actor_id: str,
        tenant_id: str,
        tool_name: str,
        outcome: str,
        reason_code: str,
        details: dict[str, Any] | None = None,
    ) -> str:
        event = _new_event(
            trace_id=trace_id,
            request_id=request_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            tool_name=tool_name,
            outcome=outcome,
            reason_code=reason_code,
            details=details,
        )
        self.events.append(event)
        return event.audit_id


class JsonlFileAuditSink:
    """
    Append-only JSONL audit log — the classroom stand-in for a prod audit trail
    (CloudWatch / SIEM / immutable object store would replace the file later).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[AuditEvent] = []

    def record(
        self,
        *,
        trace_id: str,
        request_id: str,
        actor_id: str,
        tenant_id: str,
        tool_name: str,
        outcome: str,
        reason_code: str,
        details: dict[str, Any] | None = None,
    ) -> str:
        event = _new_event(
            trace_id=trace_id,
            request_id=request_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            tool_name=tool_name,
            outcome=outcome,
            reason_code=reason_code,
            details=details,
        )
        self.events.append(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_json_dict(), default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event.audit_id


def default_audit_log_path() -> Path:
    """Project-local durable log: <project>/logs/audit.jsonl"""
    # support_agent/audit.py → src → project root
    project_root = Path(__file__).resolve().parents[2]
    override = os.getenv("GOVERNED_AUDIT_LOG")
    if override:
        return Path(override).expanduser().resolve()
    return project_root / "logs" / "audit.jsonl"


def build_audit_sink(path: str | Path | None = None) -> AuditSink:
    """
    path=None  → in-memory only (unit tests)
    path set   → JSONL file + in-memory mirror (demos / prod-shaped)
    """
    if path is None:
        return InMemoryAuditSink()
    return JsonlFileAuditSink(path)


def _new_event(
    *,
    trace_id: str,
    request_id: str,
    actor_id: str,
    tenant_id: str,
    tool_name: str,
    outcome: str,
    reason_code: str,
    details: dict[str, Any] | None,
) -> AuditEvent:
    return AuditEvent(
        audit_id=f"aud_{uuid4().hex[:12]}",
        occurred_at=datetime.now(timezone.utc),
        trace_id=trace_id,
        request_id=request_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        tool_name=tool_name,
        outcome=outcome,
        reason_code=reason_code,
        details=details or {},
    )

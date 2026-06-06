from fastapi import APIRouter
from pydantic import BaseModel, field_validator
from ..state import _state
from ..helpers import (
    _permission_audit_entries, _summarize_permission_audit,
    _append_permission_audit,
)

router = APIRouter()


class PermissionAuditRequest(BaseModel):
    source: str
    decision: str
    mode: str
    tool: str | None = None
    agent: str | None = None
    reason: str | None = None
    input_summary: str | None = None

    @field_validator("source")
    @classmethod
    def _chk_source(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("source required")
        if len(v) > 100:
            raise ValueError("source too long (max 100)")
        return v

    @field_validator("decision")
    @classmethod
    def _chk_decision(cls, v: str) -> str:
        allowed = {"allow", "deny", "ask", "bypass"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(f"decision must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("mode")
    @classmethod
    def _chk_mode(cls, v: str) -> str:
        allowed = {"default", "plan", "bypasspermissions", "auto"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(f"mode must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("tool", "agent", "reason", "input_summary")
    @classmethod
    def _normalize_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 500:
            raise ValueError("field too long (max 500)")
        return v


@router.get("/api/permissions/audit")
async def api_permissions_audit(last: int = 50):
    bounded_last = max(1, min(last, 500))
    entries = _permission_audit_entries(limit=bounded_last)
    return {
        "entries": entries,
        "summary": _summarize_permission_audit(entries),
    }


@router.post("/api/permissions/audit")
async def api_permissions_audit_log(req: PermissionAuditRequest):
    entry = _append_permission_audit(req.model_dump())
    return {
        "ok": True,
        "entry": entry,
        "summary": _state["permission_audit_summary"],
    }

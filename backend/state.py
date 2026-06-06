"""
Shared mutable state and WebSocket broadcast helpers.

All modules that need to read or write dashboard state import from here.
Scalars (_trending_cache_time, _ov_last_restart) must be updated via their
module reference (e.g. `import state; state._trending_cache_time = x`) so
the assignment is visible to all importers.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

# ---------------------------------------------------------------------------
# Shared dashboard state — populated by the background poll loop
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {
    "services": {},
    "agents": [],
    "cron_jobs": [],
    "memories": [],
    "memory_summary": {},
    "memory_events": [],
    "llm_models": [],
    "llm_active": None,
    "memory_monitor_log": [],
    "logs": {"mlx": [], "memory": []},
    "amp_messages": [],
    "hermes_status": {},
    "voice_active": False,
    "last_updated": None,
    "system": {},
    "trending_repos": [],
    "service_history": {},
    "routing_summary": {},
    "permission_audit_summary": {},
    "agent_messages": [],
    "signal_watcher": {},
    "security_posture": {},
}

# Separate mutable scalars — update as `state._trending_cache_time = x`
_trending_cache_time: float = 0.0
_ov_last_restart: float = 0.0

# Insights feed (last 20 from mesh-subconscious)
_insights: list[dict] = []

# Morning brief cache
_brief_cache: dict[str, Any] = {"text": "", "generated_at": None}

# ---------------------------------------------------------------------------
# WebSocket client registry
# ---------------------------------------------------------------------------

_ws_clients: set[WebSocket] = set()
_ws_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------

async def broadcast_status() -> None:
    payload = {
        "type": "status_update",
        "timestamp": _now_iso(),
        "services": _state["services"],
        "agents": _state["agents"],
        "cron_jobs": _state["cron_jobs"],
        "memories": _state["memories"],
        "memory_summary": _state["memory_summary"],
        "memory_events": _state["memory_events"],
        "llm_active": _state["llm_active"],
        "voice_active": _state["voice_active"],
        "system": _state["system"],
        "memory_monitor_log": _state["memory_monitor_log"],
        "logs": _state["logs"],
        "amp_messages": _state["amp_messages"],
        "hermes_status": _state["hermes_status"],
        "trending_repos": _state["trending_repos"],
        "service_history": _state["service_history"],
        "routing_summary": _state["routing_summary"],
        "permission_audit_summary": _state["permission_audit_summary"],
        "agent_messages": _state["agent_messages"],
        "signal_watcher": _state["signal_watcher"],
        "security_posture": _state["security_posture"],
    }
    data = json.dumps(payload)
    async with _ws_lock:
        dead: set[WebSocket] = set()
        for ws in _ws_clients:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        _ws_clients.difference_update(dead)


async def broadcast_insight(insight: dict) -> None:
    data = json.dumps({"type": "insight", "insight": insight})
    async with _ws_lock:
        dead: set[WebSocket] = set()
        for ws in _ws_clients:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        _ws_clients.difference_update(dead)

"""
Mission Control Dashboard — FastAPI Backend
Real-time backend for local AI mesh monitoring.
Port: 8000
"""
import asyncio
import collections
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import SESSIONS_DB, POLL_INTERVAL, MAX_WS_CONNECTIONS
from . import state as _st
from .state import _state, _insights, _now_iso, broadcast_status
from .background import run_poll_loop, run_openviking_watchdog, run_generate_brief_on_startup
from .helpers import _refresh_agent_messages, _seconds_until

# Routers
from .routers import (
    agents, memory, hermes, system, cron,
    routing, sessions, insights, permissions, rag, chat, crew,
)

# ---------------------------------------------------------------------------
# History ring buffer (AC4) — 1 snapshot/min, 24h max
# ---------------------------------------------------------------------------

_HISTORY_MAX = 1440  # 1 per minute × 60 min × 24 h
_history: collections.deque = collections.deque(maxlen=_HISTORY_MAX)


async def _snapshot_loop() -> None:
    """Appends a state snapshot every 60s for the timeline scrubber."""
    while True:
        await asyncio.sleep(60)
        if _state.get("last_updated"):
            _history.append({
                "ts": _now_iso(),
                "services": dict(_state["services"]),
                "agents": list(_state["agents"]),
                "routing_summary": dict(_state["routing_summary"]),
                "system": dict(_state["system"]),
                "signal_watcher": dict(_state["signal_watcher"]),
            })


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

def _init_sessions_db() -> None:
    with sqlite3.connect(SESSIONS_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                ts TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON session_log(date)")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _init_sessions_db()
    _refresh_agent_messages()
    asyncio.create_task(run_poll_loop())
    asyncio.create_task(run_openviking_watchdog())
    asyncio.create_task(run_generate_brief_on_startup())
    asyncio.create_task(_snapshot_loop())
    asyncio.create_task(crew.run_hermes_feed())
    asyncio.create_task(crew.run_amp_watch())
    asyncio.create_task(crew.run_crew_idle_decay())
    print(f"[startup] Mission Control backend on :8000 — polling every {POLL_INTERVAL}s", flush=True)
    yield


app = FastAPI(
    title="Mission Control Dashboard API",
    description="Real-time backend for local AI mesh monitoring",
    version="2.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

for router_module in (agents, memory, hermes, system, cron, routing, sessions, insights, permissions, rag, chat, crew):
    app.include_router(router_module.router)

# ---------------------------------------------------------------------------
# Core endpoints that live in main (aggregate state or WebSocket)
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def api_status():
    jobs = []
    for j in _state["cron_jobs"]:
        job = dict(j)
        job["next_run_in_seconds"] = _seconds_until(job.get("next_run_at"))
        jobs.append(job)
    return {
        "timestamp": _now_iso(),
        "last_updated": _state["last_updated"],
        "services": _state["services"],
        "agents": _state["agents"],
        "cron_jobs": jobs,
        "routing_summary": _state["routing_summary"],
        "permission_audit_summary": _state["permission_audit_summary"],
        "memories": _state["memories"],
        "llm_models": _state["llm_models"],
        "llm_active": _state["llm_active"],
    }


@app.get("/api/history")
async def api_history(t: str | None = None):
    """Return a historical snapshot closest to the given ISO timestamp, or the full buffer."""
    if not t:
        return {"snapshots": list(_history), "count": len(_history)}
    try:
        target = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return {"error": "invalid timestamp", "snapshots": []}
    if not _history:
        return {"snapshot": None}
    best = min(
        _history,
        key=lambda s: abs(
            (datetime.fromisoformat(s["ts"].replace("Z", "+00:00")) - target).total_seconds()
        ),
    )
    return {"snapshot": best}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    async with _st._ws_lock:
        if len(_st._ws_clients) >= MAX_WS_CONNECTIONS:
            await ws.close(code=1008, reason="Server at capacity")
            return
    await ws.accept()
    async with _st._ws_lock:
        _st._ws_clients.add(ws)

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
        "trending_repos": _state["trending_repos"],
        "insights": _st._insights,
        "agent_messages": _state["agent_messages"],
    }
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        pass

    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        async with _st._ws_lock:
            _st._ws_clients.discard(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)

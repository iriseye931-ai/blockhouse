import asyncio
from fastapi import APIRouter
from ..state import _state
from ..helpers import _fetch_system_metrics, _fetch_logs, _fetch_memory_monitor_log
from ..config import MEMORY_MONITOR_LOG

router = APIRouter()


@router.get("/api/health")
async def api_health():
    return {
        "services": _state["services"],
        "last_updated": _state["last_updated"],
        "permission_audit_summary": _state["permission_audit_summary"],
    }


@router.get("/api/system")
async def api_system():
    metrics = await asyncio.get_event_loop().run_in_executor(None, _fetch_system_metrics)
    return metrics


@router.get("/api/logs")
async def api_logs(n: int = 60):
    logs = await asyncio.get_event_loop().run_in_executor(None, lambda: _fetch_logs(n))
    return logs


@router.get("/api/memory-monitor-log")
async def api_memory_monitor_log(lines: int = 50):
    log = await asyncio.get_event_loop().run_in_executor(None, lambda: _fetch_memory_monitor_log(lines))
    return {"lines": log, "path": str(MEMORY_MONITOR_LOG)}


@router.get("/api/signal-watcher")
async def api_signal_watcher():
    from ..helpers import _compute_signal_watcher_state
    cached = _state.get("signal_watcher")
    if cached:
        return cached
    return _compute_signal_watcher_state(_state.get("cron_jobs", []), _state.get("memories", []))


@router.get("/api/security-posture")
async def api_security_posture():
    from ..helpers import _compute_security_posture_state
    cached = _state.get("security_posture")
    if cached:
        return cached
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _compute_security_posture_state)

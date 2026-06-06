"""
Background tasks — poll loop, OpenViking watchdog, morning brief.
Started from the app lifespan; imported by main.py only.
"""
import asyncio
import traceback

import httpx

from . import state as _st
from .state import _state
from .config import (
    POLL_INTERVAL, OPENVIKING_HEALTH, OPENVIKING_KEY,
    OV_WATCHDOG_INTERVAL, OV_RESTART_COOLDOWN,
)
from .helpers import (
    _fetch_service_health, _fetch_agents, _fetch_memories, _fetch_trending_repos,
    _read_cron_jobs, _detect_voice_active, _fetch_system_metrics, _fetch_logs,
    _fetch_amp_messages, _fetch_hermes_status, _fetch_memory_monitor_log,
    _update_service_history, _finalize_agents, _build_memory_summary,
    _extract_memory_events, _build_routing_summary, _refresh_permission_audit_summary,
    _compute_signal_watcher_state, _compute_security_posture_state,
    _fetch_agent_last_active, _ov_restart_sync, _generate_brief,
    _now_iso,
)
from .state import broadcast_status


async def run_poll_loop() -> None:
    async with httpx.AsyncClient() as client:
        while True:
            try:
                services, agents, memories, trending_repos = await asyncio.gather(
                    _fetch_service_health(client),
                    _fetch_agents(client),
                    _fetch_memories(client),
                    _fetch_trending_repos(client),
                )
                cron_jobs = _read_cron_jobs()
                voice_active = await asyncio.get_event_loop().run_in_executor(
                    None, _detect_voice_active
                )

                system, logs, amp_messages, hermes_status, memory_monitor_log = await asyncio.gather(
                    asyncio.get_event_loop().run_in_executor(None, _fetch_system_metrics),
                    asyncio.get_event_loop().run_in_executor(None, _fetch_logs),
                    asyncio.get_event_loop().run_in_executor(None, _fetch_amp_messages),
                    asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status),
                    asyncio.get_event_loop().run_in_executor(None, _fetch_memory_monitor_log),
                )
                _state["services"] = services
                _update_service_history(services)
                _state["llm_active"] = "mlx" if services.get("mlx_server", {}).get("status") == "up" else None
                last_active = _fetch_agent_last_active(hermes_status, amp_messages)
                _state["agents"] = _finalize_agents(agents, services, last_active)
                _state["memory_summary"] = _build_memory_summary(memories, services, memory_monitor_log)
                _state["memory_events"] = _extract_memory_events(memory_monitor_log)
                _state["routing_summary"] = _build_routing_summary(_state["agents"], services, _state["memory_summary"])
                _state["cron_jobs"] = cron_jobs
                _state["memories"] = memories
                _state["voice_active"] = voice_active
                _state["system"] = system
                _state["logs"] = logs
                _state["amp_messages"] = amp_messages
                _state["hermes_status"] = hermes_status
                _state["memory_monitor_log"] = memory_monitor_log
                _state["trending_repos"] = trending_repos
                _state["permission_audit_summary"] = _refresh_permission_audit_summary()
                _state["signal_watcher"] = _compute_signal_watcher_state(cron_jobs, memories)
                _state["security_posture"] = await asyncio.get_event_loop().run_in_executor(
                    None, _compute_security_posture_state
                )
                _state["last_updated"] = _now_iso()

                await broadcast_status()
            except Exception as exc:
                print(f"[poll] error: {exc}", flush=True)
                traceback.print_exc()

            await asyncio.sleep(POLL_INTERVAL)


async def run_openviking_watchdog() -> None:
    """Polls OpenViking health every 30s and restarts if down."""
    import time
    await asyncio.sleep(15)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                if time.monotonic() - _st._ov_last_restart < OV_RESTART_COOLDOWN:
                    await asyncio.sleep(OV_WATCHDOG_INTERVAL)
                    continue

                r = await client.get(
                    OPENVIKING_HEALTH,
                    headers={"Authorization": f"Bearer {OPENVIKING_KEY}"},
                    timeout=5.0,
                )
                if not r.json().get("healthy"):
                    raise ValueError("unhealthy")

            except Exception as exc:
                print(f"[watchdog] OpenViking down ({exc}), restarting…")
                msg = await asyncio.get_event_loop().run_in_executor(None, _ov_restart_sync)
                print(msg)

            await asyncio.sleep(OV_WATCHDOG_INTERVAL)


async def run_generate_brief_on_startup() -> None:
    """Wait for first poll to complete, then generate brief."""
    for _ in range(12):
        await asyncio.sleep(5)
        if _state.get("last_updated"):
            break
    await _generate_brief()

"""
Helper functions — extracted from the original monolithic main.py.
All functions that support route handlers and background tasks live here.
"""
import asyncio
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import uuid
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

import httpx
import psutil
from fastapi import HTTPException

from . import state as _st
from .state import _state, _insights, _brief_cache, _now_iso
from .config import (
    OPENVIKING_URL, OPENVIKING_HEALTH, OPENVIKING_KEY, OPENVIKING_ACCOUNT, OPENVIKING_USER,
    MEMORY_MCP_URL, HERMES_GATEWAY_URL, OLLAMA_URL, OLLAMA_MODELS_URL,
    MLX_SERVER_URL, MLX_AUX_URL, WHISPER_STT_URL, WHISPER_HEALTH,
    MLX_MODELS_URL, MLX_AUX_MODELS_URL, SCREENPIPE_URL,
    GITHUB_SEARCH_URL, TRENDING_CACHE_TTL,
    MEMORY_MONITOR_LOG, MLX_ERROR_LOG, AMP_AGENTS_DIR,
    HERMES_SESSIONS_DIR, HERMES_GATEWAY_STATE_PATH, HERMES_GATEWAY_PID_PATH,
    HERMES_HOME, HERMES_PROFILES_DIR, LOCAL_BIN_DIR, HERMES_BIN,
    AVAILABILITY_OVERRIDES_PATH, PERMISSION_AUDIT_LOG_PATH, AGENT_INBOX_PATH,
    HERMES_BACKGROUND_TASKS_PATH, HERMES_BACKGROUND_LOG_DIR,
    MESH_PROFILE_RUNTIME_DIR, MLX_VENV_BIN, MLX_SERVER_BIN,
    CRON_JOBS_PATH, HERMES_SESSIONS_PATH, NIGHTLY_BUILD_LOG, SESSIONS_DB,
    PROJECTS_DIR, OPENVIKING_PLIST, OV_LOCK_PATH, OV_PID_PATH,
    HTTP_TIMEOUT, POLL_INTERVAL, BRIEF_REFRESH_HOURS,
    OV_WATCHDOG_INTERVAL, OV_RESTART_COOLDOWN, SERVICE_HISTORY_MAX,
    MCP_PING, MCP_HEADERS, CLAUDE_SYSTEM_PROMPT,
    ROUTINE_KEYWORDS, SPECIALIZED_KEYWORDS, PREMIUM_KEYWORDS, CODE_KEYWORDS,
    MESH_PORTS,
)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_service_history(services: dict):
    hist = _state["service_history"]
    ts = _now_iso()
    for name, svc in services.items():
        up = svc.get("status") in ("up", "healthy")
        entry = {"ts": ts, "up": up}
        if name not in hist:
            hist[name] = []
        hist[name] = (hist[name] + [entry])[-SERVICE_HISTORY_MAX:]


def _seconds_until(iso_str: str | None) -> int | None:
    """Return seconds from now until the given ISO timestamp, or None."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = dt - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))
    except Exception:
        return None


def _parse_iso_datetime(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _iso_from_timestamp(value: float | int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _activity_summary(iso_str: str | None) -> tuple[str, int | None]:
    """Return an activity freshness label and age in seconds."""
    dt = _parse_iso_datetime(iso_str)
    if not dt:
        return "unknown", None

    age_seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if age_seconds <= 15 * 60:
        return "live", age_seconds
    if age_seconds <= 6 * 3600:
        return "recent", age_seconds
    if age_seconds <= 24 * 3600:
        return "idle", age_seconds
    return "stale", age_seconds


def _classify_task(text: str) -> tuple[str, str]:
    lowered = (text or "").strip().lower()
    if not lowered:
        return "routine", "Default local execution"

    if any(token in lowered for token in PREMIUM_KEYWORDS):
        return "premium", "Premium-only work matched planning/debugging/review signals"
    if any(token in lowered for token in SPECIALIZED_KEYWORDS):
        return "specialized", "Specialized file/web work detected"
    if any(token in lowered for token in CODE_KEYWORDS):
        return "routine", "Code-heavy local work detected"
    if any(token in lowered for token in ROUTINE_KEYWORDS):
        return "routine", "Routine local work detected"
    if len(lowered) > 600 or lowered.count("\n") > 8:
        return "premium", "Large or complex request defaults to premium review"
    return "routine", "Default local execution"


def _build_routing_summary(
    agents: list[dict[str, Any]],
    services: dict[str, Any] | None = None,
    memory_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    premium_pool = [a for a in agents if a.get("routing_group") == "premium-pool"]
    available_premium = [
        a for a in premium_pool
        if a.get("availability_status", "available") == "available"
    ]
    local_default = next((a for a in agents if a.get("routing_group") == "local-default"), None)
    specialized = [a for a in agents if a.get("routing_group") == "specialized"]
    services = services or {}
    memory_summary = memory_summary or {}
    memory_status = memory_summary.get("status") or services.get("memory_mcp", {}).get("status", "unknown")
    memory_ready = memory_status == "up"
    warnings: list[str] = []
    primary_cause = memory_summary.get("primary_cause") or {}
    memory_mode = primary_cause.get("kind", "healthy")
    if not memory_ready:
        if memory_mode == "substrate":
            warnings.append("Memory substrate is degraded; recall-heavy tasks may need manual verification.")
        elif memory_mode == "gateway":
            warnings.append("OpenViking gateway is down; memory transport and orchestration visibility are limited.")
        elif memory_mode == "pressure":
            warnings.append("Host memory pressure is degrading recall reliability.")
        elif memory_mode == "stale":
            warnings.append("Memory context is stale; recent state may be missing.")
        else:
            warnings.append(primary_cause.get("summary") or "Memory path is degraded.")

    routine_agent = (local_default or {}).get("name") or "hermes"
    specialized_agent = specialized[0].get("name") if specialized else routine_agent
    premium_agent = available_premium[0].get("name") if available_premium else (premium_pool[0].get("name") if premium_pool else "claude")
    hermes_profiles = (local_default or {}).get("local_profiles") if (local_default or {}).get("name") == "hermes" else []
    profile_guidance = _preferred_hermes_profile_guidance(hermes_profiles or [])
    return {
        "policy": "local-first",
        "premium_pool": [a.get("name") for a in premium_pool],
        "premium_available": [a.get("name") for a in available_premium],
        "premium_available_count": len(available_premium),
        "premium_total_count": len(premium_pool),
        "local_default": (local_default or {}).get("name"),
        "specialized_agents": [a.get("name") for a in specialized],
        "memory_status": memory_status,
        "memory_ready": memory_ready,
        "memory_mode": memory_mode,
        "warnings": warnings,
        "guidance": {
            "routine": routine_agent,
            "specialized": specialized_agent,
            "premium": premium_agent,
            "memory_heavy": routine_agent if memory_ready or memory_mode == "pressure" else premium_agent,
        },
        "profile_guidance": {
            "routine": profile_guidance.get("routine"),
            "summary": profile_guidance.get("summary"),
            "reasoning": profile_guidance.get("reasoning"),
            "code": profile_guidance.get("code"),
            "memory_heavy": profile_guidance.get("routine") if memory_ready or memory_mode == "pressure" else None,
        },
    }


def _permission_audit_entries(limit: int | None = None) -> list[dict[str, Any]]:
    path = PERMISSION_AUDIT_LOG_PATH
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except Exception:
        return []

    if limit is not None:
        return entries[-limit:]
    return entries


def _summarize_permission_audit(entries: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = {"allow": 0, "deny": 0, "ask": 0, "bypass": 0}
    mode_counts: dict[str, int] = {}
    last_entry = entries[-1] if entries else None

    for entry in entries:
        decision = str(entry.get("decision", "")).lower()
        if decision in decision_counts:
            decision_counts[decision] += 1
        mode = str(entry.get("mode", "")).lower()
        if mode:
            mode_counts[mode] = mode_counts.get(mode, 0) + 1

    return {
        "count": len(entries),
        "decision_counts": decision_counts,
        "mode_counts": mode_counts,
        "last_event_at": (last_entry or {}).get("timestamp"),
    }


def _refresh_permission_audit_summary() -> dict[str, Any]:
    summary = _summarize_permission_audit(_permission_audit_entries(limit=200))
    _state["permission_audit_summary"] = summary
    return summary


def _append_permission_audit(entry: dict[str, Any]) -> dict[str, Any]:
    path = PERMISSION_AUDIT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": entry.get("timestamp") or _now_iso(),
        "source": entry.get("source") or "unknown",
        "agent": entry.get("agent"),
        "tool": entry.get("tool"),
        "decision": entry.get("decision"),
        "mode": entry.get("mode"),
        "reason": entry.get("reason"),
        "input_summary": entry.get("input_summary"),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    _refresh_permission_audit_summary()
    return record


def _read_agent_messages(limit: int | None = 100) -> list[dict[str, Any]]:
    path = AGENT_INBOX_PATH
    if not path.exists():
        return []

    messages: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    messages.append(message)
    except Exception:
        return []

    return messages[-limit:] if limit is not None else messages


def _refresh_agent_messages(limit: int = 100) -> list[dict[str, Any]]:
    messages = _read_agent_messages(limit=limit)
    _state["agent_messages"] = messages
    return messages


def _append_agent_message(message: dict[str, Any]) -> dict[str, Any]:
    AGENT_INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": message.get("id") or f"msg-{datetime.now(timezone.utc).timestamp():.6f}",
        "timestamp": message.get("timestamp") or _now_iso(),
        "from": str(message.get("from") or "").strip(),
        "to": str(message.get("to") or "").strip(),
        "role": str(message.get("role") or "handoff").strip(),
        "task": str(message.get("task") or "").strip(),
        "summary": str(message.get("summary") or "").strip(),
        "details": str(message.get("details") or "").strip(),
        "files": message.get("files") or [],
    }
    with AGENT_INBOX_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    _refresh_agent_messages()
    return record


def _audit_permission_decision(
    *,
    decision: str,
    tool: str,
    reason: str,
    mode: str = "default",
    source: str = "mission-control",
    agent: str | None = None,
    input_summary: str | None = None,
) -> dict[str, Any]:
    return _append_permission_audit({
        "source": source,
        "agent": agent,
        "tool": tool,
        "decision": decision,
        "mode": mode,
        "reason": reason,
        "input_summary": input_summary,
    })


def _extract_port(base_url: str | None) -> int | None:
    if not base_url:
        return None
    try:
        parsed = urlparse(base_url)
        return parsed.port
    except Exception:
        return None


def _profile_pid_path(agent_name: str, profile_name: str) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", f"{agent_name}-{profile_name}".lower())
    return MESH_PROFILE_RUNTIME_DIR / f"{safe}.pid"


def _profile_log_path(agent_name: str, profile_name: str) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", f"{agent_name}-{profile_name}".lower())
    return MESH_PROFILE_RUNTIME_DIR / f"{safe}.log"


def _resolve_profile_model(profile: dict[str, Any]) -> Path:
    model = str(profile.get("model") or "").strip()
    return Path(model).expanduser()


def _port_open(port: int | None) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except Exception:
        return False


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


def _enrich_local_profile(agent_name: str, profile: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(profile)
    if str(profile.get("profile_kind") or "").strip() == "hermes-native":
        hermes_profile = str(profile.get("hermes_profile") or "default").strip() or "default"
        profile_home = _hermes_profile_home(hermes_profile)
        alias_path = _hermes_profile_alias_path(hermes_profile)
        gateway_state = _read_hermes_gateway_state(profile_home)
        gateway_pid = _read_pid(profile_home / "gateway.pid")
        running = _pid_running(gateway_pid) or str(gateway_state.get("status", "")).lower() == "running"
        exists = profile_home.exists()
        model_info = _read_hermes_profile_model(profile_home)
        enriched["installed"] = exists
        enriched["running"] = running
        enriched["startable"] = exists and HERMES_BIN.exists()
        enriched["managed"] = True
        enriched["pid"] = gateway_pid if _pid_running(gateway_pid) else None
        enriched["port"] = _extract_port(model_info.get("base_url"))
        enriched["model"] = model_info.get("model") or enriched.get("model") or "Hermes profile"
        enriched["base_url"] = model_info.get("base_url") or enriched.get("base_url")
        enriched["provider"] = model_info.get("provider")
        enriched["profile_home"] = str(profile_home)
        enriched["alias_path"] = str(alias_path) if hermes_profile != "default" else None
        enriched["alias_installed"] = alias_path.exists() if hermes_profile != "default" else False
        enriched["gateway_status"] = gateway_state.get("status")
        enriched["runtime"] = "hermes-profile"
        enriched["display_name"] = str(profile.get("display_name") or hermes_profile)
        enriched["session_overview"] = _fetch_hermes_profile_session_overview(profile_home, hermes_profile)
        enriched["quick_commands"] = _read_hermes_quick_commands(profile_home)
        enriched["checkpoint_overview"] = _fetch_hermes_checkpoint_overview(profile_home, hermes_profile)
        enriched["provider_overview"] = _fetch_hermes_provider_overview(profile_home)
        enriched["toolset_overview"] = _fetch_hermes_toolset_overview(profile_home)
        enriched["skill_overview"] = _fetch_hermes_skill_overview(profile_home)
        enriched["memory_overview"] = _fetch_hermes_memory_overview(profile_home)
        return enriched
    model_path = _resolve_profile_model(profile)
    pid_path = _profile_pid_path(agent_name, str(profile.get("name", "")))
    log_path = _profile_log_path(agent_name, str(profile.get("name", "")))
    pid = _read_pid(pid_path)
    port = _extract_port(profile.get("base_url"))
    running = _port_open(port) or _pid_running(pid)
    installed = model_path.exists()
    startable = installed and MLX_SERVER_BIN.exists()
    enriched["model_path"] = str(model_path)
    enriched["installed"] = installed
    enriched["running"] = running
    enriched["startable"] = startable
    enriched["pid"] = pid if _pid_running(pid) else None
    enriched["port"] = port
    enriched["managed"] = bool(profile.get("managed")) or profile.get("mode") == "on-demand"
    enriched["log_path"] = str(log_path)
    enriched["runtime"] = "mlx-server"
    enriched["display_name"] = str(profile.get("display_name") or profile.get("name") or "")
    return enriched


def _hermes_profile_home(profile_name: str) -> Path:
    safe = (profile_name or "default").strip()
    if not safe or safe == "default":
        return HERMES_HOME
    return HERMES_PROFILES_DIR / safe


def _hermes_profile_alias_path(profile_name: str) -> Path:
    return LOCAL_BIN_DIR / profile_name


def _read_hermes_gateway_state(profile_home: Path) -> dict[str, Any]:
    state_path = profile_home / "gateway_state.json"
    data = _read_json(state_path)
    return data if isinstance(data, dict) else {}


def _read_hermes_profile_model(profile_home: Path) -> dict[str, str | None]:
    config_path = profile_home / "config.yaml"
    if not config_path.exists():
        return {"model": None, "provider": None, "base_url": None}
    try:
        text = config_path.read_text(errors="replace")
    except Exception:
        return {"model": None, "provider": None, "base_url": None}

    def _match(pattern: str) -> str | None:
        m = re.search(pattern, text, re.MULTILINE)
        if not m:
            return None
        return (m.group(1) or "").strip() or None

    return {
        "model": _match(r"^  model:\s*(.+)$"),
        "provider": _match(r"^  provider:\s*(.+)$"),
        "base_url": _match(r"^  base_url:\s*(.+)$"),
    }


def _read_hermes_profile_config(profile_home: Path) -> dict[str, Any]:
    config_path = profile_home / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        loaded = yaml.safe_load(config_path.read_text(errors="replace"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _read_hermes_quick_commands(profile_home: Path) -> list[dict[str, Any]]:
    config = _read_hermes_profile_config(profile_home)
    commands = config.get("quick_commands")
    if not isinstance(commands, dict):
        return []
    items: list[dict[str, Any]] = []
    for name, spec in commands.items():
        if not isinstance(spec, dict):
            continue
        items.append({
            "name": str(name),
            "type": str(spec.get("type") or "exec"),
            "command": str(spec.get("command") or "").strip() or None,
        })
    return items


def _fetch_hermes_checkpoint_overview(profile_home: Path, profile_name: str) -> dict[str, Any]:
    config = _read_hermes_profile_config(profile_home)
    checkpoint_cfg = config.get("checkpoints")
    checkpoint_cfg = checkpoint_cfg if isinstance(checkpoint_cfg, dict) else {}
    snapshot_root = HERMES_HOME / "checkpoints"
    snapshot_dirs: list[Path] = []
    try:
        if snapshot_root.exists():
            snapshot_dirs = sorted(
                [path for path in snapshot_root.iterdir() if path.is_dir()],
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
    except Exception:
        snapshot_dirs = []

    latest_snapshot_at = None
    if snapshot_dirs:
        try:
            latest_snapshot_at = _iso_from_timestamp(snapshot_dirs[0].stat().st_mtime)
        except Exception:
            latest_snapshot_at = None

    max_snapshots = checkpoint_cfg.get("max_snapshots")
    if max_snapshots is not None:
        try:
            max_snapshots = int(max_snapshots)
        except Exception:
            max_snapshots = None

    resume_command = f"hermes -p {profile_name} -c" if profile_name != "default" else "hermes -c"
    enabled = bool(checkpoint_cfg.get("enabled"))
    return {
        "enabled": enabled,
        "max_snapshots": max_snapshots,
        "snapshot_root": str(snapshot_root),
        "snapshot_count": len(snapshot_dirs),
        "latest_snapshot_at": latest_snapshot_at,
        "git_available": shutil.which("git") is not None,
        "rollback_ready": enabled and bool(snapshot_dirs),
        "rollback_diff_hint": f"{resume_command} then run /rollback diff",
        "rollback_hint": f"{resume_command} then run /rollback",
    }


def _provider_brief(spec: Any) -> dict[str, Any] | None:
    if not isinstance(spec, dict):
        return None
    provider = str(spec.get("provider") or "").strip() or None
    model = str(spec.get("model") or spec.get("default") or "").strip() or None
    base_url = str(spec.get("base_url") or "").strip() or None
    if not any((provider, model, base_url)):
        return None
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
    }


def _fetch_hermes_provider_overview(profile_home: Path) -> dict[str, Any]:
    config = _read_hermes_profile_config(profile_home)
    primary = _provider_brief(config.get("model")) or {}
    fallback_specs = config.get("fallback_providers")
    fallback_specs = fallback_specs if isinstance(fallback_specs, list) else []
    fallbacks = [brief for brief in (_provider_brief(item) for item in fallback_specs) if brief]

    smart_cfg = config.get("smart_model_routing")
    smart_cfg = smart_cfg if isinstance(smart_cfg, dict) else {}
    cheap_model = _provider_brief(smart_cfg.get("cheap_model"))

    auxiliary_cfg = config.get("auxiliary")
    auxiliary_cfg = auxiliary_cfg if isinstance(auxiliary_cfg, dict) else {}
    auxiliary = {
        name: brief
        for name, brief in (
            (str(name), _provider_brief(spec))
            for name, spec in auxiliary_cfg.items()
            if isinstance(name, str)
        )
        if brief
    }

    delegation = _provider_brief(config.get("delegation"))
    endpoints = {
        item.get("base_url")
        for item in [primary, cheap_model, delegation, *fallbacks, *auxiliary.values()]
        if item and item.get("base_url")
    }
    models = {
        item.get("model")
        for item in [primary, cheap_model, delegation, *fallbacks, *auxiliary.values()]
        if item and item.get("model")
    }

    return {
        "primary": primary or None,
        "fallbacks": fallbacks,
        "fallback_count": len(fallbacks),
        "smart_routing_enabled": bool(smart_cfg.get("enabled")),
        "cheap_model": cheap_model,
        "auxiliary": auxiliary,
        "auxiliary_count": len(auxiliary),
        "delegation": delegation,
        "unique_endpoint_count": len(endpoints),
        "unique_model_count": len(models),
    }


def _fetch_hermes_toolset_overview(profile_home: Path) -> dict[str, Any]:
    config = _read_hermes_profile_config(profile_home)
    toolsets = config.get("toolsets")
    toolsets_list = [str(item).strip() for item in toolsets] if isinstance(toolsets, list) else []
    toolsets_list = [item for item in toolsets_list if item]
    return {
        "toolsets": toolsets_list,
        "toolset_count": len(toolsets_list),
        "all_tools": "all" in toolsets_list,
        "has_browser": any(item in {"all", "browser", "web"} for item in toolsets_list),
        "has_terminal": any(item in {"all", "terminal", "file"} for item in toolsets_list),
        "has_memory": any(item in {"all", "memory", "session_search"} for item in toolsets_list),
        "has_delegation": any(item in {"all", "delegation", "code_execution"} for item in toolsets_list),
    }


def _resolve_hermes_skill_dirs(profile_home: Path) -> tuple[Path, list[Path]]:
    local_dir = profile_home / "skills"
    config = _read_hermes_profile_config(profile_home)
    skills_cfg = config.get("skills")
    skills_cfg = skills_cfg if isinstance(skills_cfg, dict) else {}
    external = skills_cfg.get("external_dirs")
    external = external if isinstance(external, list) else []
    external_dirs: list[Path] = []
    for item in external:
        raw = str(item or "").strip()
        if not raw:
            continue
        expanded = os.path.expandvars(os.path.expanduser(raw))
        external_dirs.append(Path(expanded))
    return local_dir, external_dirs


def _scan_skill_names(root: Path) -> list[str]:
    if not root.exists():
        return []
    names: list[str] = []
    try:
        for skill_file in root.glob("**/SKILL.md"):
            parent = skill_file.parent
            rel = parent.relative_to(root)
            names.append("/".join(rel.parts))
    except Exception:
        return []
    return sorted(dict.fromkeys(names))


def _fetch_hermes_skill_overview(profile_home: Path) -> dict[str, Any]:
    local_dir, external_dirs = _resolve_hermes_skill_dirs(profile_home)
    local_names = _scan_skill_names(local_dir)
    external_info: list[dict[str, Any]] = []
    external_total = 0
    for path in external_dirs:
        names = _scan_skill_names(path)
        external_total += len(names)
        external_info.append({
            "path": str(path),
            "exists": path.exists(),
            "skill_count": len(names),
            "sample_skills": names[:5],
        })
    return {
        "local_dir": str(local_dir),
        "local_exists": local_dir.exists(),
        "local_skill_count": len(local_names),
        "local_sample_skills": local_names[:5],
        "external_dirs": external_info,
        "external_dir_count": len(external_info),
        "external_skill_count": external_total,
        "shared_skills_connected": any(item.get("exists") and item.get("skill_count", 0) > 0 for item in external_info),
    }


def _read_text_char_count(path: Path) -> int:
    try:
        return len(path.read_text(errors="replace"))
    except Exception:
        return 0


def _resolve_hermes_memory_provider(config: dict[str, Any], memory_cfg: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    mcp_servers = config.get("mcp_servers")
    mcp_servers = mcp_servers if isinstance(mcp_servers, dict) else {}
    available_names = [str(name).strip() for name in mcp_servers.keys() if isinstance(name, str) and "memory" in str(name).lower()]
    available_names = [name for name in available_names if name]

    configured_name = str(memory_cfg.get("provider") or "").strip() or None
    if not configured_name:
        return None, None, sorted(dict.fromkeys(available_names))

    candidates = [
        configured_name,
        f"{configured_name}-memory",
        configured_name.replace("_", "-"),
        f"{configured_name.replace('_', '-')}-memory",
    ]
    for candidate in candidates:
        spec = mcp_servers.get(candidate)
        if isinstance(spec, dict):
            return configured_name, spec, sorted(dict.fromkeys(available_names))
    return configured_name, None, sorted(dict.fromkeys(available_names))


def _fetch_hermes_memory_overview(profile_home: Path) -> dict[str, Any]:
    config = _read_hermes_profile_config(profile_home)
    memory_cfg = config.get("memory")
    memory_cfg = memory_cfg if isinstance(memory_cfg, dict) else {}

    memories_dir = profile_home / "memories"
    memory_path = memories_dir / "MEMORY.md"
    user_path = memories_dir / "USER.md"

    configured_provider, provider_spec, available_providers = _resolve_hermes_memory_provider(config, memory_cfg)
    provider_url = str(provider_spec.get("url") or provider_spec.get("base_url") or "").strip() if isinstance(provider_spec, dict) else ""
    latest_update_candidates: list[float] = []
    for path in (memory_path, user_path):
        try:
            if path.exists():
                latest_update_candidates.append(path.stat().st_mtime)
        except Exception:
            continue

    def _int_value(key: str) -> int | None:
        raw = memory_cfg.get(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except Exception:
            return None

    external_hint = "built-in only"
    if configured_provider and provider_spec:
        external_hint = f"{configured_provider} active"
    elif configured_provider:
        external_hint = f"{configured_provider} configured"
    elif available_providers:
        external_hint = f"{available_providers[0]} ready"

    return {
        "memory_enabled": bool(memory_cfg.get("memory_enabled")),
        "user_profile_enabled": bool(memory_cfg.get("user_profile_enabled")),
        "memory_char_limit": _int_value("memory_char_limit"),
        "user_char_limit": _int_value("user_char_limit"),
        "nudge_interval": _int_value("nudge_interval"),
        "flush_min_turns": _int_value("flush_min_turns"),
        "memory_dir": str(memories_dir),
        "memory_file_exists": memory_path.exists(),
        "user_file_exists": user_path.exists(),
        "memory_char_count": _read_text_char_count(memory_path) if memory_path.exists() else 0,
        "user_char_count": _read_text_char_count(user_path) if user_path.exists() else 0,
        "latest_update_at": _iso_from_timestamp(max(latest_update_candidates)) if latest_update_candidates else None,
        "external_provider_name": configured_provider,
        "external_provider_active": bool(configured_provider and provider_spec),
        "external_provider_available": bool(provider_spec or available_providers),
        "external_provider_endpoint": provider_url or None,
        "external_provider_candidates": available_providers,
        "external_provider_hint": external_hint,
    }


def _resolve_repo_root(repo_path: str | None) -> Path | None:
    if not repo_path:
        return None
    path = Path(repo_path).expanduser()
    if not path.exists():
        return None
    target = path if path.is_dir() else path.parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return None
        resolved = proc.stdout.strip()
        return Path(resolved) if resolved else None
    except Exception:
        return None


def _fetch_hermes_profile_session_overview(profile_home: Path, profile_name: str) -> dict[str, Any]:
    db_path = profile_home / "state.db"
    sessions_dir = profile_home / "sessions"
    overview: dict[str, Any] = {
        "profile": profile_name,
        "session_count": 0,
        "search_ready": False,
        "latest_session_id": None,
        "latest_title": None,
        "latest_source": None,
        "latest_model": None,
        "latest_started_at": None,
        "latest_ended_at": None,
        "latest_updated_at": None,
        "latest_message_count": None,
        "resume_target": None,
        "resume_command": f"hermes -c {profile_name}" if profile_name != "default" else "hermes -c",
    }

    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                overview["search_ready"] = "messages_fts" in tables
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_sessions,
                        MAX(COALESCE(ended_at, started_at)) AS latest_ts
                    FROM sessions
                    """
                ).fetchone()
                if row:
                    overview["session_count"] = int(row["total_sessions"] or 0)
                    overview["latest_updated_at"] = _iso_from_timestamp(row["latest_ts"])

                latest = conn.execute(
                    """
                    SELECT id, title, source, model, started_at, ended_at, message_count
                    FROM sessions
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                if latest:
                    latest_title = (latest["title"] or "").strip() or None
                    overview.update({
                        "latest_session_id": latest["id"],
                        "latest_title": latest_title,
                        "latest_source": latest["source"],
                        "latest_model": latest["model"],
                        "latest_started_at": _iso_from_timestamp(latest["started_at"]),
                        "latest_ended_at": _iso_from_timestamp(latest["ended_at"]),
                        "latest_message_count": latest["message_count"],
                        "resume_target": latest_title or latest["id"],
                        "resume_command": f"hermes -p {profile_name} --resume \"{latest_title or latest['id']}\"" if profile_name != "default" else f"hermes --resume \"{latest_title or latest['id']}\"",
                    })
                return overview
        except Exception:
            pass

    try:
        session_files = sorted(
            [path for path in sessions_dir.glob("session_*.json") if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        session_files = []

    overview["session_count"] = len(session_files)
    if not session_files:
        return overview

    latest_file = session_files[0]
    try:
        latest = json.loads(latest_file.read_text(errors="replace"))
    except Exception:
        latest = {}

    latest_title = str(latest.get("title") or "").strip() or None
    latest_session_id = latest.get("session_id") or latest_file.stem.removeprefix("session_")
    overview.update({
        "latest_session_id": latest_session_id,
        "latest_title": latest_title,
        "latest_source": latest.get("platform"),
        "latest_model": latest.get("model"),
        "latest_started_at": latest.get("session_start"),
        "latest_ended_at": latest.get("ended_at"),
        "latest_updated_at": latest.get("last_updated") or _iso_from_timestamp(latest_file.stat().st_mtime),
        "resume_target": latest_title or latest_session_id,
        "resume_command": f"hermes -p {profile_name} --resume \"{latest_title or latest_session_id}\"" if profile_name != "default" else f"hermes --resume \"{latest_title or latest_session_id}\"",
    })
    return overview


def _fetch_hermes_sessions_overview() -> dict[str, Any]:
    profiles = ["default"]
    try:
        if HERMES_PROFILES_DIR.exists():
            profiles.extend(sorted(path.name for path in HERMES_PROFILES_DIR.iterdir() if path.is_dir()))
    except Exception:
        pass

    per_profile = [_fetch_hermes_profile_session_overview(_hermes_profile_home(name), name) for name in profiles]
    total_sessions = sum(int(item.get("session_count") or 0) for item in per_profile)
    latest = next(
        (
            item for item in sorted(
                per_profile,
                key=lambda entry: _parse_iso_datetime(entry.get("latest_updated_at")) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            if item.get("latest_updated_at")
        ),
        None,
    )
    active_profiles = sum(1 for item in per_profile if int(item.get("session_count") or 0) > 0)
    return {
        "profiles": per_profile,
        "profile_count": len(per_profile),
        "active_profiles": active_profiles,
        "session_count": total_sessions,
        "search_ready": any(bool(item.get("search_ready")) for item in per_profile),
        "latest_title": (latest or {}).get("latest_title"),
        "latest_profile": (latest or {}).get("profile"),
        "latest_source": (latest or {}).get("latest_source"),
        "latest_updated_at": (latest or {}).get("latest_updated_at"),
        "resume_target": (latest or {}).get("resume_target"),
        "resume_command": (latest or {}).get("resume_command"),
    }


def _read_hermes_background_registry() -> list[dict[str, Any]]:
    data = _read_json(HERMES_BACKGROUND_TASKS_PATH)
    return data if isinstance(data, list) else []


def _write_hermes_background_registry(tasks: list[dict[str, Any]]) -> None:
    HERMES_BACKGROUND_TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    HERMES_BACKGROUND_TASKS_PATH.write_text(json.dumps(tasks, indent=2))


def _refresh_background_task_state(task: dict[str, Any]) -> dict[str, Any]:
    refreshed = dict(task)
    if refreshed.get("worktree_path"):
        refreshed["worktree_path"] = re.sub(r"\x1b\[[0-9;]*m", "", str(refreshed.get("worktree_path"))).strip()
    if refreshed.get("worktree_branch"):
        refreshed["worktree_branch"] = re.sub(r"\x1b\[[0-9;]*m", "", str(refreshed.get("worktree_branch"))).strip()
    pid = refreshed.get("pid")
    running = bool(pid) and _pid_running(int(pid))
    log_path = refreshed.get("log_path")
    if log_path:
        try:
            log_text = Path(log_path).read_text(errors="replace")
            log_text = re.sub(r"\x1b\[[0-9;]*m", "", log_text)
            worktree_match = re.search(r"Worktree created:\s*(.+)", log_text)
            branch_match = re.search(r"Branch:\s*(.+)", log_text)
            if worktree_match and not refreshed.get("worktree_path"):
                refreshed["worktree_path"] = worktree_match.group(1).strip()
            if branch_match and not refreshed.get("worktree_branch"):
                refreshed["worktree_branch"] = branch_match.group(1).strip()
        except Exception:
            pass
    refreshed["running"] = running
    if running:
        refreshed["status"] = "running"
    elif refreshed.get("status") == "running":
        refreshed["status"] = "finished"
        refreshed["ended_at"] = refreshed.get("ended_at") or _now_iso()
    return refreshed


def _fetch_hermes_background_tasks() -> list[dict[str, Any]]:
    tasks = [_refresh_background_task_state(task) for task in _read_hermes_background_registry()]
    if tasks != _read_hermes_background_registry():
        try:
            _write_hermes_background_registry(tasks)
        except Exception:
            pass
    tasks.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    return tasks


def _tail_text(path_str: str | None, lines: int = 40) -> str:
    if not path_str:
        return ""
    try:
        path = Path(path_str)
        if not path.exists():
            return ""
        text = path.read_text(errors="replace")
        rows = text.splitlines()
        return "\n".join(rows[-lines:])
    except Exception:
        return ""


def _build_hermes_background_command(profile_name: str, prompt: str, use_worktree: bool = False) -> list[str]:
    safe_profile = (profile_name or "default").strip() or "default"
    command = [str(HERMES_BIN)]
    if safe_profile != "default":
        command.extend(["-p", safe_profile])
    command.append("chat")
    if use_worktree:
        command.append("--worktree")
    command.extend(["-q", prompt])
    return command


def _launch_hermes_background_task(
    profile_name: str,
    prompt: str,
    title: str | None = None,
    use_worktree: bool = False,
    repo_path: str | None = None,
) -> dict[str, Any]:
    if not HERMES_BIN.exists():
        raise RuntimeError("Hermes CLI is not available")
    repo_root = _resolve_repo_root(repo_path) if use_worktree else None
    if use_worktree and not repo_root:
        raise RuntimeError("valid git repo required for Hermes worktree launch")

    task_id = f"bg_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    HERMES_BACKGROUND_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = HERMES_BACKGROUND_LOG_DIR / f"{task_id}.log"
    command = _build_hermes_background_command(profile_name, prompt, use_worktree=use_worktree)
    log_handle = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(repo_root) if repo_root else None,
            env={**os.environ, "PATH": f"{LOCAL_BIN_DIR}:{os.environ.get('PATH', '')}"},
        )
    finally:
        log_handle.close()

    task = {
        "id": task_id,
        "profile": profile_name,
        "title": (title or prompt.splitlines()[0][:80]).strip() or task_id,
        "prompt": prompt[:500],
        "command": command,
        "log_path": str(log_path),
        "pid": proc.pid,
        "status": "running",
        "running": True,
        "mode": "worktree" if use_worktree else "background",
        "repo_path": str(repo_root) if repo_root else None,
        "started_at": _now_iso(),
        "ended_at": None,
    }
    tasks = _fetch_hermes_background_tasks()
    tasks = [task, *[item for item in tasks if item.get("id") != task_id]]
    _write_hermes_background_registry(tasks[:20])
    return task


def _stop_hermes_background_task(task_id: str) -> dict[str, Any] | None:
    tasks = _fetch_hermes_background_tasks()
    updated: dict[str, Any] | None = None
    new_tasks: list[dict[str, Any]] = []
    for task in tasks:
        current = dict(task)
        if current.get("id") == task_id:
            pid = current.get("pid")
            if pid and _pid_running(int(pid)):
                try:
                    os.killpg(int(pid), signal.SIGTERM)
                except Exception:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except Exception:
                        pass
            current["status"] = "stopped"
            current["running"] = False
            current["ended_at"] = _now_iso()
            updated = current
        new_tasks.append(current)
    _write_hermes_background_registry(new_tasks)
    return updated


def _cleanup_hermes_worktree(task_id: str) -> dict[str, Any] | None:
    tasks = _fetch_hermes_background_tasks()
    updated: dict[str, Any] | None = None
    new_tasks: list[dict[str, Any]] = []
    for task in tasks:
        current = dict(task)
        if current.get("id") == task_id:
            worktree_path = str(current.get("worktree_path") or "").strip()
            if not worktree_path:
                raise RuntimeError("worktree path not recorded yet")
            if current.get("running"):
                raise RuntimeError("stop the worktree task before cleanup")
            repo_path = current.get("repo_path")
            git_root = _resolve_repo_root(repo_path)
            if not git_root:
                raise RuntimeError("repo root unavailable for worktree cleanup")
            listed = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            listed_output = listed.stdout if listed.returncode == 0 else ""
            if worktree_path and f"worktree {worktree_path}" not in listed_output:
                current["status"] = "cleaned"
                current["worktree_cleaned_at"] = _now_iso()
                updated = current
                continue
            proc = subprocess.run(
                ["git", "worktree", "remove", "--force", worktree_path],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(detail or "git worktree remove failed")
            current["status"] = "cleaned"
            current["worktree_cleaned_at"] = _now_iso()
            updated = current
        new_tasks.append(current)
    _write_hermes_background_registry(new_tasks)
    return updated


def _discover_hermes_native_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    names = ["default"]
    try:
        if HERMES_PROFILES_DIR.exists():
            names.extend(sorted(path.name for path in HERMES_PROFILES_DIR.iterdir() if path.is_dir()))
    except Exception:
        pass

    for name in names:
        key = f"profile:{name}"
        profiles.append({
            "name": key,
            "display_name": name,
            "hermes_profile": name,
            "profile_kind": "hermes-native",
            "purpose": "isolated Hermes profile with separate config, memory, sessions, and gateway",
            "mode": "profile",
            "managed": True,
            "model": "Hermes profile",
        })
    return profiles


def _find_hermes_profile(
    profiles: list[dict[str, Any]],
    *names: str,
) -> dict[str, Any] | None:
    wanted = {name.strip().lower() for name in names if name.strip()}
    for profile in profiles:
        candidates = {
            str(profile.get("name") or "").strip().lower(),
            str(profile.get("display_name") or "").strip().lower(),
            str(profile.get("hermes_profile") or "").strip().lower(),
        }
        if wanted & candidates:
            return profile
    return None


def _preferred_hermes_profile_guidance(profiles: list[dict[str, Any]]) -> dict[str, str | None]:
    routine = _find_hermes_profile(profiles, "profile:default", "default", "workhorse")
    summary = _find_hermes_profile(profiles, "profile:mesh-sidecar", "mesh-sidecar", "sidecar")
    reasoning = _find_hermes_profile(profiles, "profile:mesh-reasoning", "mesh-reasoning", "reasoning-specialist")
    code = _find_hermes_profile(profiles, "code-specialist")
    return {
        "routine": str((routine or {}).get("display_name") or (routine or {}).get("hermes_profile") or (routine or {}).get("name") or "") or None,
        "summary": str((summary or {}).get("display_name") or (summary or {}).get("hermes_profile") or (summary or {}).get("name") or "") or None,
        "reasoning": str((reasoning or {}).get("display_name") or (reasoning or {}).get("hermes_profile") or (reasoning or {}).get("name") or "") or None,
        "code": str((code or {}).get("display_name") or (code or {}).get("hermes_profile") or (code or {}).get("name") or "") or None,
    }


def _recommend_local_profile(task: str, agents: list[dict[str, Any]], recommended_agent: str) -> dict[str, Any] | None:
    if recommended_agent != "hermes":
        return None
    hermes = next((agent for agent in agents if agent.get("name") == "hermes"), None)
    profiles = (hermes or {}).get("local_profiles") or next(
        (entry.get("local_profiles", []) for entry in MESH_AGENTS if entry.get("name") == "hermes"),
        [],
    )
    lowered = (task or "").strip().lower()

    def _find(*names: str) -> dict[str, Any] | None:
        return _find_hermes_profile(profiles, *names)

    if any(token in lowered for token in {"summary", "summarize", "digest", "route", "routing", "compress", "compression"}):
        profile = _find("profile:mesh-sidecar", "mesh-sidecar", "sidecar")
        if profile:
            return {
                "profile": profile.get("name"),
                "profile_display": profile.get("display_name") or profile.get("hermes_profile") or profile.get("name"),
                "reason": "Lightweight summary/routing task fits Hermes sidecar",
            }

    if any(token in lowered for token in CODE_KEYWORDS):
        profile = _find("code-specialist")
        if profile:
            if profile.get("installed"):
                return {
                    "profile": profile.get("name"),
                    "profile_display": profile.get("display_name") or profile.get("hermes_profile") or profile.get("name"),
                    "reason": "Code-heavy work fits Hermes code specialist",
                }
            fallback = _find("profile:default", "default", "workhorse")
            return {
                "profile": (fallback or {}).get("name") or "workhorse",
                "profile_display": (fallback or {}).get("display_name") or (fallback or {}).get("hermes_profile") or "default",
                "reason": "Code specialist is not installed locally; stay on Hermes workhorse",
            }

    if any(token in lowered for token in {"reason", "reasoning", "investigate", "root cause", "second pass"}):
        profile = _find("profile:mesh-reasoning", "mesh-reasoning", "reasoning-specialist")
        if profile:
            if profile.get("installed"):
                return {
                    "profile": profile.get("name"),
                    "profile_display": profile.get("display_name") or profile.get("hermes_profile") or profile.get("name"),
                    "reason": "Harder local reasoning fits Hermes reasoning specialist",
                }
            fallback = _find("profile:default", "default", "workhorse")
            return {
                "profile": (fallback or {}).get("name") or "workhorse",
                "profile_display": (fallback or {}).get("display_name") or (fallback or {}).get("hermes_profile") or "default",
                "reason": "Reasoning specialist is not installed locally; stay on Hermes workhorse",
            }

    profile = _find("profile:default", "default", "workhorse")
    if profile:
        return {
            "profile": profile.get("name"),
            "profile_display": profile.get("display_name") or profile.get("hermes_profile") or profile.get("name"),
            "reason": "Default Hermes workhorse profile",
        }
    return None


def _recommend_route(task: str, agents: list[dict[str, Any]]) -> dict[str, Any]:
    task_class, reason = _classify_task(task)
    summary = _build_routing_summary(agents, _state.get("services"), _state.get("memory_summary"))
    memory_heavy = any(token in (task or "").lower() for token in {"memory", "recall", "rag", "context", "history", "session"})
    memory_warning = next(iter(summary.get("warnings") or []), None) if not summary.get("memory_ready", True) and memory_heavy else None
    if task_class == "premium":
        primary = summary["guidance"]["premium"]
        premium_pool = summary.get("premium_pool", [])
        fallback = next((name for name in premium_pool if name != primary), summary["guidance"]["routine"])
        return {
            "task_class": task_class,
            "recommended_agent": primary,
            "model_tier": "premium",
            "fallback_agent": fallback,
            "recommended_profile": None,
            "profile_reason": None,
            "reason": reason,
            "memory_warning": memory_warning,
        }
    if task_class == "specialized":
        specialized = summary.get("specialized_agents", [])
        primary = specialized[0] if specialized else summary["guidance"]["routine"]
        fallback = summary["guidance"]["routine"]
        return {
            "task_class": task_class,
            "recommended_agent": primary,
            "model_tier": "specialized-local",
            "fallback_agent": fallback,
            "recommended_profile": None,
            "profile_reason": None,
            "reason": reason,
            "memory_warning": memory_warning,
        }
    profile = _recommend_local_profile(task, agents, summary["guidance"]["routine"])
    recommended_agent = summary["guidance"]["memory_heavy"] if memory_heavy else summary["guidance"]["routine"]
    return {
        "task_class": task_class,
        "recommended_agent": recommended_agent,
        "model_tier": "local-default",
        "fallback_agent": summary["guidance"]["premium"] if memory_heavy and not summary.get("memory_ready", True) else None,
        "recommended_profile": (profile or {}).get("profile"),
        "recommended_profile_display": (profile or {}).get("profile_display"),
        "profile_reason": (profile or {}).get("reason"),
        "reason": reason,
        "memory_warning": memory_warning,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _availability_overrides() -> dict[str, Any]:
    data = _read_json(AVAILABILITY_OVERRIDES_PATH)
    return data if isinstance(data, dict) else {}


def _pid_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _read_hermes_gateway_runtime() -> dict[str, Any] | None:
    runtime = _read_json(HERMES_GATEWAY_STATE_PATH)
    if runtime:
        return runtime
    return _read_json(HERMES_GATEWAY_PID_PATH)


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

async def _fetch_service_health(client: httpx.AsyncClient) -> dict[str, Any]:
    services: dict[str, Any] = {}

    # OpenViking
    try:
        headers = {"Authorization": f"Bearer {OPENVIKING_KEY}"} if OPENVIKING_KEY else {}
        r = await client.get(
            OPENVIKING_HEALTH,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        body = r.json()
        services["openviking"] = {
            "name": "OpenViking",
            "url": OPENVIKING_HEALTH,
            "status": "up" if body.get("healthy") else "degraded",
            "detail": body,
        }
    except Exception as exc:
        services["openviking"] = {"name": "OpenViking", "status": "down", "error": str(exc)}

    # Memory MCP
    try:
        r = await client.post(MEMORY_MCP_URL, json=MCP_PING, headers=MCP_HEADERS, timeout=HTTP_TIMEOUT)
        body = r.json()
        services["memory_mcp"] = {
            "name": "Memory MCP",
            "url": MEMORY_MCP_URL,
            "status": "up" if "result" in body else "degraded",
            "detail": body,
        }
    except Exception as exc:
        services["memory_mcp"] = {"name": "Memory MCP", "status": "down", "error": str(exc)}

    # Hermes Gateway
    try:
        r = await client.get(f"{HERMES_GATEWAY_URL}/health", timeout=HTTP_TIMEOUT)
        body = r.json()
        services["hermes_gateway"] = {
            "name": "Hermes Gateway",
            "url": HERMES_GATEWAY_URL,
            "status": "up" if body.get("ok") else "degraded",
            "detail": body,
        }
    except Exception as exc:
        runtime = _read_hermes_gateway_runtime() or {}
        pid = runtime.get("pid")
        gateway_state = runtime.get("gateway_state")
        platform_states = runtime.get("platforms", {})

        def _fresh(pdata: dict) -> bool:
            # platform records can outlive their platform config — ignore stale ones
            raw = str(pdata.get("updated_at") or "")
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(raw)
                return age.total_seconds() < 48 * 3600
            except ValueError:
                return False

        active_platforms = sorted(
            name for name, pdata in platform_states.items()
            if isinstance(pdata, dict) and _fresh(pdata)
            and pdata.get("state") not in ("disconnected", "stopped")
        )
        failing = sorted(
            name for name, pdata in platform_states.items()
            if isinstance(pdata, dict) and _fresh(pdata)
            and pdata.get("state") in ("retrying", "error", "failed")
        )
        if _pid_is_alive(pid) or gateway_state == "running":
            services["hermes_gateway"] = {
                "name": "Hermes Gateway",
                "url": HERMES_GATEWAY_URL,
                # No HTTP health endpoint in this mode — judge from runtime state.
                "status": "degraded" if failing else "up",
                **({"error": f"platform(s) failing: {', '.join(failing)}"} if failing else {}),
                "detail": {
                    "runtime_state": gateway_state or "running",
                    "pid": pid,
                    "http_health": "unavailable",
                    "active_platforms": active_platforms,
                    "mode": "cron-only" if not active_platforms else "messaging",
                    "updated_at": runtime.get("updated_at"),
                },
            }
        else:
            services["hermes_gateway"] = {"name": "Hermes Gateway", "status": "down", "error": str(exc)}

    # Ollama (embeddings)
    try:
        r = await client.get(OLLAMA_MODELS_URL, timeout=HTTP_TIMEOUT)
        body = r.json()
        model_ids = [m["id"] for m in body.get("data", [])]
        services["ollama"] = {
            "name": "Ollama",
            "url": OLLAMA_MODELS_URL,
            "status": "up",
            "models": model_ids,
        }
    except Exception as exc:
        services["ollama"] = {"name": "Ollama", "status": "down", "error": str(exc)}

    # MLX server (Qwen3.5-35B-A3B)
    mlx_up = False
    try:
        r = await client.get(MLX_MODELS_URL, timeout=HTTP_TIMEOUT)
        body = r.json()
        mlx_models = [m["id"] for m in body.get("data", [])]
        # prefer local path models (start with '/') over community hub models
        local = [m for m in mlx_models if m.startswith('/')]
        active_model = local[0] if local else (mlx_models[0] if mlx_models else "unknown")
        services["mlx_server"] = {
            "name": "MLX Server",
            "url": MLX_MODELS_URL,
            "status": "up",
            "models": mlx_models,
            "active_model": active_model,
        }
        mlx_up = True
    except Exception:
        services["mlx_server"] = {"name": "MLX Server", "status": "down"}

    # Track which LLM backend is active
    _state["llm_active"] = "mlx" if mlx_up else None

    # Whisper STT server
    try:
        r = await client.get(WHISPER_HEALTH, timeout=HTTP_TIMEOUT)
        body = r.json()
        services["whisper_stt"] = {
            "name": "Whisper STT",
            "url": WHISPER_HEALTH,
            "status": "up" if body.get("status") == "ok" else "degraded",
            "model": body.get("model", "unknown"),
            "loaded": body.get("loaded", False),
        }
    except Exception as exc:
        services["whisper_stt"] = {"name": "Whisper STT", "status": "down", "error": str(exc)}

    # MLX aux server (Qwen3.5 9B — summaries, routing, compression)
    try:
        r = await client.get(MLX_AUX_MODELS_URL, timeout=HTTP_TIMEOUT)
        body = r.json()
        aux_models = [m["id"] for m in body.get("data", [])]
        local_aux = [m for m in aux_models if m.startswith("/")]
        active_aux = local_aux[0] if local_aux else (aux_models[0] if aux_models else "unknown")
        services["mlx_aux"] = {
            "name": "MLX 9B",
            "url": MLX_AUX_MODELS_URL,
            "status": "up",
            "models": aux_models,
            "active_model": active_aux,
        }
    except Exception:
        services["mlx_aux"] = {"name": "MLX 9B", "status": "down"}

    # Screenpipe (screen activity capture + MCP)
    try:
        r = await client.get(f"{SCREENPIPE_URL}/health", timeout=HTTP_TIMEOUT)
        services["screenpipe"] = {
            "name": "Screenpipe",
            "url": SCREENPIPE_URL,
            "status": "up",
        }
    except Exception as exc:
        services["screenpipe"] = {"name": "Screenpipe", "status": "down", "error": str(exc)}

    return services


# Core mesh agents — always shown, status detected from live processes/services
MESH_AGENTS = [
    {
        "id": "claude",
        "name": "claude",
        "label": "Claude",
        "role": "Lead Role",
        "model": "Premium Lead Pool",
        "color": "#06b6d4",
        "tier": "premium",
        "routing_group": "premium-pool",
        "scarce": True,
        "default_for": [],
        "reserve_for": ["planning", "ambiguous debugging", "tricky refactors", "final review"],
        "fallback_to": "hermes",
        "detect": None,  # always online — we are Claude
    },
    {
        "id": "hermes",
        "name": "hermes",
        "label": "Hermes",
        "role": "Task Runner",
        "model": "local LLM",
        "color": "#a855f7",
        "tier": "local-default",
        "routing_group": "local-default",
        "scarce": False,
        "default_for": ["cron jobs", "summaries", "memory consolidation", "repo scans", "routine execution"],
        "reserve_for": [],
        "fallback_to": None,
        "local_profiles": [
            {
                "name": "workhorse",
                "model": "/Users/iris/.mlx/models/Qwen3.6-35B-A3B-OptiQ-4bit",
                "base_url": "http://127.0.0.1:8081/v1",
                "purpose": "default execution",
                "mode": "active",
            },
            {
                "name": "sidecar",
                "model": "/Users/iris/.mlx/models/Qwen3.5-9B-OptiQ-4bit",
                "base_url": "http://127.0.0.1:8083/v1",
                "purpose": "summaries, routing, compression, auxiliary tasks",
                "mode": "active",
            },
        ],
        "detect": "hermes",  # pgrep pattern
    },
]


async def _is_process_running(pattern: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "pgrep", "-f", pattern,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await proc.wait() == 0
    except Exception:
        return False


async def _fetch_agents(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Build mesh agent list from runtime detection."""
    defs_by_name = {agent["name"]: agent for agent in MESH_AGENTS}

    agents = []
    for key, defn in defs_by_name.items():
        if key == "claude":
            runtime_status = "online"
            task = "Claude lead role — Claude Code (Fable 5)"
        elif defn["detect"] and await _is_process_running(defn["detect"]):
            runtime_status = "online"
            task = None
        else:
            runtime_status = "offline"
            task = None

        agents.append({
            "id": defn["id"],
            "name": defn["name"],
            "label": defn["label"],
            "role": defn["role"],
            "model": defn["model"],
            "color": defn["color"],
            "status": runtime_status,
            "runtime_status": runtime_status,
            "health_status": "unknown",
            "status_reason": None,
            "task": task,
            "host": os.getenv("MESH_HOST", "localhost"),
            "address": f"{key}@teamirs.aimaestro.local",
            "tier": defn.get("tier"),
            "routing_group": defn.get("routing_group"),
            "scarce": defn.get("scarce", False),
            "default_for": defn.get("default_for", []),
            "reserve_for": defn.get("reserve_for", []),
            "fallback_to": defn.get("fallback_to"),
            "local_profiles": defn.get("local_profiles", []),
        })

    return agents


def _finalize_agents(
    agents: list[dict[str, Any]],
    services: dict[str, Any],
    last_active: dict[str, str | None],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    defs_by_name = {entry["name"]: entry for entry in MESH_AGENTS}
    hermes_service = services.get("hermes_gateway", {})
    availability_overrides = _availability_overrides()

    for agent in agents:
        enriched = dict(agent)
        name = str(agent.get("name", "")).lower()
        runtime_status = agent.get("runtime_status", agent.get("status", "offline"))
        effective_last_active = last_active.get(name) or agent.get("last_active")
        activity_status, activity_age_seconds = _activity_summary(effective_last_active)
        override = availability_overrides.get(name, {}) if isinstance(availability_overrides.get(name), dict) else {}
        availability_status = "available"
        availability_reason = None

        if runtime_status == "offline" and activity_status == "stale":
            availability_status = "offline"
        if override:
            availability_status = override.get("availability", availability_status)
            availability_reason = override.get("note")

        if name == "hermes":
            health_status = "healthy" if hermes_service.get("status") == "up" else "degraded"
            status_reason = (
                "Hermes runtime detected; gateway is running cron-only"
                if hermes_service.get("detail", {}).get("mode") == "cron-only"
                else "Hermes runtime detected"
            )
        elif runtime_status == "online":
            health_status = "healthy"
            status_reason = "Local runtime detected"
        else:
            health_status = "offline"
            status_reason = "No local runtime detected"

        if runtime_status == "online":
            presence_kind = "local-runtime"
            presence_status = "online"
            presence_reason = "Local runtime detected"
        elif str(agent.get("registration_status", "")) == "registered":
            presence_kind = "external-registration"
            presence_status = "registered"
            presence_reason = "Registered in the mesh; no local runtime detected"
        else:
            presence_kind = "local-runtime"
            presence_status = "offline"
            presence_reason = "No local runtime detected"

        enriched["last_active"] = effective_last_active
        enriched["activity_status"] = activity_status
        enriched["activity_age_seconds"] = activity_age_seconds
        enriched["recently_active"] = activity_status in {"live", "recent", "idle"}
        enriched["availability_status"] = availability_status
        enriched["availability_reason"] = availability_reason
        enriched["health_status"] = health_status
        enriched["status_reason"] = status_reason
        enriched["presence"] = {
            "kind": presence_kind,
            "status": presence_status,
            "reason": presence_reason,
        }
        profiles = list(defs_by_name.get(name, {}).get("local_profiles", agent.get("local_profiles", [])))
        if name == "hermes":
            existing_names = {str(item.get("name", "")) for item in profiles}
            for profile in _discover_hermes_native_profiles():
                if str(profile.get("name", "")) not in existing_names:
                    profiles.append(profile)
        enriched["local_profiles"] = [_enrich_local_profile(name, profile) for profile in profiles]
        result.append(enriched)

    return result


def _detect_voice_active() -> bool:
    """Check if atlas-voice is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "atlas-voice"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def _schedule_interval_seconds(schedule: dict | str | None) -> int | None:
    """Extract interval in seconds from a Hermes schedule object."""
    if not isinstance(schedule, dict):
        return None
    kind = schedule.get("kind")
    if kind == "interval":
        minutes = schedule.get("minutes")
        if minutes:
            return int(minutes) * 60
    elif kind == "cron":
        # Parse common cron patterns to get interval
        expr = schedule.get("expr", "")
        parts = expr.split()
        if len(parts) == 5:
            minute, hour = parts[0], parts[1]
            if hour == "*" and minute.isdigit():
                return int(minute) * 60  # every N minutes
            elif minute == "0" and hour.isdigit():
                return int(hour) * 3600  # daily at hour
            elif minute == "0" and hour == "2":
                return 24 * 3600  # 2am daily
    return None


def _read_cron_jobs() -> list[dict[str, Any]]:
    """Read and parse ~/.hermes/cron/jobs.json."""
    if not CRON_JOBS_PATH.exists():
        return []
    try:
        raw = json.loads(CRON_JOBS_PATH.read_text())
        jobs_raw = raw.get("jobs", raw) if isinstance(raw, dict) else raw
        jobs = []
        for j in jobs_raw:
            next_run = j.get("next_run_at")
            schedule = j.get("schedule", {})
            interval_seconds = _schedule_interval_seconds(schedule)
            # Build schedule display
            sched_display = (
                j.get("schedule_display")
                or (schedule.get("display") if isinstance(schedule, dict) else None)
                or (schedule.get("expr") if isinstance(schedule, dict) else None)
            )
            # Prompt snippet (first 80 chars, strip newlines)
            raw_prompt = j.get("prompt", "")
            prompt_snippet = re.sub(r'\s+', ' ', raw_prompt).strip()[:80] if raw_prompt else None

            jobs.append(
                {
                    "id": j.get("id"),
                    "name": j.get("name"),
                    "schedule_display": sched_display,
                    "interval_seconds": interval_seconds,
                    "last_run_at": j.get("last_run_at"),
                    "next_run_at": next_run,
                    "next_run_in_seconds": _seconds_until(next_run),
                    "last_status": j.get("last_status"),
                    "enabled": j.get("enabled", True),
                    "state": j.get("state"),
                    "prompt_snippet": prompt_snippet,
                }
            )
        return jobs
    except Exception:
        return []


def _fetch_system_metrics() -> dict[str, Any]:
    """Collect CPU, RAM, disk, uptime, and MLX model memory usage."""
    mem = psutil.virtual_memory()
    total_ram = mem.total
    used_ram = mem.used
    ram_pct = mem.percent

    cpu_pct = psutil.cpu_percent(interval=None)

    # Disk (root partition)
    disk = psutil.disk_usage('/')
    disk_pct = round(disk.percent, 1)
    disk_used_gb = round(disk.used / 1e9, 1)
    disk_total_gb = round(disk.total / 1e9, 1)

    # System uptime
    uptime_seconds = int(datetime.now(timezone.utc).timestamp() - psutil.boot_time())

    # 1-minute load average (POSIX; graceful fallback on Windows)
    load_1m = round(psutil.getloadavg()[0], 2) if hasattr(psutil, 'getloadavg') else 0.0

    # MLX process memory
    mlx_ram_bytes = 0
    mlx_pid = None
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'mlx_lm' in cmdline or 'mlx-server' in cmdline:
                mlx_ram_bytes = proc.info['memory_info'].rss
                mlx_pid = proc.info['pid']
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    mlx_ram_pct = round((mlx_ram_bytes / total_ram) * 100, 1) if total_ram else 0

    return {
        "cpu_pct": round(cpu_pct, 1),
        "ram_pct": round(ram_pct, 1),
        "ram_used_gb": round(used_ram / 1e9, 1),
        "ram_total_gb": round(total_ram / 1e9, 1),
        "mlx_ram_pct": mlx_ram_pct,
        "mlx_ram_gb": round(mlx_ram_bytes / 1e9, 1),
        "mlx_pid": mlx_pid,
        "local_pct": round(mlx_ram_pct, 1),
        "disk_pct": disk_pct,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "uptime_seconds": uptime_seconds,
        "load_1m": load_1m,
    }


async def _fetch_memories(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch recent memories from Memory MCP."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "memory_recall",
            "arguments": {
                "query": "recent session activity",
                "limit": 5,
                "score_threshold": 0.01,
            },
        },
    }
    try:
        r = await client.post(MEMORY_MCP_URL, json=payload, headers=MCP_HEADERS, timeout=HTTP_TIMEOUT)
        body = r.json()
        result = body.get("result", {})
        # result may be a list or dict with content
        content = result if isinstance(result, list) else result.get("content", [])
        memories = []
        for item in content:
            if isinstance(item, dict):
                memories.append(
                    {
                        "text": item.get("text", item.get("content", str(item))),
                        "score": item.get("score"),
                        "id": item.get("id"),
                    }
                )
            elif isinstance(item, str):
                memories.append({"text": item})
        return memories
    except Exception:
        return []


def _parse_log_timestamp(line: str) -> datetime | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", line)
    if not match:
        return None
    raw = match.group(1).replace(" ", "T")
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_memory_events(memory_monitor_log: list[str], limit: int = 12) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in reversed(memory_monitor_log or []):
        lowered = line.lower()
        event_type = None
        status = "info"
        source = "memory-monitor"
        latency_ms = None
        resource = {}

        latency_match = re.search(r"(\d+(?:\.\d+)?)\s*ms\b", lowered)
        if latency_match:
            latency_ms = int(float(latency_match.group(1)))

        free_match = re.search(r"free=(\d+)\s*mb", lowered)
        used_match = re.search(r"used=(\d+)\s*gb", lowered)
        if free_match:
            resource["free_mb"] = int(free_match.group(1))
        if used_match:
            resource["used_gb"] = int(used_match.group(1))

        if any(token in lowered for token in ("error", "exception", "fail", "timeout")):
            event_type = "recall_failed" if "recall" in lowered else "write_failed" if any(token in lowered for token in ("write", "store", "ingest", "sync")) else "memory_error"
            status = "error"
        elif "low memory" in lowered:
            event_type = "memory_pressure"
            status = "warn"
        elif any(token in lowered for token in ("recalled", "recall ok", "recall complete", "recall success")):
            event_type = "recall_ok"
            status = "ok"
        elif any(token in lowered for token in ("stored", "write ok", "ingest complete", "write success", "synced")):
            event_type = "write_ok"
            status = "ok"
        elif "consolidat" in lowered or "compact" in lowered:
            event_type = "consolidation"
            status = "ok" if "error" not in lowered and "fail" not in lowered else "error"

        if not event_type:
            continue

        ts = _parse_log_timestamp(line)
        summary = re.sub(r"\s+", " ", line).strip()
        if len(summary) > 160:
            summary = f"{summary[:157]}..."
        events.append(
            {
                "ts": ts.isoformat() if ts else None,
                "type": event_type,
                "status": status,
                "source": source,
                "latency_ms": latency_ms,
                "resource": resource or None,
                "summary": summary,
            }
        )
        if len(events) >= limit:
            break
    return events


def _build_memory_summary(
    memories: list[dict[str, Any]],
    services: dict[str, Any],
    memory_monitor_log: list[str],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    openviking_status = services.get("openviking", {}).get("status", "unknown")
    substrate_status = services.get("memory_mcp", {}).get("status", "unknown")
    scores = [float(item.get("score")) for item in memories if item.get("score") is not None]
    events = _extract_memory_events(memory_monitor_log, limit=12)
    last_event_at: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    recent_errors = sum(1 for event in events if event.get("status") == "error")
    recent_successes = sum(1 for event in events if event.get("status") == "ok")
    pressure_events = [event for event in events if event.get("type") == "memory_pressure"]
    causes: list[dict[str, str]] = []

    if events:
        last_event_at = events[0].get("ts")
        last_success_at = next((event.get("ts") for event in events if event.get("status") == "ok"), None)
        last_error_at = next((event.get("ts") for event in events if event.get("status") == "error"), None)

    freshness_seconds: int | None = None
    if last_event_at:
        try:
            freshness_seconds = max(0, int((now - datetime.fromisoformat(last_event_at)).total_seconds()))
        except ValueError:
            freshness_seconds = None

    recall_status = "up" if memories else ("degraded" if substrate_status == "up" else substrate_status)
    status = "up"
    warnings: list[str] = []
    if substrate_status != "up":
        status = "down" if substrate_status == "down" else "degraded"
        warnings.append("Memory MCP is not healthy.")
        causes.append({"kind": "substrate", "severity": status, "summary": "Memory MCP is not healthy."})
    elif recent_errors > recent_successes and recent_errors > 0:
        status = "degraded"
        warnings.append("Recent memory monitor activity is error-heavy.")
        causes.append({"kind": "operations", "severity": "degraded", "summary": "Recent memory operations are error-heavy."})
    elif freshness_seconds is not None and freshness_seconds > 1800:
        status = "degraded"
        warnings.append("Memory activity looks stale.")
        causes.append({"kind": "stale", "severity": "degraded", "summary": "Memory activity looks stale."})
    if pressure_events:
        status = "degraded" if status == "up" else status
        latest_pressure = pressure_events[0].get("resource") or {}
        free_mb = latest_pressure.get("free_mb")
        if free_mb is not None:
            warnings.append(f"Memory pressure detected: only {free_mb}MB free.")
            causes.append({"kind": "pressure", "severity": "degraded", "summary": f"Only {free_mb}MB free on host."})
        else:
            warnings.append("Memory pressure detected in the monitor log.")
            causes.append({"kind": "pressure", "severity": "degraded", "summary": "Memory pressure detected in the monitor log."})
    if openviking_status == "down":
        warnings.append("OpenViking transport is down.")
        causes.append({"kind": "gateway", "severity": "down", "summary": "OpenViking transport is down."})

    priority = {"substrate": 0, "gateway": 1, "pressure": 2, "operations": 3, "stale": 4}
    causes.sort(key=lambda cause: priority.get(cause.get("kind", "stale"), 99))
    primary_cause = causes[0] if causes else {"kind": "healthy", "severity": "up", "summary": "Memory path is healthy."}

    return {
        "status": status,
        "gateway_status": openviking_status,
        "substrate_status": substrate_status,
        "recall_status": recall_status,
        "recall_count": len(memories),
        "average_score": round(sum(scores) / len(scores), 3) if scores else None,
        "top_score": round(max(scores), 3) if scores else None,
        "freshness_seconds": freshness_seconds,
        "last_event_at": last_event_at,
        "last_success_at": last_success_at,
        "last_error_at": last_error_at,
        "recent_successes": recent_successes,
        "recent_errors": recent_errors,
        "pressure_events": len(pressure_events),
        "component_health": {
            "gateway": openviking_status,
            "substrate": substrate_status,
            "pressure": "degraded" if pressure_events else "up",
            "freshness": "degraded" if freshness_seconds is not None and freshness_seconds > 1800 else "up",
        },
        "primary_cause": primary_cause,
        "causes": causes,
        "warnings": warnings,
    }


def _fetch_logs(n: int = 60) -> dict[str, list[str]]:
    """Return last N lines from MLX error log and memory monitor log."""
    def tail(path: Path, count: int) -> list[str]:
        try:
            if not path.exists():
                return []
            lines = path.read_text(errors="replace").splitlines()
            return lines[-count:] if len(lines) > count else lines
        except Exception:
            return []
    return {
        "mlx": tail(MLX_ERROR_LOG, n),
        "memory": tail(MEMORY_MONITOR_LOG, 30),
    }


def _fetch_amp_messages() -> list[dict]:
    """Read recent AMP messages for claude (inbox + sent)."""
    messages = []
    try:
        claude_dir = AMP_AGENTS_DIR / "claude" / "messages"
        for folder in ("inbox", "sent"):
            folder_path = claude_dir / folder
            if not folder_path.exists():
                continue
            for subdir in folder_path.iterdir():
                if not subdir.is_dir():
                    continue
                for msg_file in sorted(subdir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]:
                    try:
                        data = json.loads(msg_file.read_text())
                        messages.append({
                            "id": data.get("id", msg_file.stem),
                            "direction": folder,
                            "from": data.get("from", data.get("sender", "?")),
                            "to": data.get("to", data.get("recipient", "?")),
                            "subject": data.get("subject", ""),
                            "body": (data.get("body", data.get("message", data.get("content", ""))) or "")[:300],
                            "timestamp": data.get("timestamp", data.get("sent_at", "")),
                            "type": data.get("type", "notification"),
                        })
                    except Exception:
                        continue
    except Exception:
        pass
    messages.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
    return messages[:20]


def _fetch_hermes_status() -> dict:
    """Get latest Hermes session info."""
    sessions_overview = _fetch_hermes_sessions_overview()
    background_tasks = _fetch_hermes_background_tasks()
    try:
        sessions = sorted(
            [f for f in HERMES_SESSIONS_DIR.glob("session_*.json") if "request_dump" not in f.name],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not sessions:
            return {
                "status": "no sessions",
                "sessions": sessions_overview,
                "background_tasks": background_tasks,
                "session_count": sessions_overview.get("session_count", 0),
                "search_ready": sessions_overview.get("search_ready", False),
            }
        latest = json.loads(sessions[0].read_text())
        return {
            "session_id": sessions[0].stem,
            "model": latest.get("model", latest.get("default", "?")),
            "status": latest.get("status", "unknown"),
            "task": latest.get("task", latest.get("taskDescription")),
            "created_at": latest.get("created_at", ""),
            "modified": sessions[0].stat().st_mtime,
            "session_count": sessions_overview.get("session_count", 0),
            "search_ready": sessions_overview.get("search_ready", False),
            "resume_target": sessions_overview.get("resume_target"),
            "latest_title": sessions_overview.get("latest_title"),
            "latest_profile": sessions_overview.get("latest_profile"),
            "latest_source": sessions_overview.get("latest_source"),
            "latest_updated_at": sessions_overview.get("latest_updated_at"),
            "sessions": sessions_overview,
            "background_tasks": background_tasks,
        }
    except Exception:
        return {
            "status": "unavailable",
            "sessions": sessions_overview,
            "background_tasks": background_tasks,
            "session_count": sessions_overview.get("session_count", 0),
            "search_ready": sessions_overview.get("search_ready", False),
        }


def _fetch_memory_monitor_log(n: int = 50) -> list[str]:
    """Return last N lines from the memory monitor log."""
    try:
        if not MEMORY_MONITOR_LOG.exists():
            return []
        lines = MEMORY_MONITOR_LOG.read_text().splitlines()
        return lines[-n:] if len(lines) > n else lines
    except Exception:
        return []


async def _fetch_trending_repos(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch top 5 trending GitHub repos (new repos last 7 days by stars). Cached 6h."""
    import time
    if time.monotonic() - _st._trending_cache_time < TRENDING_CACHE_TTL:
        return _state["trending_repos"]  # return cached

    try:
        since = (datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=7)).strftime("%Y-%m-%d")

        r = await client.get(
            GITHUB_SEARCH_URL,
            params={
                "q": f"created:>{since}",
                "sort": "stars",
                "order": "desc",
                "per_page": 5,
            },
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            timeout=10.0,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        repos = []
        for item in items:
            repos.append({
                "id": item.get("id"),
                "name": item.get("full_name"),
                "description": (item.get("description") or "")[:120],
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language"),
                "url": item.get("html_url"),
                "created_at": item.get("created_at"),
                "topics": item.get("topics", [])[:4],
            })
        _st._trending_cache_time = time.monotonic()
        return repos
    except Exception as exc:
        print(f"[trending] fetch error: {exc}")
        return _state.get("trending_repos", [])  # keep stale data on error


# ---------------------------------------------------------------------------
# OpenViking watchdog
# ---------------------------------------------------------------------------



def _ov_restart_sync() -> str:
    """Blocking restart — runs in executor. Returns a log message."""
    import time
    # Kill any zombie processes holding the lock
    subprocess.run(["pkill", "-f", "create_app"], capture_output=True)
    time.sleep(1)

    # Remove stale lock files
    for path in (OV_LOCK_PATH, OV_PID_PATH):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    # Restart via launchctl
    subprocess.run(
        ["launchctl", "unload", str(OPENVIKING_PLIST)],
        capture_output=True,
    )
    time.sleep(1)
    subprocess.run(
        ["launchctl", "load", str(OPENVIKING_PLIST)],
        capture_output=True,
    )

    _st._ov_last_restart = time.monotonic()
    return "[watchdog] OpenViking restarted via launchctl"


async def _openviking_watchdog():
    """Polls OpenViking health every 30s and restarts if down."""
    import time
    await asyncio.sleep(15)  # give it time to come up on first boot

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Skip check if we just restarted — give it time to boot
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


# ---------------------------------------------------------------------------
# Background polling task
# ---------------------------------------------------------------------------

def _fetch_agent_last_active(hermes_status: dict, amp_messages: list) -> dict[str, str | None]:
    """Return {agent_name: iso_timestamp} for real last-active times."""
    result: dict[str, str | None] = {}

    # Hermes: use latest session mtime from hermes_status
    hermes_ts = None
    modified = hermes_status.get("modified")
    if modified:
        try:
            from datetime import timezone as _tz
            hermes_ts = datetime.fromtimestamp(modified, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    # Fall back to AMP bridge log last entry
    if not hermes_ts:
        for log_path in _BRIDGE_LOGS:
            try:
                lines = [l for l in log_path.read_text().splitlines() if l.strip()]
                if lines:
                    m = re.match(r'\[([^\]]+)\]', lines[-1])
                    if m:
                        hermes_ts = m.group(1)
                        break
            except Exception:
                pass
    result["hermes"] = hermes_ts

    # Claude: latest Claude session file mtime (sessions are .jsonl under projects/)
    claude_ts = None
    try:
        from datetime import timezone as _tz
        projects_dir = Path.home() / ".claude" / "projects"
        files = sorted(projects_dir.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            claude_ts = datetime.fromtimestamp(files[0].stat().st_mtime, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    result["claude"] = claude_ts


    return result



# ---------------------------------------------------------------------------
# Additional helpers (compute, MLX, brief, AMP, RAG utils)
# ---------------------------------------------------------------------------

def _port_is_localhost_only(port: int) -> bool:
    """Return True if the port is only bound to 127.0.0.1 (not 0.0.0.0 or ::)."""
    try:
        result = subprocess.run(
            ["lsof", "-iTCP", f":{port}", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().splitlines()
        for line in lines[1:]:  # skip header
            parts = line.split()
            if len(parts) < 9:
                continue
            addr = parts[8]
            host = addr.rsplit(":", 1)[0].strip("[]")
            if host not in ("127.0.0.1", "::1", "localhost"):
                return False
        return len(lines) > 1
    except Exception:
        return False

def _compute_signal_watcher_state(jobs: list, memories: list) -> dict:
    sw_job = next((j for j in jobs if "signal" in j.get("skill", "").lower() or "signal" in j.get("description", "").lower()), None)
    last_run: str | None = None
    next_run_at: str | None = None
    next_run_in_seconds: int | None = None
    if sw_job:
        last_run = sw_job.get("last_run")
        next_run_at = sw_job.get("next_run_at")
        next_run_in_seconds = _seconds_until(next_run_at)
    findings_today = 0
    top_finding: str | None = None
    today = datetime.now(timezone.utc).date().isoformat()
    for mem in memories:
        body = mem.get("body", "") or mem.get("content", "") or ""
        if "AI SIGNAL" in body and today in body:
            findings_today += 1
            if top_finding is None:
                top_finding = body[:200]
    return {
        "last_run": last_run,
        "next_run_at": next_run_at,
        "next_run_in_seconds": next_run_in_seconds,
        "findings_today": findings_today,
        "top_finding": top_finding,
        "job_active": sw_job is not None,
    }


def _compute_security_posture_state() -> dict:
    port_results = [_port_is_localhost_only(port) for _, port in MESH_PORTS]
    services_posture = [
        {"name": name, "port": port, "localhost_only": ok}
        for (name, port), ok in zip(MESH_PORTS, port_results)
    ]
    tailscale_up = False
    try:
        ts = subprocess.run(
            ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        ts_data = json.loads(ts.stdout)
        tailscale_up = ts_data.get("BackendState") == "Running"
    except Exception:
        pass
    xsearch_ok = False
    try:
        r = subprocess.run(
            ["hermes", "toolset", "status", "x_search"],
            capture_output=True, text=True, timeout=5,
        )
        xsearch_ok = "available" in r.stdout.lower() or r.returncode == 0
    except Exception:
        pass
    all_local = all(s["localhost_only"] for s in services_posture)
    return {
        "services": services_posture,
        "tailscale_up": tailscale_up,
        "xsearch_oauth": xsearch_ok,
        "all_localhost_bound": all_local,
        "score": sum([all_local, tailscale_up, xsearch_ok]),
        "max_score": 3,
    }

def _mlx_model_id() -> str:
    """Return the first available model ID from the MLX server, fallback string."""
    try:
        resp = httpx.get(MLX_MODELS_URL, timeout=2.0)
        data = resp.json()
        models = data.get("data", [])
        if models:
            return models[0]["id"]
    except Exception:
        pass
    return "local"


async def _mlx_chat_stream(
    messages: list[dict],
    max_tokens: int = 2048,
) -> AsyncGenerator[str, None]:
    """
    Stream chat completions from MLX server using OpenAI-compatible SSE.
    Yields SSE-formatted strings: 'data: {...}\n\n'
    """
    model = _mlx_model_id()
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    url = f"{MLX_SERVER_URL}/v1/chat/completions"

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield f"data: {json.dumps({'error': f'MLX error {resp.status_code}: {body.decode()}'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return
                try:
                    chunk = json.loads(raw)
                    delta = chunk["choices"][0]["delta"]
                    token = delta.get("content", "")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                except Exception:
                    continue


async def _mlx_chat_complete(messages: list[dict], max_tokens: int = 1024) -> str:
    """Non-streaming completion from MLX. Returns full response text."""
    model = _mlx_model_id()
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    url = f"{MLX_SERVER_URL}/v1/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"[MLX unavailable: {exc}]"


def _git_log_since(repo: Path, hours: int = 24) -> list[str]:
    """Return one-line git log entries from a repo since N hours ago."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={hours} hours ago", "--oneline", "--no-merges"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().splitlines()
        return lines[:10]  # cap at 10 per repo
    except Exception:
        return []


def _collect_git_activity(hours: int = 24) -> dict[str, list[str]]:
    """Scan ~/Projects for git repos with recent activity."""
    activity: dict[str, list[str]] = {}
    if not PROJECTS_DIR.exists():
        return activity
    for repo in PROJECTS_DIR.iterdir():
        if (repo / ".git").exists():
            commits = _git_log_since(repo, hours)
            if commits:
                activity[repo.name] = commits
    return activity


async def _build_brief_context() -> str:
    """Assemble context for the morning brief."""
    lines: list[str] = []

    # Git activity
    activity = _collect_git_activity(24)
    if activity:
        lines.append("## Recent Git Activity (last 24h)")
        for repo, commits in activity.items():
            lines.append(f"\n**{repo}**")
            for c in commits:
                lines.append(f"  - {c}")
    else:
        lines.append("## Git Activity\nNo commits in the last 24 hours.")

    # Agent + service state
    agents = _state.get("agents", [])
    services = _state.get("services", {})
    if agents or services:
        lines.append("\n## Mesh State")
        for a in agents:
            status = a.get("status", "unknown")
            lines.append(f"  - {a.get('name', '?')}: {status}")
        for svc, info in services.items():
            st = info.get("status", "?") if isinstance(info, dict) else str(info)
            lines.append(f"  - {svc}: {st}")

    # Recent memories
    memories = _state.get("memories", [])
    if memories:
        lines.append("\n## Recent Memory Activity")
        for m in memories[:5]:
            content = m.get("content", m.get("text", str(m)))[:120]
            lines.append(f"  - {content}")

    # Pending items from subconscious
    pending_path = Path.home() / ".claude" / "subconscious" / "pending_items.md"
    if pending_path.exists():
        pending_text = pending_path.read_text().strip()
        if pending_text:
            lines.append("\n## Pending Items")
            # Extract only In Progress + Backlog sections, skip Completed
            in_section = False
            for line in pending_text.split("\n"):
                if line.startswith("## Completed") or line.startswith("## Deferred"):
                    in_section = False
                elif line.startswith("##"):
                    in_section = "completed" not in line.lower() and "deferred" not in line.lower()
                elif in_section and line.strip():
                    lines.append(f"  {line}")

    # System snapshot
    system = _state.get("system", {})
    if system:
        cpu = system.get("cpu_percent", "?")
        ram = system.get("memory_percent", "?")
        lines.append(f"\n## System\n  CPU: {cpu}%  RAM: {ram}%")

    return "\n".join(lines)


async def _generate_brief(force: bool = False) -> str:
    """Generate or return cached morning brief."""
    now = datetime.now(timezone.utc)
    age_ok = False
    if _brief_cache["generated_at"]:
        age = (now - _brief_cache["generated_at"]).total_seconds() / 3600
        age_ok = age < BRIEF_REFRESH_HOURS

    if not force and age_ok and _brief_cache["text"]:
        return _brief_cache["text"]

    # Wait a bit for state to populate on startup
    if not _state.get("last_updated"):
        return "Mesh state loading — try again in a moment."

    context = await _build_brief_context()
    messages = [
        {
            "role": "system",
            "content": (
                "You are Claude, lead AI agent. Generate a concise morning brief for Punch "
                "(the operator). Cover: what changed overnight, what needs attention, "
                "what's healthy. Be direct and specific. Max 200 words. No fluff."
            ),
        },
        {"role": "user", "content": f"Current mesh snapshot:\n\n{context}\n\nGenerate the brief."},
    ]

    try:
        text = await asyncio.wait_for(_mlx_chat_complete(messages, max_tokens=400), timeout=15.0)
    except asyncio.TimeoutError:
        return "Brief generation timed out — MLX may be busy. Try again in a moment."
    _brief_cache["text"] = text
    _brief_cache["generated_at"] = now
    return text


async def _generate_brief_on_startup():
    """Wait for first poll to complete, then generate brief."""
    # Wait until state is populated (up to 60s)
    for _ in range(12):
        await asyncio.sleep(5)
        if _state.get("last_updated"):
            break
    await _generate_brief()

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

AMP_ALLOWED_TYPES = {"notification", "request", "task", "response"}

def _validate_agent_message(payload: dict[str, Any]) -> dict[str, Any]:
    def _clean_ident(key: str, default: str | None = None) -> str:
        value = str(payload.get(key) or default or "").strip()
        if not value:
            raise HTTPException(status_code=422, detail=f"{key} required")
        if len(value) > 100 or not re.match(r"^[a-zA-Z0-9._@\-]+$", value):
            raise HTTPException(status_code=422, detail=f"{key} invalid")
        return value

    def _clean_text(key: str, *, required: bool = False, default: str = "") -> str:
        value = str(payload.get(key) or default).strip()
        if required and not value:
            raise HTTPException(status_code=422, detail=f"{key} required")
        if len(value) > 4000:
            raise HTTPException(status_code=422, detail=f"{key} too long")
        return value

    files: list[str] = []
    raw_files = payload.get("files") or []
    if isinstance(raw_files, list):
        for item in raw_files[:20]:
            cleaned = str(item).strip()
            if cleaned:
                files.append(cleaned[:300])

    return {
        "from": _clean_ident("from_agent"),
        "to": _clean_ident("to_agent"),
        "role": _clean_ident("role", "handoff"),
        "task": _clean_text("task"),
        "summary": _clean_text("summary", required=True),
        "details": _clean_text("details"),
        "files": files,
    }

_BRIDGE_LOGS = [
    Path.home() / ".agent-messaging/agents/hermes/bridge.log",
]
_BRIDGE_EVENT_RE = re.compile(
    r'\[(?P<ts>[^\]]+)\] \[(?P<id>[^\]]+)\] (?P<msg>.+)'
)


def _fetch_amp_events() -> list[dict]:
    events: list[dict] = []
    for log_path in _BRIDGE_LOGS:
        agent = log_path.parts[-3]
        try:
            lines = log_path.read_text().splitlines()[-60:]
        except Exception:
            continue
        for line in lines:
            m = _BRIDGE_EVENT_RE.match(line)
            if not m:
                continue
            msg = m.group("msg")
            if "responded via" in msg or "reply sent" in msg or "route=" in msg:
                events.append({
                    "agent": agent,
                    "ts": m.group("ts"),
                    "id": m.group("id"),
                    "msg": msg,
                })
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:30]


def _ov_headers() -> dict:
    h = {"X-OpenViking-Account": OPENVIKING_ACCOUNT, "X-OpenViking-User": OPENVIKING_USER}
    if OPENVIKING_KEY:
        h["Authorization"] = f"Bearer {OPENVIKING_KEY}"
    return h

def _build_claude_messages(req: "ChatRequest") -> list[dict]:
    """Build OpenAI-format messages for Claude chat."""
    mesh_status = json.dumps(
        {
            "services": {k: v.get("status") for k, v in _state["services"].items()},
            "agents": [{"name": a["name"], "status": a["status"]} for a in _state["agents"]],
            "last_updated": _state["last_updated"],
        },
        indent=2,
    )
    system_content = CLAUDE_SYSTEM_PROMPT.format(mesh_status=mesh_status)
    messages: list[dict] = [{"role": "system", "content": system_content}]
    for m in req.history[-10:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": req.message})
    return messages

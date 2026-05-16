"""
Mission Control Dashboard — FastAPI Backend
Real-time backend for local AI mesh monitoring.
Port: 8000
"""

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import re
import signal
import socket
import psutil
import uuid
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

OPENVIKING_URL = os.getenv("OPENVIKING_URL", "http://127.0.0.1:1933")
OPENVIKING_HEALTH = f"{OPENVIKING_URL}/health"
OPENVIKING_KEY = os.getenv("OPENVIKING_KEY", "")
OPENVIKING_ACCOUNT = os.getenv("OPENVIKING_ACCOUNT", "teamirs")
OPENVIKING_USER = os.getenv("OPENVIKING_USER", "iris")
RAG_INBOX = Path.home() / "Documents" / "rag" / "inbox"

MEMORY_MCP_URL = os.getenv("MEMORY_MCP_URL", "http://127.0.0.1:2033/mcp")
HERMES_GATEWAY_URL = os.getenv("HERMES_GATEWAY_URL", "http://127.0.0.1:18789")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODELS_URL = f"{OLLAMA_URL}/v1/models"

MEMORY_MONITOR_LOG = Path.home() / ".mlx" / "logs" / "memory-monitor.log"
MLX_ERROR_LOG = Path.home() / ".mlx" / "logs" / "mlx-server.error.log"
AMP_AGENTS_DIR = Path.home() / ".agent-messaging" / "agents"
HERMES_SESSIONS_DIR = Path.home() / ".hermes" / "sessions"
HERMES_GATEWAY_STATE_PATH = Path.home() / ".hermes" / "gateway_state.json"
HERMES_GATEWAY_PID_PATH = Path.home() / ".hermes" / "gateway.pid"
HERMES_HOME = Path.home() / ".hermes"
HERMES_PROFILES_DIR = HERMES_HOME / "profiles"
LOCAL_BIN_DIR = Path.home() / ".local" / "bin"
HERMES_BIN = Path(shutil.which("hermes") or "/Users/iris/.local/bin/hermes")
AIMAESTRO_AGENTS_DIR = Path.home() / ".aimaestro" / "agents"
AIMAESTRO_REGISTRY_PATH = AIMAESTRO_AGENTS_DIR / "registry.json"
AVAILABILITY_OVERRIDES_PATH = Path.home() / ".mesh" / "availability_overrides.json"
PERMISSION_AUDIT_LOG_PATH = Path.home() / ".mesh" / "permission_audit.jsonl"
AGENT_INBOX_PATH = Path.home() / ".mesh" / "agent_inbox.jsonl"
HERMES_BACKGROUND_TASKS_PATH = Path.home() / ".mesh" / "hermes_background_tasks.json"
HERMES_BACKGROUND_LOG_DIR = Path.home() / ".mesh" / "hermes-background"
MESH_PROFILE_RUNTIME_DIR = Path.home() / ".mesh" / "mlx-profiles"
MLX_VENV_BIN = Path.home() / ".mlx" / "venv" / "bin"
MLX_SERVER_BIN = MLX_VENV_BIN / "mlx_lm.server"

MLX_SERVER_URL = os.getenv("MLX_SERVER_URL", "http://127.0.0.1:8081")
WHISPER_STT_URL = os.getenv("WHISPER_STT_URL", "http://127.0.0.1:8082")
WHISPER_HEALTH = f"{WHISPER_STT_URL}/health"
MLX_MODELS_URL = f"{MLX_SERVER_URL}/v1/models"

CRON_JOBS_PATH = Path.home() / ".hermes" / "cron" / "jobs.json"
HERMES_ENV_PATH = Path.home() / ".hermes" / ".env"
HERMES_SESSIONS_PATH = Path.home() / ".hermes" / "sessions"

HTTP_TIMEOUT = 3.0
POLL_INTERVAL = 10  # seconds

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
TRENDING_CACHE_TTL = 6 * 3600  # 6 hours

MCP_PING = {"jsonrpc": "2.0", "id": 0, "method": "ping"}
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

NIGHTLY_BUILD_LOG = Path.home() / ".claude" / "nightly-build-log.md"
SESSIONS_DB = Path.home() / ".claude" / "atlas-sessions.db"
_SERVICE_HISTORY_MAX = 20

MESH_OPERATOR = os.getenv("MESH_OPERATOR", "Punch")

ATLAS_SYSTEM_PROMPT = """You are Atlas — the lead AI agent in a local AI mesh. You are accessed via the Mission Control Dashboard. Be direct, concise, technical.

Current mesh status:
{mesh_status}"""

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def _init_sessions_db():
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
    asyncio.create_task(_poll_loop())
    asyncio.create_task(_openviking_watchdog())
    asyncio.create_task(_generate_brief_on_startup())
    print(f"[startup] Mission Control backend on :8000 — polling every {POLL_INTERVAL}s, watchdog active")
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
# Shared state — updated by background tasks, read by endpoints/WS
# ---------------------------------------------------------------------------

_insights: list[dict] = []  # last 20 from mesh-subconscious
_brief_cache: dict[str, Any] = {"text": "", "generated_at": None}  # morning brief

_state: dict[str, Any] = {
    "services": {},
    "agents": [],
    "cron_jobs": [],
    "memories": [],
    "memory_summary": {},
    "memory_events": [],
    "llm_models": [],
    "llm_active": None,   # which LLM backend is serving: "mlx" | None
    "memory_monitor_log": [],  # last N lines from memory monitor log
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
}

_trending_cache_time: float = 0.0

_ws_clients: set[WebSocket] = set()
_ws_lock = asyncio.Lock()

_ROUTINE_KEYWORDS = {
    "summarize", "summary", "digest", "status", "report", "memory", "cron",
    "schedule", "scan", "search", "recall", "monitor", "health", "log",
}
_SPECIALIZED_KEYWORDS = {
    "browser", "web", "website", "page", "scrape", "click", "navigate",
    "file", "folder", "upload", "download",
}
_PREMIUM_KEYWORDS = {
    "plan", "planning", "architecture", "architect", "design", "ambiguous",
    "debug", "debugging", "investigate", "root cause", "refactor", "review",
    "final review", "hard", "complex", "high-stakes", "risky",
}
_CODE_KEYWORDS = {
    "code", "implement", "implementation", "patch", "fix", "bug", "test",
    "tests", "typescript", "python", "react", "fastapi", "refactor",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        hist[name] = (hist[name] + [entry])[-_SERVICE_HISTORY_MAX:]


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

    if any(token in lowered for token in _PREMIUM_KEYWORDS):
        return "premium", "Premium-only work matched planning/debugging/review signals"
    if any(token in lowered for token in _SPECIALIZED_KEYWORDS):
        return "specialized", "Specialized file/web work detected"
    if any(token in lowered for token in _CODE_KEYWORDS):
        return "routine", "Code-heavy local work detected"
    if any(token in lowered for token in _ROUTINE_KEYWORDS):
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
    premium_agent = available_premium[0].get("name") if available_premium else (premium_pool[0].get("name") if premium_pool else "atlas")
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

    if any(token in lowered for token in _CODE_KEYWORDS):
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
        active_platforms = sorted(
            name for name, pdata in platform_states.items()
            if isinstance(pdata, dict) and pdata.get("state") not in ("disconnected", "stopped")
        )
        if _pid_is_alive(pid) or gateway_state == "running":
            services["hermes_gateway"] = {
                "name": "Hermes Gateway",
                "url": HERMES_GATEWAY_URL,
                # Cron-only Hermes runs without an HTTP health endpoint.
                "status": "degraded",
                "error": str(exc),
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

    # AI Maestro (AMP routing hub) — no /health endpoint, use /api/agents
    try:
        r = await client.get(f"{AI_MAESTRO_URL}/api/agents", timeout=HTTP_TIMEOUT)
        body = r.json()
        agents = body.get("agents", [])
        services["aimaestro"] = {
            "name": "AI Maestro",
            "url": AI_MAESTRO_URL,
            "status": "up" if "agents" in body else "degraded",
            "agents": len(agents),
            "online": sum(1 for agent in agents if agent.get("status") == "online"),
        }
    except Exception as exc:
        services["aimaestro"] = {"name": "AI Maestro", "status": "down", "error": str(exc)}

    return services


# Core mesh agents — always shown, status detected from live processes/services
MESH_AGENTS = [
    {
        "id": "atlas",
        "name": "atlas",
        "label": "Atlas",
        "role": "Lead Role",
        "model": "Premium Lead Pool",
        "color": "#06b6d4",
        "tier": "premium",
        "routing_group": "premium-pool",
        "scarce": True,
        "default_for": [],
        "reserve_for": ["planning", "ambiguous debugging", "tricky refactors", "final review"],
        "fallback_to": "claude",
        "detect": None,  # always online — we are Atlas
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
                "model": "/Users/iris/.mlx/models/Qwen3.5-35B-A3B-4bit",
                "base_url": "http://192.168.1.186:8081/v1",
                "purpose": "default execution",
                "mode": "active",
            },
            {
                "name": "sidecar",
                "model": "/Users/iris/.mlx/models/Qwen2.5-7B-Instruct-4bit",
                "base_url": "http://192.168.1.186:8083/v1",
                "purpose": "summaries, routing, compression, auxiliary tasks",
                "mode": "active",
            },
            {
                "name": "code-specialist",
                "model": "/Users/iris/.mlx/models/Qwen2.5-Coder-32B-Instruct-4bit",
                "base_url": "http://127.0.0.1:8084/v1",
                "purpose": "code-heavy implementation, patching, and local review",
                "mode": "on-demand",
                "managed": True,
            },
            {
                "name": "reasoning-specialist",
                "model": "/Users/iris/.mlx/models/DeepSeek-R1-Distill-Qwen-32B-4bit",
                "base_url": "http://127.0.0.1:8085/v1",
                "purpose": "harder local reasoning, debugging analysis, and second-pass review",
                "mode": "on-demand",
                "managed": True,
            },
        ],
        "detect": "hermes",  # pgrep pattern
    },
    {
        "id": "iriseye",
        "name": "iriseye",
        "label": "iriseye",
        "role": "File/Web Agent",
        "model": "Claude Code",
        "color": "#10b981",
        "tier": "specialized",
        "routing_group": "specialized",
        "scarce": False,
        "default_for": ["file work", "web tasks"],
        "reserve_for": ["interactive file and browser tasks"],
        "fallback_to": "hermes",
        "detect": None,
    },
    {
        "id": "claude",
        "name": "claude",
        "label": "claude",
        "role": "Lead Role Backup",
        "model": "Claude Code",
        "color": "#f59e0b",
        "tier": "premium",
        "routing_group": "premium-pool",
        "scarce": True,
        "default_for": [],
        "reserve_for": ["planning", "ambiguous debugging", "tricky refactors", "final review"],
        "fallback_to": "atlas",
        "detect": None,
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


async def _fetch_maestro_registry(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    try:
        r = await client.get(f"{AI_MAESTRO_URL}/api/agents", timeout=HTTP_TIMEOUT)
        body = r.json()
        agents = body.get("agents", [])
        return {
            str(agent.get("name", "")).strip().lower(): agent
            for agent in agents
            if agent.get("name")
        }
    except Exception:
        return {}


async def _fetch_agents(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Build mesh agent list from runtime detection plus AI Maestro registration data."""
    maestro_agents = await _fetch_maestro_registry(client)
    defs_by_name = {agent["name"]: agent for agent in MESH_AGENTS}
    all_names = list(dict.fromkeys([*defs_by_name.keys(), *maestro_agents.keys()]))

    agents = []
    for key in all_names:
        defn = defs_by_name.get(key, {
            "id": key,
            "name": key,
            "label": key,
            "role": "Registered Agent",
            "model": None,
            "color": "#64748b",
            "detect": None,
        })
        maestro = maestro_agents.get(key)

        if key == "atlas":
            runtime_status = "online"
            task = "Atlas lead role — served by Codex or Claude Code"
        elif defn["detect"] and await _is_process_running(defn["detect"]):
            runtime_status = "online"
            task = None
        else:
            runtime_status = "offline"
            task = None

        orchestration_status = maestro.get("status", "unknown") if maestro else "unregistered"
        registration_status = "registered" if maestro else "local-only"
        address = None
        if maestro:
            addresses = (((maestro.get("tools") or {}).get("amp") or {}).get("addresses")) or []
            primary = next((item for item in addresses if item.get("primary")), addresses[0] if addresses else None)
            if primary:
                address = primary.get("address")

        agents.append({
            "id": defn["id"],
            "name": defn["name"],
            "label": defn["label"],
            "role": defn["role"],
            "model": (maestro or {}).get("model") or defn["model"],
            "color": defn["color"],
            "status": runtime_status,
            "runtime_status": runtime_status,
            "registration_status": registration_status,
            "orchestration_status": orchestration_status,
            "health_status": "unknown",
            "status_reason": None,
            "task": task or (maestro or {}).get("taskDescription"),
            "host": os.getenv("MESH_HOST", "localhost"),
            "address": address,
            "program": (maestro or {}).get("program"),
            "last_active": (maestro or {}).get("lastActive"),
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
    maestro_service = services.get("aimaestro", {})
    availability_overrides = _availability_overrides()

    for agent in agents:
        enriched = dict(agent)
        name = str(agent.get("name", "")).lower()
        runtime_status = agent.get("runtime_status", agent.get("status", "offline"))
        orchestration_status = agent.get("orchestration_status", "unknown")
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
        elif agent.get("registration_status") == "registered":
            health_status = "offline" if activity_status == "stale" else "degraded"
            freshness = f", last active {activity_status}" if activity_status != "unknown" else ""
            status_reason = f"Registered in AI Maestro ({orchestration_status}) but no local runtime detected{freshness}"
        else:
            health_status = "offline"
            status_reason = "No local runtime detected"

        if runtime_status == "online":
            presence_kind = "local-runtime"
            presence_status = "online"
            presence_reason = "Local runtime detected"
        elif agent.get("registration_status") == "registered":
            presence_kind = "external-registration"
            presence_status = "registered"
            presence_reason = "Registered in orchestration, but no local runtime detected"
        else:
            presence_kind = "local-runtime"
            presence_status = "offline"
            presence_reason = "No local runtime or external registration detected"

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
        enriched["orchestration_reachable"] = maestro_service.get("status") == "up"
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
    """Read recent AMP messages for atlas (inbox + sent)."""
    messages = []
    try:
        atlas_dir = AMP_AGENTS_DIR / "atlas" / "messages"
        for folder in ("inbox", "sent"):
            folder_path = atlas_dir / folder
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
    global _trending_cache_time

    if time.monotonic() - _trending_cache_time < TRENDING_CACHE_TTL:
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
        _trending_cache_time = time.monotonic()
        return repos
    except Exception as exc:
        print(f"[trending] fetch error: {exc}")
        return _state.get("trending_repos", [])  # keep stale data on error


# ---------------------------------------------------------------------------
# OpenViking watchdog
# ---------------------------------------------------------------------------

OPENVIKING_PLIST = Path.home() / "Library/LaunchAgents/local.openviking-server.plist"
OV_LOCK_PATH = Path.home() / ".openviking/data/vectordb/context/store/LOCK"
OV_PID_PATH  = Path.home() / ".openviking/data/.openviking.pid"
OV_WATCHDOG_INTERVAL = 30   # seconds between health checks
OV_RESTART_COOLDOWN  = 60   # seconds to wait after a restart before checking again

_ov_last_restart: float = 0.0


def _ov_restart_sync() -> str:
    """Blocking restart — runs in executor. Returns a log message."""
    import time
    global _ov_last_restart

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

    _ov_last_restart = time.monotonic()
    return "[watchdog] OpenViking restarted via launchctl"


async def _openviking_watchdog():
    """Polls OpenViking health every 30s and restarts if down."""
    import time
    await asyncio.sleep(15)  # give it time to come up on first boot

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Skip check if we just restarted — give it time to boot
                if time.monotonic() - _ov_last_restart < OV_RESTART_COOLDOWN:
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

    # Atlas: latest Claude session file mtime (sessions are .jsonl under projects/)
    atlas_ts = None
    try:
        from datetime import timezone as _tz
        projects_dir = Path.home() / ".claude" / "projects"
        files = sorted(projects_dir.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            atlas_ts = datetime.fromtimestamp(files[0].stat().st_mtime, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    result["atlas"] = atlas_ts

    # AI Maestro local runtime status files for registered agents
    try:
        registry = json.loads(AIMAESTRO_REGISTRY_PATH.read_text())
        latest_by_name: dict[str, str] = {}
        for agent in registry:
            name = str(agent.get("name", "")).strip().lower()
            agent_id = str(agent.get("id", "")).strip()
            if not name or not agent_id:
                continue
            status_path = AIMAESTRO_AGENTS_DIR / agent_id / "status.json"
            if not status_path.exists():
                continue
            try:
                payload = json.loads(status_path.read_text())
            except Exception:
                continue
            if payload.get("isRunning") is not True:
                continue
            last_updated_ms = payload.get("lastUpdated")
            if not isinstance(last_updated_ms, (int, float)):
                continue
            ts = datetime.fromtimestamp(last_updated_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            prev = latest_by_name.get(name)
            if not prev or ts > prev:
                latest_by_name[name] = ts
        result.update(latest_by_name)
    except Exception:
        pass

    return result


async def _poll_loop():
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
                _state["last_updated"] = _now_iso()

                await _broadcast_status()
            except Exception as exc:
                import traceback
                print(f"[poll] error: {exc}", flush=True)
                traceback.print_exc()

            await asyncio.sleep(POLL_INTERVAL)


async def _broadcast_insight(insight: dict):
    data = json.dumps({"type": "insight", "insight": insight})
    async with _ws_lock:
        dead: set[WebSocket] = set()
        for ws in _ws_clients:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        _ws_clients.difference_update(dead)


async def _broadcast_status():
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


# ---------------------------------------------------------------------------
# MLX chat helpers
# ---------------------------------------------------------------------------

PROJECTS_DIR = Path.home() / "Projects"
BRIEF_REFRESH_HOURS = 6  # regenerate brief if older than this


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
    global _brief_cache

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
                "You are Atlas, lead AI agent. Generate a concise morning brief for Punch "
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
    _brief_cache = {"text": text, "generated_at": now}
    return text


async def _generate_brief_on_startup():
    """Wait for first poll to complete, then generate brief."""
    # Wait until state is populated (up to 60s)
    for _ in range(12):
        await asyncio.sleep(5)
        if _state.get("last_updated"):
            break
    await _generate_brief()


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def api_health():
    return {
        "services": _state["services"],
        "last_updated": _state["last_updated"],
        "permission_audit_summary": _state["permission_audit_summary"],
    }


@app.get("/api/agents")
async def api_agents():
    return {"agents": _state["agents"]}


@app.get("/api/routing")
async def api_routing():
    return _state["routing_summary"]


@app.get("/api/cron")
async def api_cron():
    # Recompute next_run_in_seconds on every request so countdown stays fresh
    jobs = []
    for j in _state["cron_jobs"]:
        job = dict(j)
        job["next_run_in_seconds"] = _seconds_until(job.get("next_run_at"))
        jobs.append(job)
    return {"jobs": jobs}


@app.get("/api/memories")
async def api_memories():
    return {"memories": _state["memories"]}


@app.get("/api/memory-events")
async def api_memory_events():
    return {"events": _state["memory_events"]}


@app.get("/api/system")
async def api_system():
    metrics = await asyncio.get_event_loop().run_in_executor(None, _fetch_system_metrics)
    return metrics


@app.get("/api/memory-monitor-log")
async def api_memory_monitor_log(lines: int = 50):
    log = await asyncio.get_event_loop().run_in_executor(None, lambda: _fetch_memory_monitor_log(lines))
    return {"lines": log, "path": str(MEMORY_MONITOR_LOG)}


@app.get("/api/logs")
async def api_logs(n: int = 60):
    logs = await asyncio.get_event_loop().run_in_executor(None, lambda: _fetch_logs(n))
    return logs


@app.get("/api/amp")
async def api_amp():
    messages = await asyncio.get_event_loop().run_in_executor(None, _fetch_amp_messages)
    return {"messages": messages}


AI_MAESTRO_URL = os.getenv("AI_MAESTRO_URL", "http://localhost:23000")
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


async def _fetch_maestro_messages() -> list[dict[str, Any]]:
    """Fetch latest 20 messages for claude/atlas from AI Maestro API."""
    url = f"{AI_MAESTRO_URL}/api/agents/claude/messages"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return [{"error": str(exc)}]

    raw = data if isinstance(data, list) else data.get("messages", data.get("data", []))
    messages = []
    for item in raw[:20]:
        if not isinstance(item, dict):
            continue
        body = item.get("body", item.get("message", item.get("content", ""))) or ""
        body = _ANSI_RE.sub("", str(body))
        preview = body[:120]
        messages.append({
            "id": item.get("id", item.get("message_id", "")),
            "from": item.get("from", item.get("sender", item.get("from_agent", "?"))),
            "subject": item.get("subject", item.get("type", "")),
            "timestamp": item.get("timestamp", item.get("sent_at", item.get("created_at", ""))),
            "status": item.get("status", item.get("read", "unread") if isinstance(item.get("read"), str) else ("read" if item.get("read") else "unread")),
            "preview": preview,
        })
    return messages


@app.get("/api/amp/messages")
async def api_amp_messages():
    """Fetch latest 20 AMP messages for atlas/claude from AI Maestro."""
    messages = await _fetch_maestro_messages()
    return {"messages": messages}


@app.get("/api/agent-messages")
async def api_agent_messages(limit: int = 50, agent: str | None = None):
    messages = _read_agent_messages(limit=max(1, min(limit, 200)))
    if agent:
        needle = agent.strip().lower()
        messages = [
            message for message in messages
            if str(message.get("from", "")).lower() == needle or str(message.get("to", "")).lower() == needle
        ]
    return {"messages": messages}


@app.post("/api/agent-messages")
async def api_post_agent_message(payload: dict[str, Any] = Body(...)):
    record = _append_agent_message(_validate_agent_message(payload))
    await _broadcast_status()
    return {"ok": True, "message": record}


_AMP_ALLOWED_TYPES = {"notification", "request", "task", "response"}


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


class AmpSendRequest(BaseModel):
    recipient: str
    subject: str
    message: str
    type: str = "notification"

    @field_validator("recipient")
    @classmethod
    def _chk_recipient(cls, v: str) -> str:
        import re
        v = v.strip()
        if not v:
            raise ValueError("recipient required")
        if len(v) > 100:
            raise ValueError("recipient too long (max 100)")
        if not re.match(r"^[a-zA-Z0-9@._\-]+$", v):
            raise ValueError("recipient contains invalid characters")
        return v

    @field_validator("subject")
    @classmethod
    def _chk_subject(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("subject required")
        if len(v) > 200:
            raise ValueError("subject too long (max 200)")
        return v

    @field_validator("message")
    @classmethod
    def _chk_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message required")
        if len(v) > 4000:
            raise ValueError("message too long (max 4000)")
        return v

    @field_validator("type")
    @classmethod
    def _chk_type(cls, v: str) -> str:
        if v not in _AMP_ALLOWED_TYPES:
            raise ValueError(f"type must be one of: {', '.join(sorted(_AMP_ALLOWED_TYPES))}")
        return v


@app.post("/api/amp/send")
async def api_amp_send(req: AmpSendRequest):
    """Send an AMP message via amp-send CLI."""
    amp_bin = os.getenv("AMP_BIN", "/Users/iris/.local/bin/amp-send")
    env = {**os.environ, "PATH": f"/Users/iris/.local/bin:{os.environ.get('PATH', '')}"}
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [amp_bin, req.recipient, req.subject, req.message, "--type", req.type],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            ),
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"exit {result.returncode}"
            return {"ok": False, "error": err}
        return {"ok": True, "output": result.stdout.strip()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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


@app.get("/api/amp/events")
async def api_amp_events():
    events = await asyncio.get_event_loop().run_in_executor(None, _fetch_amp_events)
    return {"events": events}


@app.get("/api/hermes")
async def api_hermes():
    status = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    return status


@app.post("/api/hermes/background")
async def api_hermes_background(payload: dict = Body(...)):
    req = HermesBackgroundTaskRequest(**payload)
    hermes_agent = next((agent for agent in _state.get("agents", []) if agent.get("name") == "hermes"), None)
    profiles = (hermes_agent or {}).get("local_profiles") or []
    target = _find_hermes_profile(profiles, req.profile, f"profile:{req.profile}")
    resolved_profile = str((target or {}).get("hermes_profile") or req.profile or "default")
    try:
        task = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _launch_hermes_background_task(
                resolved_profile,
                req.prompt,
                req.title,
                use_worktree=req.use_worktree,
                repo_path=req.repo_path,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to launch Hermes background task: {exc}")

    _state["hermes_status"] = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    await _broadcast_status()
    return {"ok": True, "task": task}


@app.post("/api/hermes/background/{task_id}/stop")
async def api_hermes_background_stop(task_id: str):
    task = await asyncio.get_event_loop().run_in_executor(None, lambda: _stop_hermes_background_task(task_id))
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    _state["hermes_status"] = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    await _broadcast_status()
    return {"ok": True, "task": task}


@app.post("/api/hermes/background/{task_id}/cleanup")
async def api_hermes_background_cleanup(task_id: str):
    try:
        task = await asyncio.get_event_loop().run_in_executor(None, lambda: _cleanup_hermes_worktree(task_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    _state["hermes_status"] = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    await _broadcast_status()
    return {"ok": True, "task": task}


@app.get("/api/hermes/background/{task_id}")
async def api_hermes_background_poll(task_id: str):
    task = next((item for item in _fetch_hermes_background_tasks() if item.get("id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    return {"ok": True, "task": task}


@app.get("/api/hermes/background/{task_id}/log")
async def api_hermes_background_log(task_id: str, lines: int = 40):
    task = next((item for item in _fetch_hermes_background_tasks() if item.get("id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    capped = max(1, min(lines, 200))
    return {
        "ok": True,
        "task_id": task_id,
        "lines": capped,
        "log": _tail_text(task.get("log_path"), capped),
    }


@app.post("/api/hermes/quick-command")
async def api_hermes_quick_command(payload: dict = Body(...)):
    req = HermesQuickCommandRequest(**payload)
    hermes_agent = next((agent for agent in _state.get("agents", []) if agent.get("name") == "hermes"), None)
    profiles = (hermes_agent or {}).get("local_profiles") or []
    target = _find_hermes_profile(profiles, req.profile, f"profile:{req.profile}")
    resolved_profile = str((target or {}).get("hermes_profile") or req.profile or "default")
    profile_home = _hermes_profile_home(resolved_profile)
    quick_commands = _read_hermes_quick_commands(profile_home)
    command = next((item for item in quick_commands if item.get("name") == req.command_name), None)
    if not command:
        raise HTTPException(status_code=404, detail="quick command not found")
    if command.get("type") != "exec" or not command.get("command"):
        raise HTTPException(status_code=400, detail="only exec quick commands are supported")
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                command["command"],
                shell=True,
                cwd=str(profile_home),
                capture_output=True,
                text=True,
                timeout=20,
                env={**os.environ, "PATH": f"{LOCAL_BIN_DIR}:{os.environ.get('PATH', '')}"},
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"quick command failed: {exc}")
    return {
        "ok": result.returncode == 0,
        "profile": resolved_profile,
        "command_name": req.command_name,
        "status": "ok" if result.returncode == 0 else "error",
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
        "exit_code": result.returncode,
    }


@app.get("/api/trending")
async def api_trending():
    return {"repos": _state["trending_repos"], "cached": _trending_cache_time > 0}


class InsightPayload(BaseModel):
    timestamp: str
    severity: str
    summary: str
    insights: list = []
    actions: list = []


@app.post("/api/insights")
async def api_insights_post(payload: InsightPayload):
    global _insights
    record = payload.model_dump()
    _insights = ([record] + _insights)[:20]
    # Broadcast to all WS clients immediately
    await _broadcast_insight(record)
    return {"ok": True}


@app.get("/api/insights")
async def api_insights_get():
    return {"insights": _insights}


@app.get("/api/nightly/status")
async def api_nightly_status():
    if not NIGHTLY_BUILD_LOG.exists():
        return {"last_run": None, "rotation": None, "branch": None, "pr_url": None, "log_tail": None}
    text = NIGHTLY_BUILD_LOG.read_text(errors="replace")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    last = sections[-1].strip() if len(sections) > 1 else None
    last_run = rotation = branch = pr_url = log_tail = None
    if last:
        log_tail = last[:600]
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s*[-–]\s*(\w+)", last)
        if m:
            last_run, rotation = m.group(1), m.group(2)
        pr_m = re.search(r"- PR:\s*(https://\S+)", last)
        if pr_m:
            pr_url = pr_m.group(1)
    try:
        result = subprocess.run(
            ["git", "branch", "--list", "nightly/*"],
            cwd=str(Path.home() / "Projects" / "mission-control-dashboard"),
            capture_output=True, text=True, timeout=5,
        )
        branches = [b.strip().lstrip("* ") for b in result.stdout.strip().splitlines() if b.strip()]
        branch = branches[-1] if branches else None
    except Exception:
        pass
    return {"last_run": last_run, "rotation": rotation, "branch": branch, "pr_url": pr_url, "log_tail": log_tail}


class SessionLogRequest(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def _chk_role(cls, v: str) -> str:
        if v not in ("user", "assistant", "system", "note"):
            raise ValueError("role must be user/assistant/system/note")
        return v

    @field_validator("content")
    @classmethod
    def _chk_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content required")
        if len(v) > 10000:
            raise ValueError("content too long (max 10000)")
        return v


class RouteTaskRequest(BaseModel):
    task: str

    @field_validator("task")
    @classmethod
    def _chk_task(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("task required")
        if len(v) > 4000:
            raise ValueError("task too long (max 4000)")
        return v


class TaskSubmitRequest(BaseModel):
    task: str
    subject: str | None = None
    dispatch: bool = False

    @field_validator("task")
    @classmethod
    def _chk_submit_task(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("task required")
        if len(v) > 4000:
            raise ValueError("task too long (max 4000)")
        return v

    @field_validator("subject")
    @classmethod
    def _chk_subject_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 200:
            raise ValueError("subject too long (max 200)")
        return v


class AgentAvailabilityRequest(BaseModel):
    agent: str
    availability: str
    note: str | None = None

    @field_validator("agent")
    @classmethod
    def _chk_agent(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("agent required")
        return v

    @field_validator("availability")
    @classmethod
    def _chk_availability(cls, v: str) -> str:
        allowed = {"available", "rate_limited", "offline"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(f"availability must be one of: {', '.join(sorted(allowed))}")
        return v


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


class LocalProfileActionRequest(BaseModel):
    agent: str = "hermes"
    profile: str
    action: str

    @field_validator("agent")
    @classmethod
    def _chk_profile_agent(cls, v: str) -> str:
        v = v.strip().lower()
        if v != "hermes":
            raise ValueError("only hermes local profiles are currently supported")
        return v

    @field_validator("profile")
    @classmethod
    def _chk_profile_name(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("profile required")
        return v

    @field_validator("action")
    @classmethod
    def _chk_profile_action(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"start", "stop"}:
            raise ValueError("action must be start or stop")
        return v


class HermesBackgroundTaskRequest(BaseModel):
    profile: str = "default"
    prompt: str
    title: str | None = None
    use_worktree: bool = False
    repo_path: str | None = None

    @field_validator("profile")
    @classmethod
    def _chk_background_profile(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("profile required")
        return v

    @field_validator("prompt")
    @classmethod
    def _chk_background_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("prompt required")
        if len(v) > 4000:
            raise ValueError("prompt too long (max 4000)")
        return v

    @field_validator("title")
    @classmethod
    def _chk_background_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 120:
            raise ValueError("title too long (max 120)")
        return v

    @field_validator("repo_path")
    @classmethod
    def _chk_repo_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 500:
            raise ValueError("repo_path too long (max 500)")
        return v


class HermesQuickCommandRequest(BaseModel):
    profile: str = "default"
    command_name: str

    @field_validator("profile")
    @classmethod
    def _chk_quick_profile(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("profile required")
        return v

    @field_validator("command_name")
    @classmethod
    def _chk_quick_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("command_name required")
        if len(v) > 100:
            raise ValueError("command_name too long (max 100)")
        return v


@app.get("/api/sessions/today")
async def api_sessions_today():
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with sqlite3.connect(SESSIONS_DB) as conn:
            rows = conn.execute(
                "SELECT ts, role, content FROM session_log WHERE date = ? ORDER BY id ASC",
                (today,),
            ).fetchall()
        return {"date": today, "entries": [{"ts": r[0], "role": r[1], "content": r[2]} for r in rows]}
    except Exception as e:
        return {"date": today, "entries": [], "error": str(e)}


@app.post("/api/sessions/log")
async def api_sessions_log(req: SessionLogRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    ts = _now_iso()
    try:
        with sqlite3.connect(SESSIONS_DB) as conn:
            conn.execute(
                "INSERT INTO session_log (date, ts, role, content) VALUES (?, ?, ?, ?)",
                (today, ts, req.role, req.content),
            )
        return {"ok": True, "ts": ts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/routing/recommend")
async def api_routing_recommend(req: RouteTaskRequest):
    recommendation = _recommend_route(req.task, _state["agents"])
    return {
        **recommendation,
        "task": req.task,
        "policy": _state.get("routing_summary", {}).get("policy", "local-first"),
    }


@app.post("/api/tasks/submit")
async def api_tasks_submit(req: TaskSubmitRequest):
    recommendation = _recommend_route(req.task, _state["agents"])
    routing = _state.get("routing_summary", {})
    premium_available = set(routing.get("premium_available") or [])
    recommended_agent = recommendation["recommended_agent"]

    status = "routed"
    if recommendation["task_class"] == "premium" and recommended_agent not in premium_available:
        status = "deferred"

    subject = req.subject or req.task.splitlines()[0][:80]
    response: dict[str, Any] = {
        "status": status,
        "policy": routing.get("policy", "local-first"),
        "subject": subject,
        **recommendation,
    }

    if not req.dispatch or status == "deferred":
        if req.dispatch and status == "deferred":
            _audit_permission_decision(
                decision="deny",
                tool="amp-dispatch",
                agent=recommended_agent,
                reason="Dispatch deferred because no premium agent is currently available",
                input_summary=subject,
            )
        return response

    amp_bin = os.getenv("AMP_BIN", "/Users/iris/.local/bin/amp-send")
    env = {**os.environ, "PATH": f"/Users/iris/.local/bin:{os.environ.get('PATH', '')}"}
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [amp_bin, recommended_agent, subject, req.task, "--type", "task"],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            ),
        )
        if result.returncode != 0:
            _audit_permission_decision(
                decision="deny",
                tool="amp-dispatch",
                agent=recommended_agent,
                reason=result.stderr.strip() or f"AMP send failed with exit {result.returncode}",
                input_summary=subject,
            )
            response["status"] = "error"
            response["error"] = result.stderr.strip() or f"exit {result.returncode}"
            return response
        _audit_permission_decision(
            decision="allow",
            tool="amp-dispatch",
            agent=recommended_agent,
            reason="Task dispatch accepted by Mission Control",
            input_summary=subject,
        )
        response["dispatched"] = True
        response["output"] = result.stdout.strip()
        return response
    except Exception as exc:
        _audit_permission_decision(
            decision="deny",
            tool="amp-dispatch",
            agent=recommended_agent,
            reason=str(exc),
            input_summary=subject,
        )
        response["status"] = "error"
        response["error"] = str(exc)
        return response


@app.get("/api/availability")
async def api_availability():
    return {"overrides": _availability_overrides()}


@app.post("/api/availability")
async def api_availability_set(req: AgentAvailabilityRequest):
    path = AVAILABILITY_OVERRIDES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    overrides = _availability_overrides()
    overrides[req.agent] = {
        "availability": req.availability,
        "note": req.note,
        "updated_at": _now_iso(),
    }
    path.write_text(json.dumps(overrides, indent=2))
    _audit_permission_decision(
        decision="allow",
        tool="availability-override",
        agent=req.agent,
        reason=f"Availability override set to {req.availability}",
        input_summary=req.note,
    )
    return {"ok": True, "overrides": overrides}


@app.get("/api/permissions/audit")
async def api_permissions_audit(last: int = 50):
    bounded_last = max(1, min(last, 500))
    entries = _permission_audit_entries(limit=bounded_last)
    return {
        "entries": entries,
        "summary": _summarize_permission_audit(entries),
    }


@app.post("/api/permissions/audit")
async def api_permissions_audit_log(req: PermissionAuditRequest):
    entry = _append_permission_audit(req.model_dump())
    return {
        "ok": True,
        "entry": entry,
        "summary": _state["permission_audit_summary"],
    }


@app.post("/api/local-profiles/action")
async def api_local_profiles_action(req: LocalProfileActionRequest):
    hermes = next((agent for agent in _state["agents"] if agent.get("name") == req.agent), None)
    if not hermes:
        _audit_permission_decision(
            decision="deny",
            tool="local-profile-action",
            agent=req.agent,
            reason="Hermes agent not found in current mesh state",
            input_summary=f"{req.profile}:{req.action}",
        )
        raise HTTPException(status_code=404, detail="hermes agent not found")

    profile = next((item for item in (hermes.get("local_profiles") or []) if item.get("name") == req.profile), None)
    if not profile:
        _audit_permission_decision(
            decision="deny",
            tool="local-profile-action",
            agent=req.agent,
            reason=f"Profile not found: {req.profile}",
            input_summary=f"{req.profile}:{req.action}",
        )
        raise HTTPException(status_code=404, detail=f"profile not found: {req.profile}")

    profile_kind = str(profile.get("profile_kind") or "")
    if profile_kind == "hermes-native":
        hermes_profile = str(profile.get("hermes_profile") or "default").strip() or "default"
        profile_home = _hermes_profile_home(hermes_profile)
        if not profile_home.exists():
            cmd = f"hermes profile create {hermes_profile} --clone" if hermes_profile != "default" else "hermes setup"
            _audit_permission_decision(
                decision="deny",
                tool="local-profile-action",
                agent=req.agent,
                reason=f"Hermes profile {hermes_profile} does not exist locally",
                input_summary=f"{req.profile}:{req.action}",
            )
            raise HTTPException(status_code=400, detail=f"hermes profile missing: {hermes_profile}. Next step: {cmd}")
        if not HERMES_BIN.exists():
            _audit_permission_decision(
                decision="deny",
                tool="local-profile-action",
                agent=req.agent,
                reason="Hermes CLI is not available",
                input_summary=f"{req.profile}:{req.action}",
            )
            raise HTTPException(status_code=400, detail=f"hermes CLI not found at {HERMES_BIN}")

        cmd = [str(HERMES_BIN), "-p", hermes_profile, "gateway", req.action]
        proc = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "PATH": f"{LOCAL_BIN_DIR}:{os.environ.get('PATH', '')}"},
            ),
        )
        combined = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if proc.returncode != 0:
            _audit_permission_decision(
                decision="deny",
                tool="local-profile-action",
                agent=req.agent,
                reason=combined or f"gateway {req.action} failed for Hermes profile {hermes_profile}",
                input_summary=f"{req.profile}:{req.action}",
            )
            raise HTTPException(status_code=500, detail=combined or f"gateway {req.action} failed for Hermes profile {hermes_profile}")

        _audit_permission_decision(
            decision="allow",
            tool="local-profile-action",
            agent=req.agent,
            reason=f"Hermes profile {hermes_profile} gateway {req.action} succeeded",
            input_summary=f"{req.profile}:{req.action}",
        )
        return {
            "ok": True,
            "status": "started" if req.action == "start" else "stopped",
            "profile": req.profile,
            "profile_kind": "hermes-native",
            "hermes_profile": hermes_profile,
            "output": combined,
        }

    if req.action == "stop":
        pid_path = _profile_pid_path(req.agent, req.profile)
        pid = _read_pid(pid_path)
        if not pid:
            _audit_permission_decision(
                decision="allow",
                tool="local-profile-action",
                agent=req.agent,
                reason=f"Stop request accepted; profile {req.profile} was not running",
                input_summary=f"{req.profile}:stop",
            )
            return {"ok": True, "status": "not_running", "profile": req.profile}
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        pid_path.unlink(missing_ok=True)
        _audit_permission_decision(
            decision="allow",
            tool="local-profile-action",
            agent=req.agent,
            reason=f"Stopped local profile {req.profile}",
            input_summary=f"{req.profile}:stop",
        )
        return {"ok": True, "status": "stopped", "profile": req.profile}

    if profile.get("mode") != "on-demand":
        _audit_permission_decision(
            decision="allow",
            tool="local-profile-action",
            agent=req.agent,
            reason=f"Profile {req.profile} is already active and not on-demand",
            input_summary=f"{req.profile}:start",
        )
        return {"ok": True, "status": "already_active", "profile": req.profile}
    if not profile.get("installed"):
        _audit_permission_decision(
            decision="deny",
            tool="local-profile-action",
            agent=req.agent,
            reason=f"Model not installed locally for profile {req.profile}",
            input_summary=f"{req.profile}:start",
        )
        raise HTTPException(status_code=400, detail=f"model not installed locally: {profile.get('model_path')}")
    if not MLX_SERVER_BIN.exists():
        _audit_permission_decision(
            decision="deny",
            tool="local-profile-action",
            agent=req.agent,
            reason="mlx_lm.server binary is not available",
            input_summary=f"{req.profile}:start",
        )
        raise HTTPException(status_code=400, detail=f"mlx_lm.server not found at {MLX_SERVER_BIN}")
    if profile.get("running"):
        _audit_permission_decision(
            decision="allow",
            tool="local-profile-action",
            agent=req.agent,
            reason=f"Profile {req.profile} is already running",
            input_summary=f"{req.profile}:start",
        )
        return {"ok": True, "status": "already_running", "profile": req.profile, "base_url": profile.get("base_url")}

    port = profile.get("port")
    model_path = profile.get("model_path")
    if not port or not model_path:
        _audit_permission_decision(
            decision="deny",
            tool="local-profile-action",
            agent=req.agent,
            reason="Profile missing port or model path",
            input_summary=f"{req.profile}:start",
        )
        raise HTTPException(status_code=400, detail="profile missing port or model path")

    MESH_PROFILE_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    pid_path = _profile_pid_path(req.agent, req.profile)
    log_path = _profile_log_path(req.agent, req.profile)
    with open(log_path, "ab") as log_handle:
        proc = subprocess.Popen(
            [
                str(MLX_SERVER_BIN),
                "--model", str(model_path),
                "--host", "127.0.0.1",
                "--port", str(port),
                "--prompt-cache-bytes", str(536870912),
                "--max-tokens", str(1024),
                "--decode-concurrency", "1",
                "--prompt-concurrency", "1",
            ],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={
                **os.environ,
                "PATH": f"{MLX_VENV_BIN}:{os.environ.get('PATH', '')}",
                "VIRTUAL_ENV": str(MLX_VENV_BIN.parent),
            },
        )
    pid_path.write_text(str(proc.pid))
    _audit_permission_decision(
        decision="allow",
        tool="local-profile-action",
        agent=req.agent,
        reason=f"Started local profile {req.profile}",
        input_summary=f"{req.profile}:start",
    )
    return {
        "ok": True,
        "status": "started",
        "profile": req.profile,
        "pid": proc.pid,
        "base_url": profile.get("base_url"),
        "log_path": str(log_path),
    }


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


# ---------------------------------------------------------------------------
# Chat endpoint — shells out to `claude -p` (requires claude CLI in PATH)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


def _build_atlas_messages(req: "ChatRequest") -> list[dict]:
    """Build OpenAI-format messages for Atlas chat."""
    mesh_status = json.dumps(
        {
            "services": {k: v.get("status") for k, v in _state["services"].items()},
            "agents": [{"name": a["name"], "status": a["status"]} for a in _state["agents"]],
            "last_updated": _state["last_updated"],
        },
        indent=2,
    )
    system_content = ATLAS_SYSTEM_PROMPT.format(mesh_status=mesh_status)
    messages: list[dict] = [{"role": "system", "content": system_content}]
    for m in req.history[-10:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": req.message})
    return messages


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """Non-streaming chat via MLX only."""
    if _state.get("llm_active") != "mlx":
        return {"error": "MLX server unavailable — start it with `mlx-server`", "mlx_down": True}
    messages = _build_atlas_messages(req)
    text = await _mlx_chat_complete(messages)
    if text.startswith("[MLX unavailable"):
        return {"error": text, "mlx_down": True}
    return {"response": text}


@app.post("/api/chat/stream")
async def api_chat_stream(req: ChatRequest):
    """
    Streaming Atlas chat via MLX server (SSE).
    Falls back to non-streaming Claude CLI if MLX is down.

    SSE events:
      data: {"token": "..."}\n\n   — incremental token
      data: [DONE]\n\n             — stream complete
      data: {"error": "..."}\n\n   — error
    """
    if _state.get("llm_active") != "mlx":
        # MLX not up — run non-streaming and emit as single chunk
        async def _fallback_stream():
            result = await api_chat(req)
            text = result.get("response") or result.get("error", "No response")
            yield f"data: {json.dumps({'token': text})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_fallback_stream(), media_type="text/event-stream")

    messages = _build_atlas_messages(req)

    return StreamingResponse(
        _mlx_chat_stream(messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/brief")
async def api_brief(refresh: bool = False):
    """
    Return the morning brief. Pass ?refresh=true to force regeneration.
    The brief is auto-generated at startup and cached for BRIEF_REFRESH_HOURS.
    """
    text = await _generate_brief(force=refresh)
    return {
        "brief": text,
        "generated_at": _brief_cache["generated_at"].isoformat() if _brief_cache["generated_at"] else None,
    }


@app.post("/api/stt")
async def api_stt(file: UploadFile = File(...)):
    """
    Proxy audio to the local Whisper STT server at :8082.
    Accepts any audio format the browser sends (webm, wav, etc).
    Returns OpenAI-compatible {"text": "..."}.
    """
    audio_bytes = await file.read()
    filename = file.filename or "audio.webm"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{WHISPER_STT_URL}/v1/audio/transcriptions",
                files={"file": (filename, audio_bytes, file.content_type or "audio/webm")},
                data={"model": "whisper-1"},
            )
            if resp.status_code != 200:
                return {"error": f"Whisper STT error {resp.status_code}", "text": ""}
            return resp.json()
    except Exception as exc:
        return {"error": f"STT unavailable: {exc}", "text": ""}


# ---------------------------------------------------------------------------
# RAG — Document search via OpenViking
# ---------------------------------------------------------------------------

def _ov_headers() -> dict:
    h = {"X-OpenViking-Account": OPENVIKING_ACCOUNT, "X-OpenViking-User": OPENVIKING_USER}
    if OPENVIKING_KEY:
        h["Authorization"] = f"Bearer {OPENVIKING_KEY}"
    return h


class RAGSearchRequest(BaseModel):
    query: str
    limit: int = 8


class RAGIngestRequest(BaseModel):
    path: str | None = None


@app.post("/api/rag/search")
async def api_rag_search(req: RAGSearchRequest):
    """Semantic search across documents in OpenViking RAG inbox."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{OPENVIKING_URL}/api/v1/search/search",
                headers=_ov_headers(),
                json={"query": req.query, "limit": req.limit},
            )
            if resp.status_code != 200:
                return {"error": f"Search error {resp.status_code}", "results": []}
            data = resp.json()
            result = data.get("result", {})
            # Combine memories and resources, prefer resources for doc search
            items = result.get("resources", []) + result.get("memories", [])
            results = [
                {
                    "uri": r.get("uri", ""),
                    "score": round(r.get("score", 0), 4),
                    "abstract": r.get("abstract", ""),
                    "context_type": r.get("context_type", ""),
                }
                for r in items[:req.limit]
            ]
            return {"results": results}
    except Exception as exc:
        return {"error": str(exc), "results": []}


@app.post("/api/rag/ingest")
async def api_rag_ingest(req: RAGIngestRequest):
    """
    Scan inbox and upload any files not yet in OpenViking.
    Uses temp_upload → resources/parent flow which correctly indexes content.
    If req.path is set, ingest only that file; otherwise scan the whole inbox.
    """
    RAG_INBOX.mkdir(parents=True, exist_ok=True)

    if req.path:
        files_to_ingest = [Path(req.path)]
    else:
        files_to_ingest = [f for f in RAG_INBOX.iterdir() if f.is_file()]

    if not files_to_ingest:
        return {"ok": True, "ingested": 0, "message": "Inbox is empty"}

    ingested = 0
    errors = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for fpath in files_to_ingest:
            try:
                # Step 1: temp upload
                with open(fpath, "rb") as fh:
                    up = await client.post(
                        f"{OPENVIKING_URL}/api/v1/resources/temp_upload",
                        headers=_ov_headers(),
                        files={"file": (fpath.name, fh, "application/octet-stream")},
                    )
                if up.status_code != 200:
                    errors.append(f"{fpath.name}: upload failed {up.status_code}")
                    continue
                temp_path = up.json().get("result", {}).get("temp_path")
                if not temp_path:
                    errors.append(f"{fpath.name}: no temp_path")
                    continue

                # Step 2: register under rag-inbox parent
                add = await client.post(
                    f"{OPENVIKING_URL}/api/v1/resources",
                    headers=_ov_headers(),
                    json={
                        "temp_path": temp_path,
                        "parent": "viking://resources/rag-inbox",
                        "reason": f"RAG inbox: {fpath.name}",
                    },
                )
                if add.status_code == 200:
                    ingested += 1
                else:
                    errors.append(f"{fpath.name}: register failed {add.status_code}")
            except Exception as exc:
                errors.append(f"{fpath.name}: {exc}")

    return {"ok": True, "ingested": ingested, "errors": errors}


@app.get("/api/rag/status")
async def api_rag_status():
    """Returns count of files in inbox and whether OpenViking is reachable."""
    RAG_INBOX.mkdir(parents=True, exist_ok=True)
    files = list(RAG_INBOX.iterdir())
    inbox_count = len([f for f in files if f.is_file()])
    return {
        "inbox_path": str(RAG_INBOX),
        "inbox_count": inbox_count,
        "inbox_files": [f.name for f in files if f.is_file()][:20],
    }


_RAG_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50MB
_RAG_ALLOWED_EXT = {'.pdf', '.txt', '.md', '.docx', '.csv', '.json', '.rst'}


@app.post("/api/rag/upload")
async def api_rag_upload(file: UploadFile = File(...)):
    """Upload a file directly into the RAG inbox."""
    RAG_INBOX.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload").name
    if Path(safe_name).suffix.lower() not in _RAG_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"File type not allowed. Accepted: {', '.join(sorted(_RAG_ALLOWED_EXT))}")
    content = await file.read()
    if len(content) > _RAG_MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")
    dest = RAG_INBOX / safe_name
    dest.write_bytes(content)
    return {"filename": safe_name, "size": len(content)}


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

class TTSRequest(BaseModel):
    text: str
    voice: str = "en-US-AriaNeural"


@app.post("/api/tts")
async def api_tts(req: TTSRequest):
    """Convert text to speech using edge-tts and return mp3 audio."""
    import edge_tts

    text = req.text.strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="text is empty")

    communicate = edge_tts.Communicate(text, req.voice)

    async def audio_stream():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(audio_stream(), media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

_MAX_WS_CONNECTIONS = 50


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    async with _ws_lock:
        if len(_ws_clients) >= _MAX_WS_CONNECTIONS:
            await ws.close(code=1008, reason="Server at capacity")
            return
    await ws.accept()
    async with _ws_lock:
        _ws_clients.add(ws)

    # Send current state immediately on connect
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
        "insights": _insights,
        "agent_messages": _state["agent_messages"],
    }
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        pass

    try:
        while True:
            # Keep alive — client messages are ignored but connection is maintained
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        async with _ws_lock:
            _ws_clients.discard(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)

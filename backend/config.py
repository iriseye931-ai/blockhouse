"""
Shared configuration — all constants and environment-derived paths.
Import this module; do not import individual names (avoids stale references).
"""
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Remote services
# ---------------------------------------------------------------------------

OPENVIKING_URL     = os.getenv("OPENVIKING_URL", "http://127.0.0.1:1933")
OPENVIKING_HEALTH  = f"{OPENVIKING_URL}/health"
OPENVIKING_KEY     = os.getenv("OPENVIKING_KEY", "")
OPENVIKING_ACCOUNT = os.getenv("OPENVIKING_ACCOUNT", "teamirs")
OPENVIKING_USER    = os.getenv("OPENVIKING_USER", "iris")

MEMORY_MCP_URL    = os.getenv("MEMORY_MCP_URL", "http://127.0.0.1:2033/mcp")
HERMES_GATEWAY_URL = os.getenv("HERMES_GATEWAY_URL", "http://127.0.0.1:18789")
OLLAMA_URL        = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODELS_URL = f"{OLLAMA_URL}/v1/models"

MLX_SERVER_URL    = os.getenv("MLX_SERVER_URL", "http://127.0.0.1:8081")
MLX_AUX_URL       = os.getenv("MLX_AUX_URL", "http://127.0.0.1:8083")
WHISPER_STT_URL   = os.getenv("WHISPER_STT_URL", "http://127.0.0.1:8082")
WHISPER_HEALTH    = f"{WHISPER_STT_URL}/health"
MLX_MODELS_URL    = f"{MLX_SERVER_URL}/v1/models"
MLX_AUX_MODELS_URL = f"{MLX_AUX_URL}/v1/models"
SCREENPIPE_URL    = os.getenv("SCREENPIPE_URL", "http://127.0.0.1:3030")

GITHUB_SEARCH_URL  = "https://api.github.com/search/repositories"
TRENDING_CACHE_TTL = 6 * 3600  # 6 hours

# ---------------------------------------------------------------------------
# Filesystem paths
# ---------------------------------------------------------------------------

RAG_INBOX                  = Path.home() / "Documents" / "rag" / "inbox"
MEMORY_MONITOR_LOG         = Path.home() / ".mlx" / "logs" / "memory-monitor.log"
MLX_ERROR_LOG              = Path.home() / ".mlx" / "logs" / "mlx-server.error.log"
AMP_AGENTS_DIR             = Path.home() / ".agent-messaging" / "agents"
HERMES_SESSIONS_DIR        = Path.home() / ".hermes" / "sessions"
HERMES_GATEWAY_STATE_PATH  = Path.home() / ".hermes" / "gateway_state.json"
HERMES_GATEWAY_PID_PATH    = Path.home() / ".hermes" / "gateway.pid"
HERMES_HOME                = Path.home() / ".hermes"
HERMES_PROFILES_DIR        = HERMES_HOME / "profiles"
LOCAL_BIN_DIR              = Path.home() / ".local" / "bin"
HERMES_BIN                 = Path(shutil.which("hermes") or "/Users/iris/.local/bin/hermes")
SCREENPIPE_AGENTS_DIR      = Path.home() / ".screenpipe"
AVAILABILITY_OVERRIDES_PATH = Path.home() / ".mesh" / "availability_overrides.json"
PERMISSION_AUDIT_LOG_PATH  = Path.home() / ".mesh" / "permission_audit.jsonl"
AGENT_INBOX_PATH           = Path.home() / ".mesh" / "agent_inbox.jsonl"
HERMES_BACKGROUND_TASKS_PATH = Path.home() / ".mesh" / "hermes_background_tasks.json"
HERMES_BACKGROUND_LOG_DIR  = Path.home() / ".mesh" / "hermes-background"
MESH_PROFILE_RUNTIME_DIR   = Path.home() / ".mesh" / "mlx-profiles"
MLX_VENV_BIN               = Path.home() / ".mlx" / "venv" / "bin"
MLX_SERVER_BIN             = MLX_VENV_BIN / "mlx_lm.server"
CRON_JOBS_PATH             = Path.home() / ".hermes" / "cron" / "jobs.json"
HERMES_ENV_PATH            = Path.home() / ".hermes" / ".env"
HERMES_SESSIONS_PATH       = Path.home() / ".hermes" / "sessions"
NIGHTLY_BUILD_LOG          = Path.home() / ".claude" / "nightly-build-log.md"
SESSIONS_DB                = Path.home() / ".claude" / "atlas-sessions.db"
PROJECTS_DIR               = Path.home() / "Projects"

# OpenViking watchdog
OPENVIKING_PLIST      = Path.home() / "Library/LaunchAgents/local.openviking-server.plist"
OV_LOCK_PATH          = Path.home() / ".openviking/data/vectordb/context/store/LOCK"
OV_PID_PATH           = Path.home() / ".openviking/data/.openviking.pid"

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

HTTP_TIMEOUT          = 3.0
POLL_INTERVAL         = 10          # seconds between background polls
BRIEF_REFRESH_HOURS   = 6
OV_WATCHDOG_INTERVAL  = 30          # seconds between OpenViking health checks
OV_RESTART_COOLDOWN   = 60          # seconds to wait after a restart
_SERVICE_HISTORY_MAX  = 20
MAX_WS_CONNECTIONS    = 50
SERVICE_HISTORY_MAX   = 20

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

MCP_PING    = {"jsonrpc": "2.0", "id": 0, "method": "ping"}
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

CLAUDE_SYSTEM_PROMPT = """You are Claude — the lead AI agent in a local AI mesh. You are accessed via the Mission Control Dashboard. Be direct, concise, technical.

Current mesh status:
{mesh_status}"""

MESH_OPERATOR = os.getenv("MESH_OPERATOR", "Punch")

# RAG
RAG_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB
RAG_ALLOWED_EXT    = {".pdf", ".txt", ".md", ".docx", ".csv", ".json", ".rst"}

# AMP
AMP_ALLOWED_TYPES = {"notification", "request", "task", "response"}

# Routing keyword sets
ROUTINE_KEYWORDS = {
    "summarize", "summary", "digest", "status", "report", "memory", "cron",
    "schedule", "scan", "search", "recall", "monitor", "health", "log",
}
SPECIALIZED_KEYWORDS = {
    "browser", "web", "website", "page", "scrape", "click", "navigate",
    "file", "folder", "upload", "download",
}
PREMIUM_KEYWORDS = {
    "plan", "planning", "architecture", "architect", "design", "ambiguous",
    "debug", "debugging", "investigate", "root cause", "refactor", "review",
    "final review", "hard", "complex", "high-stakes", "risky",
}
CODE_KEYWORDS = {
    "code", "implement", "implementation", "patch", "fix", "bug", "test",
    "tests", "typescript", "python", "react", "fastapi", "refactor",
}

# Mesh ports for security posture check
MESH_PORTS = [
    ("openviking", 1933),
    ("memory_mcp", 2033),
    ("hermes", 18789),
    ("mlx_35b", 8081),
    ("mlx_9b", 8083),
    ("screenpipe", 3030),
]

"""
Crew router — real-time per-agent activity pipeline.

Three real data sources, no simulation:
  * Claude: Claude Code hooks POST to /api/crew/hook (SessionStart, PreToolUse, ...)
  * Hermes: tail of ~/.hermes/logs/agent.log (conversation loop + tool executor lines)
  * Speech: new AMP messages between agents become speech-bubble events

Crew state and a ring buffer of events are pushed to clients as
{"type": "crew_event", ...} WebSocket frames, separate from the 10s
status_update cadence, so the crew stage reacts within ~2s.
"""
import asyncio
import json
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from .. import state as _st
from ..state import _state, _now_iso
from ..config import AMP_AGENTS_DIR, HERMES_HOME

router = APIRouter()

HERMES_AGENT_LOG = HERMES_HOME / "logs" / "agent.log"

IDLE_AFTER_SECONDS = 120        # no events -> idle
HERMES_TAIL_INTERVAL = 2.0
AMP_WATCH_INTERVAL = 3.0
EVENTS_MAX = 300

# ---------------------------------------------------------------------------
# Crew state
# ---------------------------------------------------------------------------

def _blank_member(name: str, role: str, model: str) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "model": model,
        "status": "idle",           # idle | thinking | working | talking | waiting
        "activity": None,           # human-readable current action
        "tool": None,
        "task": None,               # session / task label
        "tokens_in": 0,
        "tokens_out": 0,
        "events_today": 0,
        "last_event_at": None,
    }


_crew: dict[str, dict[str, Any]] = {
    "claude": _blank_member("Claude", "Lead — Claude Code", "fable-5"),
    "hermes": _blank_member("Hermes", "Runner — MLX local", "qwen3.6-35b"),
}

_crew_events: deque = deque(maxlen=EVENTS_MAX)


async def _emit(agent: str, kind: str, text: str, *, status: str | None = None,
                tool: str | None = None, meta: dict | None = None) -> None:
    member = _crew.get(agent)
    now = _now_iso()
    if member is not None:
        if status:
            member["status"] = status
        member["activity"] = text
        member["tool"] = tool
        member["last_event_at"] = now
        member["events_today"] += 1
    event = {
        "id": uuid.uuid4().hex[:12],
        "ts": now,
        "agent": agent,
        "kind": kind,          # hook | tool | thought | speech | lifecycle
        "text": text,
        "tool": tool,
        "meta": meta or {},
    }
    _crew_events.append(event)
    await _broadcast_crew(event)


async def _broadcast_crew(event: dict | None = None) -> None:
    payload = json.dumps({
        "type": "crew_event",
        "timestamp": _now_iso(),
        "event": event,
        "crew": _crew,
    })
    async with _st._ws_lock:
        dead = set()
        for ws in _st._ws_clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        _st._ws_clients.difference_update(dead)


# ---------------------------------------------------------------------------
# Claude — Claude Code hook receiver
# ---------------------------------------------------------------------------

def _summarize_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return tool_input.get("description") or (tool_input.get("command") or "")[:80]
    if tool_name in ("Edit", "Write", "Read", "NotebookEdit"):
        path = tool_input.get("file_path") or ""
        return f"{tool_name} {Path(path).name}" if path else tool_name
    if tool_name in ("Grep", "Glob"):
        return f"{tool_name} {tool_input.get('pattern', '')}"[:80]
    if tool_name == "Task":
        return f"subagent: {tool_input.get('description', '')}"[:80]
    if tool_name in ("WebFetch", "WebSearch"):
        return f"{tool_name} {tool_input.get('url') or tool_input.get('query', '')}"[:80]
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            server = parts[1].replace("claude-in-", "").replace("-", " ")
            return f"{server}: {parts[2].replace('_', ' ')}"[:80]
    return tool_name


@router.post("/api/crew/hook")
async def crew_hook(payload: dict = Body(...)):
    """Receiver for Claude Code hook events (Claude activity)."""
    hook = payload.get("hook_event_name", "")
    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or ""
    project = Path(cwd).name if cwd else None
    if project:
        _crew["claude"]["task"] = project

    if hook == "SessionStart":
        await _emit("claude", "lifecycle", f"session started in {project or '~'}",
                    status="thinking")
    elif hook == "UserPromptSubmit":
        await _emit("claude", "thought", "reading Iris's prompt", status="thinking")
    elif hook == "PreToolUse":
        await _emit("claude", "tool", _summarize_tool(tool_name, tool_input),
                    status="working", tool=tool_name)
    elif hook == "PostToolUse":
        # keep working state; refresh timestamp only
        _crew["claude"]["last_event_at"] = _now_iso()
    elif hook == "Notification":
        await _emit("claude", "lifecycle",
                    payload.get("message") or "needs attention", status="waiting")
    elif hook in ("Stop", "SubagentStop", "SessionEnd"):
        await _emit("claude", "lifecycle", "finished turn", status="idle")
    else:
        _crew["claude"]["last_event_at"] = _now_iso()

    return {"ok": True}


@router.get("/api/crew")
async def get_crew():
    return {"crew": _crew, "events": list(_crew_events)}


@router.post("/api/crew/task")
async def crew_task(payload: dict = Body(...)):
    """CAPCOM /task — queue real work on Hermes's kanban via the hermes CLI."""
    import os
    import subprocess
    title = str(payload.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    if len(title) > 300:
        return {"ok": False, "error": "title too long (300 max)"}
    hermes_bin = os.getenv("HERMES_BIN_PATH", str(Path.home() / ".local" / "bin" / "hermes"))
    env = {**os.environ, "PATH": f"{Path.home() / '.local' / 'bin'}:{os.environ.get('PATH', '')}"}
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [hermes_bin, "kanban", "create", title,
                 "--created-by", "mission-control", "--json"],
                capture_output=True, text=True, timeout=20, env=env,
            ),
        )
        if result.returncode != 0:
            return {"ok": False, "error": (result.stderr or result.stdout).strip()[:300]}
        try:
            task = json.loads(result.stdout.strip())
        except Exception:
            task = {"raw": result.stdout.strip()[:200]}
        task_id = task.get("id") or task.get("task_id") or "?"
        await _emit("hermes", "lifecycle", f"task queued: {title[:80]} [{task_id}]",
                    meta={"task_id": str(task_id)})
        return {"ok": True, "task": task}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Hermes — agent.log tail
# ---------------------------------------------------------------------------

_LOG_LINE = re.compile(
    r"^\S+ \S+ \w+ \[(?P<session>[^\]]+)\] (?P<logger>[\w.]+): (?P<msg>.*)$"
)
_TOKENS = re.compile(r"in=(\d+) out=(\d+)")
_TOOL_DONE = re.compile(r"tool (\w+) completed")


def _clean_session(raw: str) -> str:
    # cron_mlx-model-watchdog_20260701_200355 -> mlx-model-watchdog
    return re.sub(r"_\d{8}_\d{6}$", "", raw).removeprefix("cron_").removeprefix("session_")


async def run_hermes_feed() -> None:
    """Tails Hermes agent.log and converts lines into crew events."""
    pos = HERMES_AGENT_LOG.stat().st_size if HERMES_AGENT_LOG.exists() else 0
    while True:
        try:
            if HERMES_AGENT_LOG.exists():
                size = HERMES_AGENT_LOG.stat().st_size
                if size < pos:          # rotated
                    pos = 0
                if size > pos:
                    with HERMES_AGENT_LOG.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        chunk = fh.read(256_000)
                        pos = fh.tell()
                    await _ingest_hermes_lines(chunk.splitlines())
        except Exception as exc:
            print(f"[crew] hermes feed error: {exc}", flush=True)
        await asyncio.sleep(HERMES_TAIL_INTERVAL)


async def _ingest_hermes_lines(lines: list[str]) -> None:
    last_thought: str | None = None
    last_tool: tuple[str, str] | None = None
    session = None
    for line in lines:
        m = _LOG_LINE.match(line)
        if not m:
            continue
        session = _clean_session(m.group("session"))
        logger, msg = m.group("logger"), m.group("msg")
        if logger.endswith("conversation_loop") and "API call" in msg:
            tk = _TOKENS.search(msg)
            if tk:
                _crew["hermes"]["tokens_in"] += int(tk.group(1))
                _crew["hermes"]["tokens_out"] += int(tk.group(2))
            last_thought = f"reasoning on {session}"
        elif logger.endswith("tool_executor"):
            td = _TOOL_DONE.search(msg)
            if td:
                last_tool = (td.group(1), f"{td.group(1)} on {session}")
    if session:
        _crew["hermes"]["task"] = session
    # emit at most one thought + one tool event per tail cycle to avoid spam
    if last_tool:
        await _emit("hermes", "tool", last_tool[1], status="working", tool=last_tool[0])
    elif last_thought:
        await _emit("hermes", "thought", last_thought, status="thinking")


# ---------------------------------------------------------------------------
# Speech — AMP message watcher
# ---------------------------------------------------------------------------

def _resolve_agent_dirs() -> list[Path]:
    """Agent dirs may be name-keyed or mapped to a UUID dir via .index.json."""
    dirs: list[Path] = []
    index: dict[str, str] = {}
    index_path = AMP_AGENTS_DIR / ".index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    for name in ("claude", "hermes"):
        for candidate in (AMP_AGENTS_DIR / name, AMP_AGENTS_DIR / index.get(name, "")):
            if candidate.name and candidate.is_dir() and candidate not in dirs:
                dirs.append(candidate)
    return dirs


def _amp_inbox_files() -> list[Path]:
    """Messages move inbox -> processed quickly; sent/ catches the outgoing side."""
    files: list[Path] = []
    for agent_dir in _resolve_agent_dirs():
        for sub in ("inbox", "processed", "sent"):
            box = agent_dir / "messages" / sub
            if box.exists():
                files.extend(p for p in box.rglob("*.json") if p.is_file())
    return files


async def run_amp_watch() -> None:
    """Emits a speech event whenever a new AMP message lands in claude/hermes boxes."""
    seen: set[str] = {p.name for p in _amp_inbox_files()}
    while True:
        try:
            for p in _amp_inbox_files():
                key = p.name   # message id — same file appears in sent/ and inbox/
                if key in seen:
                    continue
                seen.add(key)
                try:
                    msg = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                envelope = msg.get("envelope") or msg
                payload = msg.get("payload") or msg
                sender = str(envelope.get("from", "?")).split("@")[0]
                recipient = str(envelope.get("to", "?")).split("@")[0]
                subject = envelope.get("subject") or payload.get("type", "message")
                body = payload.get("message") or payload.get("body") or ""
                if sender in _crew:
                    _crew[sender]["status"] = "talking"
                    _crew[sender]["last_event_at"] = _now_iso()
                await _emit(sender if sender in _crew else recipient, "speech",
                            f"{subject}: {str(body)[:140]}",
                            meta={"from": sender, "to": recipient, "subject": subject})
        except Exception as exc:
            print(f"[crew] amp watch error: {exc}", flush=True)
        await asyncio.sleep(AMP_WATCH_INTERVAL)


# ---------------------------------------------------------------------------
# Idle decay
# ---------------------------------------------------------------------------

async def run_crew_idle_decay() -> None:
    while True:
        try:
            now = datetime.now(timezone.utc)
            changed = False
            for member in _crew.values():
                last = member.get("last_event_at")
                if member["status"] != "idle" and last:
                    age = (now - datetime.fromisoformat(last)).total_seconds()
                    if age > IDLE_AFTER_SECONDS:
                        member["status"] = "idle"
                        member["activity"] = None
                        member["tool"] = None
                        changed = True
            if changed:
                await _broadcast_crew(None)
        except Exception as exc:
            print(f"[crew] idle decay error: {exc}", flush=True)
        await asyncio.sleep(15)

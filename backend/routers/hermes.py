import asyncio
import os
import re
import subprocess
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, field_validator
from ..state import _state, broadcast_status
from ..helpers import (
    _fetch_hermes_status, _fetch_hermes_background_tasks,
    _launch_hermes_background_task, _stop_hermes_background_task,
    _cleanup_hermes_worktree, _tail_text, _hermes_profile_home,
    _find_hermes_profile, _read_hermes_quick_commands,
    _fetch_amp_messages, _fetch_amp_events, _read_agent_messages,
)
from ..config import LOCAL_BIN_DIR, AMP_ALLOWED_TYPES

router = APIRouter()

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


class AmpSendRequest(BaseModel):
    recipient: str
    subject: str
    message: str
    type: str = "notification"

    @field_validator("recipient")
    @classmethod
    def _chk_recipient(cls, v: str) -> str:
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
        if v not in AMP_ALLOWED_TYPES:
            raise ValueError(f"type must be one of: {', '.join(sorted(AMP_ALLOWED_TYPES))}")
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


@router.get("/api/amp")
async def api_amp():
    messages = await asyncio.get_event_loop().run_in_executor(None, _fetch_amp_messages)
    return {"messages": messages}


@router.get("/api/amp/messages")
async def api_amp_messages():
    messages = _read_agent_messages(limit=20)
    return {"messages": messages}


@router.post("/api/amp/send")
async def api_amp_send(req: AmpSendRequest):
    amp_bin = os.getenv("AMP_BIN", "/Users/iris/.local/bin/amp-send")
    env = {**os.environ, "PATH": f"/Users/iris/.local/bin:{os.environ.get('PATH', '')}"}
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [amp_bin, req.recipient, req.subject, req.message, "--type", req.type],
                capture_output=True, text=True, timeout=15, env=env,
            ),
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"exit {result.returncode}"
            return {"ok": False, "error": err}
        return {"ok": True, "output": result.stdout.strip()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/amp/events")
async def api_amp_events():
    events = await asyncio.get_event_loop().run_in_executor(None, _fetch_amp_events)
    return {"events": events}


@router.get("/api/hermes")
async def api_hermes():
    status = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    return status


@router.post("/api/hermes/background")
async def api_hermes_background(payload: dict = Body(...)):
    req = HermesBackgroundTaskRequest(**payload)
    hermes_agent = next((a for a in _state.get("agents", []) if a.get("name") == "hermes"), None)
    profiles = (hermes_agent or {}).get("local_profiles") or []
    target = _find_hermes_profile(profiles, req.profile, f"profile:{req.profile}")
    resolved_profile = str((target or {}).get("hermes_profile") or req.profile or "default")
    try:
        task = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _launch_hermes_background_task(
                resolved_profile, req.prompt, req.title,
                use_worktree=req.use_worktree, repo_path=req.repo_path,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to launch Hermes background task: {exc}")

    _state["hermes_status"] = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    await broadcast_status()
    return {"ok": True, "task": task}


@router.post("/api/hermes/background/{task_id}/stop")
async def api_hermes_background_stop(task_id: str):
    task = await asyncio.get_event_loop().run_in_executor(None, lambda: _stop_hermes_background_task(task_id))
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    _state["hermes_status"] = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    await broadcast_status()
    return {"ok": True, "task": task}


@router.post("/api/hermes/background/{task_id}/cleanup")
async def api_hermes_background_cleanup(task_id: str):
    try:
        task = await asyncio.get_event_loop().run_in_executor(None, lambda: _cleanup_hermes_worktree(task_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    _state["hermes_status"] = await asyncio.get_event_loop().run_in_executor(None, _fetch_hermes_status)
    await broadcast_status()
    return {"ok": True, "task": task}


@router.get("/api/hermes/background/{task_id}")
async def api_hermes_background_poll(task_id: str):
    task = next((t for t in _fetch_hermes_background_tasks() if t.get("id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    return {"ok": True, "task": task}


@router.get("/api/hermes/background/{task_id}/log")
async def api_hermes_background_log(task_id: str, lines: int = 40):
    task = next((t for t in _fetch_hermes_background_tasks() if t.get("id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="background task not found")
    capped = max(1, min(lines, 200))
    return {"ok": True, "task_id": task_id, "lines": capped, "log": _tail_text(task.get("log_path"), capped)}


@router.post("/api/hermes/quick-command")
async def api_hermes_quick_command(payload: dict = Body(...)):
    req = HermesQuickCommandRequest(**payload)
    hermes_agent = next((a for a in _state.get("agents", []) if a.get("name") == "hermes"), None)
    profiles = (hermes_agent or {}).get("local_profiles") or []
    target = _find_hermes_profile(profiles, req.profile, f"profile:{req.profile}")
    resolved_profile = str((target or {}).get("hermes_profile") or req.profile or "default")
    profile_home = _hermes_profile_home(resolved_profile)
    quick_commands = _read_hermes_quick_commands(profile_home)
    command = next((c for c in quick_commands if c.get("name") == req.command_name), None)
    if not command:
        raise HTTPException(status_code=404, detail="quick command not found")
    if command.get("type") != "exec" or not command.get("command"):
        raise HTTPException(status_code=400, detail="only exec quick commands are supported")
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                command["command"], shell=True, cwd=str(profile_home),
                capture_output=True, text=True, timeout=20,
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

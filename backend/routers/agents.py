import asyncio
import json
import os
import re
import signal
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, field_validator
from ..state import _state, broadcast_status
from ..helpers import (
    _read_agent_messages, _append_agent_message, _validate_agent_message,
    _availability_overrides, _audit_permission_decision, _now_iso,
    _hermes_profile_home, _pid_running, _read_pid, _profile_pid_path,
    _profile_log_path, _enrich_local_profile, _find_hermes_profile,
)
from ..config import (
    AVAILABILITY_OVERRIDES_PATH, HERMES_BIN, LOCAL_BIN_DIR,
    MLX_SERVER_BIN, MLX_VENV_BIN, MESH_PROFILE_RUNTIME_DIR,
)

router = APIRouter()


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


@router.get("/api/agents")
async def api_agents():
    return {"agents": _state["agents"]}


@router.get("/api/availability")
async def api_availability():
    return {"overrides": _availability_overrides()}


@router.post("/api/availability")
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
        decision="allow", tool="availability-override", agent=req.agent,
        reason=f"Availability override set to {req.availability}",
        input_summary=req.note,
    )
    return {"ok": True, "overrides": overrides}


@router.get("/api/agent-messages")
async def api_agent_messages(limit: int = 50, agent: str | None = None):
    messages = _read_agent_messages(limit=max(1, min(limit, 200)))
    if agent:
        needle = agent.strip().lower()
        messages = [
            m for m in messages
            if str(m.get("from", "")).lower() == needle or str(m.get("to", "")).lower() == needle
        ]
    return {"messages": messages}


@router.post("/api/agent-messages")
async def api_post_agent_message(payload: dict = Body(...)):
    record = _append_agent_message(_validate_agent_message(payload))
    await broadcast_status()
    return {"ok": True, "message": record}


@router.post("/api/local-profiles/action")
async def api_local_profiles_action(req: LocalProfileActionRequest):
    hermes = next((a for a in _state["agents"] if a.get("name") == req.agent), None)
    if not hermes:
        _audit_permission_decision(
            decision="deny", tool="local-profile-action", agent=req.agent,
            reason="Hermes agent not found in current mesh state",
            input_summary=f"{req.profile}:{req.action}",
        )
        raise HTTPException(status_code=404, detail="hermes agent not found")

    profile = next((p for p in (hermes.get("local_profiles") or []) if p.get("name") == req.profile), None)
    if not profile:
        _audit_permission_decision(
            decision="deny", tool="local-profile-action", agent=req.agent,
            reason=f"Profile not found: {req.profile}",
            input_summary=f"{req.profile}:{req.action}",
        )
        raise HTTPException(status_code=404, detail=f"profile not found: {req.profile}")

    profile_kind = str(profile.get("profile_kind") or "")
    if profile_kind == "hermes-native":
        import subprocess
        hermes_profile = str(profile.get("hermes_profile") or "default").strip() or "default"
        profile_home = _hermes_profile_home(hermes_profile)
        if not profile_home.exists():
            cmd = f"hermes profile create {hermes_profile} --clone" if hermes_profile != "default" else "hermes setup"
            _audit_permission_decision(
                decision="deny", tool="local-profile-action", agent=req.agent,
                reason=f"Hermes profile {hermes_profile} does not exist locally",
                input_summary=f"{req.profile}:{req.action}",
            )
            raise HTTPException(status_code=400, detail=f"hermes profile missing: {hermes_profile}. Next step: {cmd}")
        if not HERMES_BIN.exists():
            _audit_permission_decision(
                decision="deny", tool="local-profile-action", agent=req.agent,
                reason="Hermes CLI is not available",
                input_summary=f"{req.profile}:{req.action}",
            )
            raise HTTPException(status_code=400, detail=f"hermes CLI not found at {HERMES_BIN}")

        cmd = [str(HERMES_BIN), "-p", hermes_profile, "gateway", req.action]
        proc = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                env={**os.environ, "PATH": f"{LOCAL_BIN_DIR}:{os.environ.get('PATH', '')}"},
            ),
        )
        combined = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if proc.returncode != 0:
            _audit_permission_decision(
                decision="deny", tool="local-profile-action", agent=req.agent,
                reason=combined or f"gateway {req.action} failed for Hermes profile {hermes_profile}",
                input_summary=f"{req.profile}:{req.action}",
            )
            raise HTTPException(status_code=500, detail=combined or f"gateway {req.action} failed for Hermes profile {hermes_profile}")

        _audit_permission_decision(
            decision="allow", tool="local-profile-action", agent=req.agent,
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
                decision="allow", tool="local-profile-action", agent=req.agent,
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
            decision="allow", tool="local-profile-action", agent=req.agent,
            reason=f"Stopped local profile {req.profile}",
            input_summary=f"{req.profile}:stop",
        )
        return {"ok": True, "status": "stopped", "profile": req.profile}

    if profile.get("mode") != "on-demand":
        _audit_permission_decision(
            decision="allow", tool="local-profile-action", agent=req.agent,
            reason=f"Profile {req.profile} is already active and not on-demand",
            input_summary=f"{req.profile}:start",
        )
        return {"ok": True, "status": "already_active", "profile": req.profile}

    if not profile.get("installed"):
        _audit_permission_decision(
            decision="deny", tool="local-profile-action", agent=req.agent,
            reason=f"Model not installed locally for profile {req.profile}",
            input_summary=f"{req.profile}:start",
        )
        raise HTTPException(status_code=400, detail=f"model not installed locally: {profile.get('model_path')}")

    if not MLX_SERVER_BIN.exists():
        _audit_permission_decision(
            decision="deny", tool="local-profile-action", agent=req.agent,
            reason="mlx_lm.server binary is not available",
            input_summary=f"{req.profile}:start",
        )
        raise HTTPException(status_code=400, detail=f"mlx_lm.server not found at {MLX_SERVER_BIN}")

    if profile.get("running"):
        _audit_permission_decision(
            decision="allow", tool="local-profile-action", agent=req.agent,
            reason=f"Profile {req.profile} is already running",
            input_summary=f"{req.profile}:start",
        )
        return {"ok": True, "status": "already_running", "profile": req.profile, "base_url": profile.get("base_url")}

    port = profile.get("port")
    model_path = profile.get("model_path")
    if not port or not model_path:
        _audit_permission_decision(
            decision="deny", tool="local-profile-action", agent=req.agent,
            reason="Profile missing port or model path",
            input_summary=f"{req.profile}:start",
        )
        raise HTTPException(status_code=400, detail="profile missing port or model path")

    import subprocess
    MESH_PROFILE_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    pid_path = _profile_pid_path(req.agent, req.profile)
    log_path = _profile_log_path(req.agent, req.profile)
    with open(log_path, "ab") as log_handle:
        proc = subprocess.Popen(
            [
                str(MLX_SERVER_BIN), "--model", str(model_path),
                "--host", "127.0.0.1", "--port", str(port),
                "--prompt-cache-bytes", str(536870912),
                "--max-tokens", str(1024),
                "--decode-concurrency", "1",
                "--prompt-concurrency", "1",
            ],
            stdout=log_handle, stderr=subprocess.STDOUT, start_new_session=True,
            env={
                **os.environ,
                "PATH": f"{MLX_VENV_BIN}:{os.environ.get('PATH', '')}",
                "VIRTUAL_ENV": str(MLX_VENV_BIN.parent),
            },
        )
    pid_path.write_text(str(proc.pid))
    _audit_permission_decision(
        decision="allow", tool="local-profile-action", agent=req.agent,
        reason=f"Started local profile {req.profile}",
        input_summary=f"{req.profile}:start",
    )
    return {
        "ok": True, "status": "started", "profile": req.profile,
        "pid": proc.pid, "base_url": profile.get("base_url"), "log_path": str(log_path),
    }

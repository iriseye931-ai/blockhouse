import asyncio
import os
import subprocess
from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, field_validator
from ..state import _state
from ..helpers import _recommend_route, _classify_task, _build_routing_summary, _audit_permission_decision
from ..config import AMP_ALLOWED_TYPES

router = APIRouter()


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


@router.get("/api/routing")
async def api_routing():
    return _state["routing_summary"]


@router.post("/api/routing/recommend")
async def api_routing_recommend(req: RouteTaskRequest):
    recommendation = _recommend_route(req.task, _state["agents"])
    return {
        **recommendation,
        "task": req.task,
        "policy": _state.get("routing_summary", {}).get("policy", "local-first"),
    }


@router.post("/api/tasks/submit")
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
                capture_output=True, text=True, timeout=15, env=env,
            ),
        )
        if result.returncode != 0:
            _audit_permission_decision(
                decision="deny", tool="amp-dispatch", agent=recommended_agent,
                reason=result.stderr.strip() or f"AMP send failed with exit {result.returncode}",
                input_summary=subject,
            )
            response["status"] = "error"
            response["error"] = result.stderr.strip() or f"exit {result.returncode}"
            return response
        _audit_permission_decision(
            decision="allow", tool="amp-dispatch", agent=recommended_agent,
            reason="Task dispatch accepted by Mission Control", input_summary=subject,
        )
        response["dispatched"] = True
        response["output"] = result.stdout.strip()
        return response
    except Exception as exc:
        _audit_permission_decision(
            decision="deny", tool="amp-dispatch", agent=recommended_agent,
            reason=str(exc), input_summary=subject,
        )
        response["status"] = "error"
        response["error"] = str(exc)
        return response

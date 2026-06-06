from fastapi import APIRouter
from pydantic import BaseModel
from .. import state as _st
from ..state import _state, _insights
from ..state import broadcast_insight

router = APIRouter()


class InsightPayload(BaseModel):
    timestamp: str
    severity: str
    summary: str
    insights: list = []
    actions: list = []


@router.post("/api/insights")
async def api_insights_post(payload: InsightPayload):
    record = payload.model_dump()
    _st._insights[:] = ([record] + _st._insights)[:20]
    await broadcast_insight(record)
    return {"ok": True}


@router.get("/api/insights")
async def api_insights_get():
    return {"insights": _st._insights}


@router.get("/api/trending")
async def api_trending():
    return {"repos": _state["trending_repos"], "cached": _st._trending_cache_time > 0}

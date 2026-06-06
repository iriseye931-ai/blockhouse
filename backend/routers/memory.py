from fastapi import APIRouter
from ..state import _state

router = APIRouter()


@router.get("/api/memories")
async def api_memories():
    return {"memories": _state["memories"]}


@router.get("/api/memory-events")
async def api_memory_events():
    return {"events": _state["memory_events"]}

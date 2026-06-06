import sqlite3
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from ..state import _now_iso
from ..config import SESSIONS_DB

router = APIRouter()


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


@router.get("/api/sessions/today")
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


@router.post("/api/sessions/log")
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

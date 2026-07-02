import asyncio
import json
import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .. import state as _st
from ..state import _state, _brief_cache
from ..helpers import _build_claude_messages, _mlx_chat_stream, _mlx_chat_complete, _generate_brief
from ..config import WHISPER_STT_URL

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class TTSRequest(BaseModel):
    text: str
    voice: str = "en-US-AriaNeural"


@router.post("/api/chat")
async def api_chat(req: ChatRequest):
    if _state.get("llm_active") != "mlx":
        return {"error": "MLX server unavailable — start it with `mlx-server`", "mlx_down": True}
    messages = _build_claude_messages(req)
    text = await _mlx_chat_complete(messages)
    if text.startswith("[MLX unavailable"):
        return {"error": text, "mlx_down": True}
    return {"response": text}


@router.post("/api/chat/stream")
async def api_chat_stream(req: ChatRequest):
    if _state.get("llm_active") != "mlx":
        async def _fallback_stream():
            result = await api_chat(req)
            text = result.get("response") or result.get("error", "No response")
            yield f"data: {json.dumps({'token': text})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_fallback_stream(), media_type="text/event-stream")

    messages = _build_claude_messages(req)
    return StreamingResponse(
        _mlx_chat_stream(messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/brief")
async def api_brief(refresh: bool = False):
    text = await _generate_brief(force=refresh)
    return {
        "brief": text,
        "generated_at": _st._brief_cache["generated_at"].isoformat() if _st._brief_cache["generated_at"] else None,
    }


@router.post("/api/stt")
async def api_stt(file: UploadFile = File(...)):
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


@router.post("/api/tts")
async def api_tts(req: TTSRequest):
    import edge_tts
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")

    communicate = edge_tts.Communicate(text, req.voice)

    async def audio_stream():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(audio_stream(), media_type="audio/mpeg")

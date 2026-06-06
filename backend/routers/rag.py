import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File
from pathlib import Path
from pydantic import BaseModel
from ..config import OPENVIKING_URL, RAG_INBOX, RAG_MAX_FILE_BYTES, RAG_ALLOWED_EXT
from ..helpers import _ov_headers

router = APIRouter()


class RAGSearchRequest(BaseModel):
    query: str
    limit: int = 8


class RAGIngestRequest(BaseModel):
    path: str | None = None


@router.post("/api/rag/search")
async def api_rag_search(req: RAGSearchRequest):
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


@router.post("/api/rag/ingest")
async def api_rag_ingest(req: RAGIngestRequest):
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


@router.get("/api/rag/status")
async def api_rag_status():
    RAG_INBOX.mkdir(parents=True, exist_ok=True)
    files = list(RAG_INBOX.iterdir())
    inbox_count = len([f for f in files if f.is_file()])
    return {
        "inbox_path": str(RAG_INBOX),
        "inbox_count": inbox_count,
        "inbox_files": [f.name for f in files if f.is_file()][:20],
    }


@router.post("/api/rag/upload")
async def api_rag_upload(file: UploadFile = File(...)):
    RAG_INBOX.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload").name
    if Path(safe_name).suffix.lower() not in RAG_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"File type not allowed. Accepted: {', '.join(sorted(RAG_ALLOWED_EXT))}")
    content = await file.read()
    if len(content) > RAG_MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")
    dest = RAG_INBOX / safe_name
    dest.write_bytes(content)
    return {"filename": safe_name, "size": len(content)}

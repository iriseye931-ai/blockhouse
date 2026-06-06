import re
import subprocess
from pathlib import Path
from fastapi import APIRouter
from ..state import _state
from ..helpers import _seconds_until
from ..config import NIGHTLY_BUILD_LOG

router = APIRouter()


@router.get("/api/cron")
async def api_cron():
    jobs = []
    for j in _state["cron_jobs"]:
        job = dict(j)
        job["next_run_in_seconds"] = _seconds_until(job.get("next_run_at"))
        jobs.append(job)
    return {"jobs": jobs}


@router.get("/api/nightly/status")
async def api_nightly_status():
    if not NIGHTLY_BUILD_LOG.exists():
        return {"last_run": None, "rotation": None, "branch": None, "pr_url": None, "log_tail": None}
    text = NIGHTLY_BUILD_LOG.read_text(errors="replace")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    last = sections[-1].strip() if len(sections) > 1 else None
    last_run = rotation = branch = pr_url = log_tail = None
    if last:
        log_tail = last[:600]
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s*[-–]\s*(\w+)", last)
        if m:
            last_run, rotation = m.group(1), m.group(2)
        pr_m = re.search(r"- PR:\s*(https://\S+)", last)
        if pr_m:
            pr_url = pr_m.group(1)
    try:
        result = subprocess.run(
            ["git", "branch", "--list", "nightly/*"],
            cwd=str(Path.home() / "Projects" / "mission-control-dashboard"),
            capture_output=True, text=True, timeout=5,
        )
        branches = [b.strip().lstrip("* ") for b in result.stdout.strip().splitlines() if b.strip()]
        branch = branches[-1] if branches else None
    except Exception:
        pass
    return {"last_run": last_run, "rotation": rotation, "branch": branch, "pr_url": pr_url, "log_tail": log_tail}

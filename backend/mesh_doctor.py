"""
Local mesh doctor for Mission Control.

Runs a small set of operational checks against the live local mesh and prints a
compact diagnosis with actionable warnings.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:3000"
DEFAULT_AI_MAESTRO_URL = "http://127.0.0.1:23000"
CRON_PATH = Path.home() / ".hermes" / "cron" / "jobs.json"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _age_seconds(value: str | None) -> int | None:
    dt = _parse_iso(value)
    if not dt:
        return None
    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))


def _fmt_age(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.json()


def _ov_secret() -> str:
    import os
    key = os.getenv("OV_API_KEY")
    if key:
        return key
    try:
        for line in open(Path.home() / ".openviking" / "secrets.env"):
            if line.startswith("OV_API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _check_memory_write(client: httpx.Client) -> CheckResult:
    """End-to-end write-path probe: create a session on OpenViking and confirm
    it returns a real session id. This is exactly what memory_store does first,
    and where a stale/rotated API key silently fails (result: null) while
    /health and recall keep working."""
    try:
        r = client.post(
            "http://127.0.0.1:1933/api/v1/sessions",
            headers={
                "Authorization": f"Bearer {_ov_secret()}",
                "X-OpenViking-Account": "teamirs",
                "X-OpenViking-User": "iris",
                "Content-Type": "application/json",
            },
            json={"metadata": {"probe": "mesh_doctor"}},
            timeout=8.0,
        )
        body = r.json()
        sid = (body.get("result") or {}).get("session_id")
        if sid:
            return CheckResult("memory-write", "ok", "OpenViking write path healthy (session created)")
        return CheckResult(
            "memory-write", "fail",
            f"write path broken — session create returned no id "
            f"({body.get('error', {}).get('code', r.status_code)}). "
            f"Likely a stale key: rotate-ov-key.sh or restart-service.sh local.openviking-mcp",
        )
    except Exception as exc:
        return CheckResult("memory-write", "fail", f"OpenViking write path unreachable: {exc}")


def run_doctor(base_url: str, frontend_url: str, maestro_url: str) -> tuple[list[CheckResult], int]:
    results: list[CheckResult] = []
    exit_code = 0

    with httpx.Client(timeout=5.0) as client:
        try:
            status = _fetch_json(client, f"{base_url}/api/status")
            services = status.get("services", {})
            agents = status.get("agents", [])
            cron_jobs = status.get("cron_jobs", [])
            routing = status.get("routing_summary", {})
            if not routing or not routing.get("guidance"):
                try:
                    routing = _fetch_json(client, f"{base_url}/api/routing")
                except Exception:
                    routing = routing or {}
            results.append(CheckResult("backend", "ok", f"Mission Control responding at {base_url}"))
        except Exception as exc:
            return [CheckResult("backend", "fail", f"Mission Control unreachable: {exc}")], 2

        try:
            resp = client.get(frontend_url)
            resp.raise_for_status()
            results.append(CheckResult("frontend", "ok", f"Dashboard responding at {frontend_url}"))
        except Exception as exc:
            results.append(CheckResult("frontend", "warn", f"Dashboard not reachable: {exc}"))
            exit_code = max(exit_code, 1)

        hermes_service = services.get("hermes_gateway", {})
        hermes_mode = (hermes_service.get("detail") or {}).get("mode")
        if hermes_service.get("status") == "up":
            results.append(CheckResult("hermes", "ok", "Hermes gateway healthy"))
        elif hermes_mode == "cron-only":
            results.append(CheckResult("hermes", "warn", "Hermes running cron-only; HTTP gateway unavailable by design"))
            exit_code = max(exit_code, 1)
        else:
            results.append(CheckResult("hermes", "fail", f"Hermes unhealthy: {hermes_service.get('error', hermes_service.get('status', 'unknown'))}"))
            exit_code = max(exit_code, 2)

        premium_available = routing.get("premium_available", [])
        premium_total = routing.get("premium_total_count", 0)
        rate_limited_agents = [
            str(agent.get("name")) for agent in agents
            if agent.get("availability_status") == "rate_limited"
        ]
        if premium_available:
            results.append(CheckResult("premium-pool", "ok", f"Premium capacity available: {', '.join(premium_available)}"))
        else:
            results.append(CheckResult("premium-pool", "warn", f"No premium agent currently available (pool size {premium_total})"))
            exit_code = max(exit_code, 1)
        if rate_limited_agents:
            results.append(CheckResult("premium-state", "warn", f"Rate-limited agents: {', '.join(rate_limited_agents)}"))
            exit_code = max(exit_code, 1)

        stale_agents = [
            agent for agent in agents
            if agent.get("activity_status") == "stale" and agent.get("registration_status") == "registered"
        ]
        if stale_agents:
            names = ", ".join(str(agent.get("name")) for agent in stale_agents)
            results.append(CheckResult("heartbeats", "warn", f"Registered but stale agents: {names}"))
            exit_code = max(exit_code, 1)
        else:
            results.append(CheckResult("heartbeats", "ok", "No registered agents are stale"))

        overdue_jobs = [
            job for job in cron_jobs
            if job.get("enabled") is not False and (job.get("next_run_in_seconds") or 0) == 0
        ]
        if overdue_jobs:
            names = ", ".join(str(job.get("name")) for job in overdue_jobs[:4])
            results.append(CheckResult("cron", "warn", f"Overdue cron jobs detected: {names}"))
            exit_code = max(exit_code, 1)
        else:
            results.append(CheckResult("cron", "ok", f"{len(cron_jobs)} cron jobs scheduled"))

        if CRON_PATH.exists():
            try:
                cron_data = json.loads(CRON_PATH.read_text())
                updated_at = cron_data.get("updated_at")
                age = _age_seconds(updated_at)
                if age is not None and age > 3600:
                    results.append(CheckResult("cron-state", "warn", f"jobs.json stale ({_fmt_age(age)} old)"))
                    exit_code = max(exit_code, 1)
                else:
                    results.append(CheckResult("cron-state", "ok", f"jobs.json updated {_fmt_age(age)} ago"))
            except Exception as exc:
                results.append(CheckResult("cron-state", "warn", f"Could not parse jobs.json: {exc}"))
                exit_code = max(exit_code, 1)

        routine_target = (routing.get("guidance") or {}).get("routine")
        if routine_target == "hermes":
            results.append(CheckResult("routing", "ok", "Routine work routes to Hermes"))
        else:
            results.append(CheckResult("routing", "warn", f"Routine work is not routed to Hermes (got {routine_target})"))
            exit_code = max(exit_code, 1)

        mem = _check_memory_write(client)
        results.append(mem)
        if mem.status == "fail":
            exit_code = max(exit_code, 2)

    return results, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the local iriseye mesh health.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND_URL)
    parser.add_argument("--maestro-url", default=DEFAULT_AI_MAESTRO_URL)
    args = parser.parse_args()

    results, exit_code = run_doctor(args.base_url, args.frontend_url, args.maestro_url)
    for result in results:
        print(f"[{result.status.upper():4}] {result.name:12} {result.detail}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

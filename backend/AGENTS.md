# Backend Context

This directory contains the FastAPI backend for Mission Control.

## Responsibilities

- Poll local mesh services and normalize their health/state.
- Expose REST endpoints and WebSocket updates for the frontend.
- Surface routing, memory, cron, agent, and system state in a way operators can trust.
- Support direct agent-message and AMP-related workflows without pretending to be the source of truth for services it cannot verify.

## Conventions

- Prefer explicit degraded/down/stale states over collapsing everything to "up" or "offline".
- Keep endpoint behavior deterministic and operator-readable.
- Treat local execution features carefully; anything that shells out to an agent or CLI is a higher-risk surface than read-only health endpoints.
- Avoid permissive defaults unless they are clearly intentional and acceptable for local-only use.

## Important Files

- `main.py` is the primary backend entry point.
- `mesh_doctor.py` is the operational verification path.
- `run_mission_control.sh` is the preferred launcher.
- `tests/` should cover behavior regressions for health, routing, and API shape when practical.

## Editing Guidance

- If you change service discovery, also review every endpoint or UI surface that depends on that state.
- If you add or rename ports, update docs, doctor checks, and any scripts that reference them.
- Keep local-path and machine-specific assumptions centralized and visible.

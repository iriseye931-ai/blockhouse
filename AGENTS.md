# Project Context

`mission-control-dashboard` is the main live operator UI for the local AI mesh. It combines a React/Vite frontend with a FastAPI backend and is meant to present truthful runtime state for Hermes, Atlas, OpenViking, AI Maestro, MLX, routing, memory, and agent messaging.

## Architecture

- `frontend/` is the live dashboard UI on port `3000`.
- `backend/` is the FastAPI/WebSocket backend on port `8000`.
- The backend polls local services and normalizes state for the frontend.
- This repo is the current primary Mission Control surface; the `iriseye` repo only contains an older legacy dashboard snapshot.

## Product Expectations

- Operator trust matters more than visual flair.
- The dashboard should not imply a service is healthy if the backend cannot verify it.
- Partial-state handling is important: degraded, stale, registered-only, or disconnected states should be shown honestly.
- Routing, memory, and agent presence should be understandable at a glance.

## Conventions

- Preserve the established mesh-first visual language unless asked to redesign it.
- Keep backend and frontend contracts in sync.
- Prefer explicit service names, ports, and health semantics over vague labels.
- Avoid fake demo data leaking into live operator surfaces unless it is clearly marked as simulated.

## Important Notes

- Root quick-start claims should stay aligned with what actually exists in `backend/` and `frontend/`.
- `mesh_doctor.py` and `run_mission_control.sh` are operationally important artifacts in this repo.
- A frontend that loads while the backend is down is not enough; operator confidence depends on end-to-end truth.

## Editing Guidance

- Verify user-visible operational claims before changing copy or status logic.
- Prefer fixes that improve compositional clarity, runtime truthfulness, and resilience under partial failure.
- When changing API payloads or health models, inspect both backend and frontend consumers.
- If delegating work in this repo, split backend and frontend tasks cleanly and provide exact files, endpoints, and expected UI/API outcomes.

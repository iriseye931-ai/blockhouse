# Changelog

All notable changes to this project will be documented here.

## v0.3.0 - 2026-07-01

### Crew stage (replaces the mesh sphere)
- Pixel-art Atlas and Hermes characters with state animations: idle, thinking, working (typing at consoles with live screen code), talking, waiting
- Speech bubbles rendered from real AMP messages between agents, with a data beam between consoles
- Per-agent status plates (status, model, task, activity, token counters) and a live ops log

### Real-time event pipeline
- `POST /api/crew/hook` receives Claude Code hook events (SessionStart, UserPromptSubmit, PreToolUse, Notification, Stop)
- Hermes activity from a live tail of `~/.hermes/logs/agent.log` (sessions, tools, token counts)
- AMP inbox/processed/sent watcher resolves agent dirs through `.index.json` and emits speech events
- `crew_event` WebSocket frames push updates to the stage within ~2s; `agent_simulator.py` removed — everything on screen is real

### Mesh + health
- Mesh registry trimmed to Atlas + Hermes (test agents and orphaned identities archived; `claude` symlinked to `atlas`)
- Hermes gateway health judged from runtime state; stale platform records (>48h) no longer mark the gateway degraded
- Agent list cleaned of retired iriseye/claude entries

### Fixes
- Backend test suite repaired after the v0.2.0 package split (62 passing)
- `_finalize_agents` distinguishes mesh-registered agents from plain offline


## v0.2.0 - 2026-06-05

### Architecture

- Split `backend/main.py` (4,291 lines) into `config.py`, `state.py`, `helpers.py`, `background.py`, and 11 focused FastAPI routers under `backend/routers/`. `main.py` reduced to 199 lines.
- Extracted `MeshPanel.tsx` into `panel/Primitives.tsx`, `panel/LogsTab.tsx`, `panel/HermesTab.tsx`, and a thin 38-line `MeshPanel.tsx` wrapper.
- Extracted `MeshGraph.tsx` constants and utilities into `mesh/constants.ts` and `mesh/utils.ts`.
- Deleted dead code: `LiveLogFeed.tsx` (deprecated stub), `agentStore.ts` (deprecated re-export).

### New Features

- **History ring buffer** — backend maintains a 24h in-memory snapshot ring (1/min, 1440 entries max). New `GET /api/history?t=<iso>` endpoint returns nearest snapshot.
- **Timeline scrubber** — ops strip now includes a slider to replay historical mesh state. Defaults to live; dragging left enters replay mode with a timestamp indicator and a ← Live button to return.
- **OS notifications** — dashboard requests `Notification` permission once on load. Service health transitions to `down` or `degraded` fire a browser notification, debounced 60s per service.

## v0.1.0-alpha - 2026-04-04

First public alpha of the rebuilt mesh-first dashboard.

- replaced the older panel-heavy layout with a cinematic mesh-first operator surface
- added a permanent left agent dock for Lead, Hermes, and IrisEye
- added a top ops strip, alert line, and compact operator utility block
- made operator summaries clickable so they focus matching agents and services
- upgraded memory modeling with summary, events, cause ranking, and routing impact
- encoded memory and gateway health directly into mesh node and link visuals
- refreshed the public README with live screenshots captured from the running dashboard
- tightened repo metadata to match the current product direction

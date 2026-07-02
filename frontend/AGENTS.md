# Frontend Context

This directory contains the React/Vite Mission Control frontend.

## Responsibilities

- Present the mesh as an operator surface, not a marketing site.
- Make routing, memory state, service health, and agent presence legible at a glance.
- Preserve visual hierarchy around the crew stage, status plates, and top-level status surfaces.
- Handle degraded or missing backend data honestly.

## Conventions

- The sphere is a central product surface, but it must not crowd out operator readability.
- Prefer concise labels and operational language over descriptive dashboard copy.
- Avoid UI elements that look live but are disconnected from real backend state.
- Maintain consistency in status color semantics and label casing.

## Stack

- React 19
- Vite
- TypeScript
- Tailwind CSS

## Editing Guidance

- Preserve the existing visual language unless a redesign is explicitly requested.
- When changing data usage, check the backend contract instead of assuming fields exist.
- Treat accessibility and readability as first-order concerns: contrast, text size, overlap, and partial-state messaging matter.
- If a panel is simulated, loading, or stale, communicate that clearly in the UI.

#!/bin/zsh
set -euo pipefail

BACKEND_DIR="/Users/iris/Projects/mission-control-dashboard/backend"
PROJECT_DIR="/Users/iris/Projects/mission-control-dashboard"
VENV_UVICORN="$BACKEND_DIR/venv/bin/uvicorn"

cd "$PROJECT_DIR"
exec "$VENV_UVICORN" backend.main:app --host 0.0.0.0 --port 8000

#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec python3 agent_inbox.py watch --agent codex "$@"

#!/usr/bin/env python3
"""
Tiny CLI for the Mission Control agent inbox.

This tool defaults to direct file access so two terminals can coordinate
without depending on the backend process.

Examples:
  ./agent_inbox.py read --agent codex
  ./agent_inbox.py watch --agent claude
  ./agent_inbox.py send --from-agent claude --to-agent codex --summary "Finished sphere pass"
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DEFAULT_INBOX_PATH = Path.home() / ".mesh" / "agent_inbox.jsonl"
DEFAULT_CLAIMS_PATH = Path.home() / ".mesh" / "agent_claims.json"


def _format_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M:%S")
    except Exception:
        return value


def _read_messages(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    messages: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                messages.append(record)
    return messages


def _read_claims(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


@contextmanager
def _claims_lock(path: Path) -> Iterator[None]:
    # Serializes read-modify-write of the claims file across agent processes.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write_claims(path: Path, claims: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so concurrent readers never see a half-written file.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(claims, indent=2), encoding="utf-8")
    tmp.replace(path)


def _write_message(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": payload.get("id") or f"msg-{datetime.now(timezone.utc).timestamp():.6f}",
        "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "from": payload["from"],
        "to": payload["to"],
        "role": payload.get("role", "handoff"),
        "task": payload.get("task", ""),
        "summary": payload["summary"],
        "details": payload.get("details", ""),
        "files": payload.get("files", []),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


def _filter_messages(messages: list[dict[str, Any]], agent: str | None, limit: int) -> list[dict[str, Any]]:
    if agent:
        needle = agent.strip().lower()
        messages = [
            message for message in messages
            if str(message.get("from", "")).lower() == needle or str(message.get("to", "")).lower() == needle
        ]
    return messages[-limit:]


def _print_message(message: dict[str, Any]) -> None:
    header = f"[{_format_timestamp(str(message.get('timestamp', '')))}] {message.get('from', '?')} -> {message.get('to', '?')}"
    print(header)
    print(f"summary: {message.get('summary', '')}")
    task = str(message.get("task", "")).strip()
    if task:
        print(f"task: {task}")
    details = str(message.get("details", "")).strip()
    if details:
        print(details)
    files = message.get("files") or []
    if files:
        print("files:", ", ".join(str(item) for item in files))
    print()


def _print_claim(claim: dict[str, Any]) -> None:
    print(f"[{_format_timestamp(str(claim.get('timestamp', '')))}] {claim.get('agent', '?')} claims {claim.get('scope', '')}")
    summary = str(claim.get("summary", "")).strip()
    if summary:
        print(f"summary: {summary}")
    files = claim.get("files") or []
    if files:
        print("files:", ", ".join(str(item) for item in files))
    print()


def cmd_read(args: argparse.Namespace) -> None:
    messages = _filter_messages(_read_messages(args.inbox_path), args.agent, args.limit)
    for message in messages:
        _print_message(message)


def cmd_latest(args: argparse.Namespace) -> None:
    messages = _filter_messages(_read_messages(args.inbox_path), args.agent, max(1, args.limit))
    if messages:
        _print_message(messages[-1])


def cmd_status(args: argparse.Namespace) -> None:
    messages = _read_messages(args.inbox_path)
    claims = _read_claims(args.claims_path)
    latest_by_agent: dict[str, dict[str, Any]] = {}
    for message in messages:
        sender = str(message.get("from", "")).strip()
        if sender:
            latest_by_agent[sender] = message

    print("Latest agent handoffs")
    print()
    for agent in args.agents:
        message = latest_by_agent.get(agent)
        if message:
            print(f"{agent}: {message.get('summary', '')}")
        else:
            print(f"{agent}: waiting")
    print()
    print("Open claims")
    print()
    open_claims = [claim for claim in claims if not claim.get("released")]
    if not open_claims:
        print("none")
        print()
        return
    for claim in open_claims:
        _print_claim(claim)


def cmd_send(args: argparse.Namespace) -> None:
    files = [item.strip() for item in (args.files or "").split(",") if item.strip()]
    record = _write_message(args.inbox_path, {
        "from": args.from_agent,
        "to": args.to_agent,
        "role": args.role,
        "task": args.task,
        "summary": args.summary,
        "details": args.details,
        "files": files,
    })
    _print_message(record)


def cmd_watch(args: argparse.Namespace) -> None:
    print(f"watching {args.inbox_path}")
    for message in _filter_messages(_read_messages(args.inbox_path), args.agent, args.limit):
        _print_message(message)
    # Watch output is typically redirected to a log/pipe — without flushing,
    # messages sit in the block buffer and are lost if the process is killed.
    sys.stdout.flush()
    position = args.inbox_path.stat().st_size if args.inbox_path.exists() else 0
    buffer = ""
    while True:
        time.sleep(args.interval)
        if not args.inbox_path.exists():
            position = 0
            buffer = ""
            continue
        size = args.inbox_path.stat().st_size
        if size < position:
            # File was truncated or replaced — start over from the top.
            position = 0
            buffer = ""
        if size == position:
            continue
        with args.inbox_path.open("r", encoding="utf-8") as handle:
            handle.seek(position)
            buffer += handle.read()
            position = handle.tell()
        lines = buffer.split("\n")
        buffer = lines.pop()
        new_messages: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                new_messages.append(record)
        for message in _filter_messages(new_messages, args.agent, max(len(new_messages), 1)):
            _print_message(message)
        sys.stdout.flush()


def cmd_claim(args: argparse.Namespace) -> None:
    files = [item.strip() for item in (args.files or "").split(",") if item.strip()]
    claim = {
        "id": f"claim-{datetime.now(timezone.utc).timestamp():.6f}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": args.agent,
        "scope": args.scope,
        "summary": args.summary,
        "files": files,
        "released": False,
    }
    with _claims_lock(args.claims_path):
        claims = _read_claims(args.claims_path)
        claims.append(claim)
        _write_claims(args.claims_path, claims)
    _print_claim(claim)


def cmd_claims(args: argparse.Namespace) -> None:
    claims = _read_claims(args.claims_path)
    if args.agent:
        claims = [claim for claim in claims if str(claim.get("agent", "")).lower() == args.agent.lower()]
    if not args.all:
        claims = [claim for claim in claims if not claim.get("released")]
    claims = claims[-args.limit:]
    for claim in claims:
        _print_claim(claim)


def cmd_release(args: argparse.Namespace) -> None:
    with _claims_lock(args.claims_path):
        claims = _read_claims(args.claims_path)
        updated = False
        for claim in claims:
            matches_agent = str(claim.get("agent", "")).lower() == args.agent.lower()
            matches_scope = args.scope and str(claim.get("scope", "")) == args.scope
            if matches_agent and (matches_scope or not args.scope) and not claim.get("released"):
                claim["released"] = True
                claim["released_at"] = datetime.now(timezone.utc).isoformat()
                updated = True
        if updated:
            _write_claims(args.claims_path, claims)
    if not updated:
        print("no matching open claims")
    else:
        print("claims released")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI for Mission Control agent inbox")
    parser.add_argument("--inbox-path", type=Path, default=DEFAULT_INBOX_PATH, help="shared inbox file path")
    parser.add_argument("--claims-path", type=Path, default=DEFAULT_CLAIMS_PATH, help="shared claims file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser("read", help="read recent agent messages")
    read_parser.add_argument("--agent", help="filter messages by agent name")
    read_parser.add_argument("--limit", type=int, default=20)
    read_parser.set_defaults(func=cmd_read)

    latest_parser = subparsers.add_parser("latest", help="show newest matching message")
    latest_parser.add_argument("--agent", help="filter messages by agent name")
    latest_parser.add_argument("--limit", type=int, default=1)
    latest_parser.set_defaults(func=cmd_latest)

    watch_parser = subparsers.add_parser("watch", help="poll and print new agent messages")
    watch_parser.add_argument("--agent", help="filter messages by agent name")
    watch_parser.add_argument("--limit", type=int, default=20)
    watch_parser.add_argument("--interval", type=float, default=2.0)
    watch_parser.set_defaults(func=cmd_watch)

    status_parser = subparsers.add_parser("status", help="show latest handoff per agent and current claims")
    status_parser.add_argument("--agents", nargs="+", default=["codex", "claude"])
    status_parser.set_defaults(func=cmd_status)

    send_parser = subparsers.add_parser("send", help="send an agent handoff")
    send_parser.add_argument("--from-agent", required=True)
    send_parser.add_argument("--to-agent", required=True)
    send_parser.add_argument("--summary", required=True)
    send_parser.add_argument("--details", default="")
    send_parser.add_argument("--task", default="dashboard realism")
    send_parser.add_argument("--role", default="handoff")
    send_parser.add_argument("--files", default="", help="comma-separated file list")
    send_parser.set_defaults(func=cmd_send)

    claim_parser = subparsers.add_parser("claim", help="claim ownership of a scope or file set")
    claim_parser.add_argument("--agent", required=True)
    claim_parser.add_argument("--scope", required=True, help="high-level ownership scope")
    claim_parser.add_argument("--summary", required=True)
    claim_parser.add_argument("--files", default="", help="comma-separated file list")
    claim_parser.set_defaults(func=cmd_claim)

    claims_parser = subparsers.add_parser("claims", help="list current claims")
    claims_parser.add_argument("--agent", help="filter claims by agent")
    claims_parser.add_argument("--limit", type=int, default=20)
    claims_parser.add_argument("--all", action="store_true", help="include released claims")
    claims_parser.set_defaults(func=cmd_claims)

    release_parser = subparsers.add_parser("release", help="release claims for an agent")
    release_parser.add_argument("--agent", required=True)
    release_parser.add_argument("--scope", help="release only a specific scope")
    release_parser.set_defaults(func=cmd_release)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

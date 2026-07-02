"""
Tests for input validation: AMP send, RAG upload, and core API endpoints.
"""
import io
import sys
import os
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# Add repo root to path so the `backend` package resolves
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.main import app
from backend.routers.hermes import AmpSendRequest, HermesBackgroundTaskRequest
from backend.routers.permissions import PermissionAuditRequest
from backend.routers.routing import RouteTaskRequest, TaskSubmitRequest
from backend.config import (
    RAG_MAX_FILE_BYTES as _RAG_MAX_FILE_BYTES,
    RAG_ALLOWED_EXT as _RAG_ALLOWED_EXT,
)
from backend.helpers import (
    _build_hermes_background_command,
    _cleanup_hermes_worktree,
    _finalize_agents,
    _fetch_hermes_checkpoint_overview,
    _fetch_hermes_memory_overview,
    _fetch_hermes_provider_overview,
    _fetch_hermes_profile_session_overview,
    _fetch_hermes_sessions_overview,
    _fetch_hermes_skill_overview,
    _fetch_hermes_toolset_overview,
    _refresh_background_task_state,
    _read_hermes_quick_commands,
    _recommend_route,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# AmpSendRequest validator tests
# ---------------------------------------------------------------------------

class TestAmpSendRequest:
    def _valid(self, **overrides):
        defaults = {"recipient": "hermes", "subject": "hello", "message": "test body", "type": "notification"}
        return {**defaults, **overrides}

    def test_valid_passes(self):
        req = AmpSendRequest(**self._valid())
        assert req.recipient == "hermes"

    def test_recipient_strips_whitespace(self):
        req = AmpSendRequest(**self._valid(recipient="  hermes  "))
        assert req.recipient == "hermes"

    def test_recipient_empty_fails(self):
        with pytest.raises(ValidationError, match="recipient required"):
            AmpSendRequest(**self._valid(recipient="   "))

    def test_recipient_too_long_fails(self):
        with pytest.raises(ValidationError, match="too long"):
            AmpSendRequest(**self._valid(recipient="a" * 101))

    def test_recipient_invalid_chars_fails(self):
        with pytest.raises(ValidationError, match="invalid characters"):
            AmpSendRequest(**self._valid(recipient="bad;injection"))

    def test_recipient_at_sign_allowed(self):
        req = AmpSendRequest(**self._valid(recipient="iris@teamirs.local"))
        assert req.recipient == "iris@teamirs.local"

    def test_subject_too_long_fails(self):
        with pytest.raises(ValidationError, match="too long"):
            AmpSendRequest(**self._valid(subject="x" * 201))

    def test_message_empty_fails(self):
        with pytest.raises(ValidationError, match="message required"):
            AmpSendRequest(**self._valid(message="   "))

    def test_message_too_long_fails(self):
        with pytest.raises(ValidationError, match="too long"):
            AmpSendRequest(**self._valid(message="x" * 4001))

    def test_invalid_type_fails(self):
        with pytest.raises(ValidationError, match="type must be one of"):
            AmpSendRequest(**self._valid(type="shell_exec"))

    def test_all_valid_types(self):
        for t in ("notification", "request", "task", "response"):
            req = AmpSendRequest(**self._valid(type=t))
            assert req.type == t


# ---------------------------------------------------------------------------
# RAG upload endpoint — extension and size gating
# ---------------------------------------------------------------------------

class TestRagUpload:
    def _upload(self, filename: str, content: bytes = b"data"):
        return client.post(
            "/api/rag/upload",
            files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        )

    def test_allowed_txt(self):
        # Should not return 400 (may fail for other reasons on CI, but not ext/size)
        r = self._upload("notes.txt", b"hello world")
        assert r.status_code != 400

    def test_disallowed_exe_returns_400(self):
        r = self._upload("evil.exe", b"MZ\x90\x00")
        assert r.status_code == 400
        assert "not allowed" in r.json()["detail"].lower()

    def test_disallowed_sh_returns_400(self):
        r = self._upload("script.sh", b"#!/bin/bash")
        assert r.status_code == 400

    def test_disallowed_js_returns_400(self):
        r = self._upload("payload.js", b"console.log(1)")
        assert r.status_code == 400

    def test_oversized_file_returns_413(self):
        big = b"x" * (_RAG_MAX_FILE_BYTES + 1)
        r = self._upload("huge.txt", big)
        assert r.status_code == 413

    def test_allowed_extensions_set(self):
        assert ".pdf" in _RAG_ALLOWED_EXT
        assert ".txt" in _RAG_ALLOWED_EXT
        assert ".exe" not in _RAG_ALLOWED_EXT
        assert ".sh" not in _RAG_ALLOWED_EXT


# ---------------------------------------------------------------------------
# Core API smoke tests
# ---------------------------------------------------------------------------

class TestCoreEndpoints:
    def test_health_returns_200(self):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_agents_returns_list(self):
        r = client.get("/api/agents")
        assert r.status_code == 200
        data = r.json()
        assert "agents" in data
        assert isinstance(data["agents"], list)

    def test_status_returns_200(self):
        r = client.get("/api/status")
        assert r.status_code == 200

    def test_amp_bad_type_returns_422(self):
        r = client.post("/api/amp/send", json={
            "recipient": "hermes",
            "subject": "test",
            "message": "body",
            "type": "DROP TABLE users;",
        })
        assert r.status_code == 422

    def test_amp_missing_recipient_returns_422(self):
        r = client.post("/api/amp/send", json={
            "subject": "test",
            "message": "body",
        })
        assert r.status_code == 422

    def test_routing_summary_returns_200(self):
        r = client.get("/api/routing")
        assert r.status_code == 200

    def test_permission_audit_returns_200(self):
        r = client.get("/api/permissions/audit")
        assert r.status_code == 200
        data = r.json()
        assert "entries" in data
        assert "summary" in data

    def test_routing_recommend_premium_task(self):
        r = client.post("/api/routing/recommend", json={
            "task": "Review this tricky refactor and decide the architecture before final merge"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["task_class"] == "premium"

    def test_routing_recommend_routine_task(self):
        r = client.post("/api/routing/recommend", json={
            "task": "Summarize the last 10 AMP messages and generate a short status report"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["task_class"] == "routine"


class TestRoutingValidation:
    def test_route_task_request_rejects_empty(self):
        with pytest.raises(ValidationError, match="task required"):
            RouteTaskRequest(task="   ")

    def test_task_submit_request_rejects_empty(self):
        with pytest.raises(ValidationError, match="task required"):
            TaskSubmitRequest(task="   ")

    def test_recommend_route_prefers_hermes_for_routine(self):
        rec = _recommend_route(
            "Summarize the latest mesh status",
            [
                {"name": "hermes", "routing_group": "local-default"},
                {"name": "claude", "routing_group": "premium-pool", "runtime_status": "online"},
            ],
        )
        assert rec["recommended_agent"] == "hermes"

    def test_recommend_route_prefers_premium_for_hard_tasks(self):
        rec = _recommend_route(
            "Plan the architecture and review this refactor",
            [
                {"name": "hermes", "routing_group": "local-default"},
                {"name": "claude", "routing_group": "premium-pool", "runtime_status": "online", "activity_status": "live"},
            ],
        )
        assert rec["recommended_agent"] == "claude"

    def test_recommend_route_prefers_sidecar_for_summary_work(self):
        rec = _recommend_route(
            "Summarize the current cron failures and routing status",
            [
                {
                    "name": "hermes",
                    "routing_group": "local-default",
                    "local_profiles": [
                        {"name": "profile:default", "display_name": "default", "hermes_profile": "default", "installed": True},
                        {"name": "profile:mesh-sidecar", "display_name": "mesh-sidecar", "hermes_profile": "mesh-sidecar", "installed": True},
                    ],
                },
            ],
        )
        assert rec["recommended_agent"] == "hermes"
        assert rec["recommended_profile"] == "profile:mesh-sidecar"
        assert rec["recommended_profile_display"] == "mesh-sidecar"

    def test_recommend_route_falls_back_when_code_specialist_missing(self):
        rec = _recommend_route(
            "Implement a React bug fix and patch the TypeScript tests",
            [
                {
                    "name": "hermes",
                    "routing_group": "local-default",
                    "local_profiles": [
                        {"name": "profile:default", "display_name": "default", "hermes_profile": "default", "installed": True},
                        {"name": "code-specialist", "installed": False},
                    ],
                },
            ],
        )
        assert rec["recommended_agent"] == "hermes"
        assert rec["recommended_profile"] == "profile:default"
        assert rec["recommended_profile_display"] == "default"

    def test_routing_summary_exposes_hermes_profile_guidance(self):
        import backend.helpers as main_mod

        summary = main_mod._build_routing_summary(
            [
                {
                    "name": "hermes",
                    "routing_group": "local-default",
                    "local_profiles": [
                        {"name": "profile:default", "display_name": "default", "hermes_profile": "default"},
                        {"name": "profile:mesh-sidecar", "display_name": "mesh-sidecar", "hermes_profile": "mesh-sidecar"},
                        {"name": "profile:mesh-reasoning", "display_name": "mesh-reasoning", "hermes_profile": "mesh-reasoning"},
                    ],
                },
                {"name": "claude", "routing_group": "premium-pool", "availability_status": "available"},
            ],
            {},
            {"status": "up", "primary_cause": {"kind": "healthy"}},
        )
        assert summary["profile_guidance"]["routine"] == "default"
        assert summary["profile_guidance"]["summary"] == "mesh-sidecar"
        assert summary["profile_guidance"]["reasoning"] == "mesh-reasoning"


class TestTaskSubmitEndpoint:
    def test_submit_task_routes_without_dispatch(self):
        r = client.post("/api/tasks/submit", json={
            "task": "Summarize the last 10 AMP messages and generate a short status report",
            "dispatch": False,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "routed"
        assert data["recommended_agent"] == "hermes"
        assert data["recommended_profile"] in {"workhorse", "sidecar"}

    def test_submit_task_premium_can_defer_when_unavailable(self, monkeypatch):
        import backend.helpers as main_mod
        monkeypatch.setitem(main_mod._state, "routing_summary", {
            "policy": "local-first",
            "premium_available": [],
        })
        monkeypatch.setitem(main_mod._state, "agents", [
            {"name": "claude", "routing_group": "premium-pool"},
            {"name": "claude", "routing_group": "premium-pool"},
            {"name": "hermes", "routing_group": "local-default"},
        ])
        r = client.post("/api/tasks/submit", json={
            "task": "Review this tricky refactor and decide the architecture before final merge",
            "dispatch": False,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "deferred"


class TestHermesSessions:
    def test_profile_session_overview_reads_sqlite_store(self, tmp_path):
        profile_home = tmp_path / "default"
        profile_home.mkdir()
        db_path = profile_home / "state.db"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    message_count INTEGER DEFAULT 0,
                    title TEXT,
                    model TEXT
                );
                CREATE VIRTUAL TABLE messages_fts USING fts5(content);
                """
            )
            conn.execute(
                "INSERT INTO sessions (id, source, started_at, ended_at, message_count, title, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("sess-1", "cli", 1000.0, 1010.0, 12, "mesh reasoning review", "qwen"),
            )

        overview = _fetch_hermes_profile_session_overview(profile_home, "default")
        assert overview["session_count"] == 1
        assert overview["search_ready"] is True
        assert overview["latest_title"] == "mesh reasoning review"
        assert overview["resume_target"] == "mesh reasoning review"

    def test_profile_session_overview_falls_back_to_session_files(self, tmp_path):
        profile_home = tmp_path / "mesh-sidecar"
        sessions_dir = profile_home / "sessions"
        sessions_dir.mkdir(parents=True)
        session_file = sessions_dir / "session_20260404_sidecar.json"
        session_file.write_text(json.dumps({
            "session_id": "20260404_sidecar",
            "title": "sidecar digest",
            "platform": "cli",
            "model": "qwen2.5",
            "session_start": "2026-04-04T05:00:00+00:00",
            "last_updated": "2026-04-04T05:05:00+00:00",
        }))

        overview = _fetch_hermes_profile_session_overview(profile_home, "mesh-sidecar")
        assert overview["session_count"] == 1
        assert overview["search_ready"] is False
        assert overview["latest_title"] == "sidecar digest"
        assert overview["resume_target"] == "sidecar digest"

    def test_sessions_overview_aggregates_profiles(self, tmp_path, monkeypatch):
        import backend.helpers as main_mod

        hermes_home = tmp_path / ".hermes"
        profiles_dir = hermes_home / "profiles"
        default_home = hermes_home
        sidecar_home = profiles_dir / "mesh-sidecar"
        sidecar_sessions = sidecar_home / "sessions"
        profiles_dir.mkdir(parents=True)
        sidecar_sessions.mkdir(parents=True)

        default_db = default_home / "state.db"
        with sqlite3.connect(default_db) as conn:
            conn.executescript(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    message_count INTEGER DEFAULT 0,
                    title TEXT,
                    model TEXT
                );
                CREATE VIRTUAL TABLE messages_fts USING fts5(content);
                """
            )
            conn.execute(
                "INSERT INTO sessions (id, source, started_at, ended_at, message_count, title, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("sess-1", "cli", 1000.0, 1020.0, 18, "default run", "qwen"),
            )
        (sidecar_sessions / "session_1.json").write_text(json.dumps({
            "session_id": "s1",
            "title": "sidecar digest",
            "platform": "cli",
            "last_updated": "2026-04-04T05:05:00+00:00",
        }))

        monkeypatch.setattr(main_mod, "HERMES_HOME", hermes_home)
        monkeypatch.setattr(main_mod, "HERMES_PROFILES_DIR", profiles_dir)

        overview = _fetch_hermes_sessions_overview()
        assert overview["session_count"] == 2
        assert overview["profile_count"] == 2
        assert overview["active_profiles"] == 2
        assert overview["search_ready"] is True

    def test_checkpoint_overview_reads_profile_settings(self, tmp_path, monkeypatch):
        import backend.helpers as main_mod

        hermes_home = tmp_path / ".hermes"
        profile_home = hermes_home / "profiles" / "mesh-sidecar"
        checkpoint_root = hermes_home / "checkpoints"
        profile_home.mkdir(parents=True)
        checkpoint_root.mkdir(parents=True)
        (profile_home / "config.yaml").write_text(
            "checkpoints:\n"
            "  enabled: true\n"
            "  max_snapshots: 25\n"
        )
        shadow_repo = checkpoint_root / "abcdef1234567890"
        shadow_repo.mkdir()

        monkeypatch.setattr(main_mod, "HERMES_HOME", hermes_home)

        overview = _fetch_hermes_checkpoint_overview(profile_home, "mesh-sidecar")
        assert overview["enabled"] is True
        assert overview["max_snapshots"] == 25
        assert overview["snapshot_count"] == 1
        assert overview["rollback_ready"] is True
        assert "/rollback diff" in overview["rollback_diff_hint"]

    def test_checkpoint_overview_handles_disabled_checkpoints(self, tmp_path, monkeypatch):
        import backend.helpers as main_mod

        hermes_home = tmp_path / ".hermes"
        profile_home = hermes_home
        profile_home.mkdir(parents=True)
        (profile_home / "config.yaml").write_text(
            "checkpoints:\n"
            "  enabled: false\n"
        )

        monkeypatch.setattr(main_mod, "HERMES_HOME", hermes_home)

        overview = _fetch_hermes_checkpoint_overview(profile_home, "default")
        assert overview["enabled"] is False
        assert overview["snapshot_count"] == 0
        assert overview["rollback_ready"] is False

    def test_provider_overview_reads_routing_and_fallbacks(self, tmp_path):
        profile_home = tmp_path / "mesh-sidecar"
        profile_home.mkdir(parents=True)
        (profile_home / "config.yaml").write_text(
            "model:\n"
            "  default: /models/main\n"
            "  provider: custom\n"
            "  base_url: http://127.0.0.1:8081/v1\n"
            "fallback_providers:\n"
            "  - provider: custom\n"
            "    model: /models/fallback\n"
            "    base_url: http://127.0.0.1:8083/v1\n"
            "smart_model_routing:\n"
            "  enabled: true\n"
            "  cheap_model:\n"
            "    provider: custom\n"
            "    model: /models/cheap\n"
            "    base_url: http://127.0.0.1:8083/v1\n"
            "auxiliary:\n"
            "  session_search:\n"
            "    provider: custom\n"
            "    model: /models/cheap\n"
            "    base_url: http://127.0.0.1:8083/v1\n"
            "delegation:\n"
            "  provider: custom\n"
            "  model: /models/main\n"
            "  base_url: http://127.0.0.1:8081/v1\n"
        )

        overview = _fetch_hermes_provider_overview(profile_home)
        assert overview["primary"]["model"] == "/models/main"
        assert overview["fallback_count"] == 1
        assert overview["smart_routing_enabled"] is True
        assert overview["cheap_model"]["model"] == "/models/cheap"
        assert overview["auxiliary_count"] == 1
        assert overview["delegation"]["model"] == "/models/main"

    def test_toolset_overview_reads_profile_toolsets(self, tmp_path):
        profile_home = tmp_path / "mesh-sidecar"
        profile_home.mkdir(parents=True)
        (profile_home / "config.yaml").write_text(
            "toolsets:\n"
            "  - terminal\n"
            "  - memory\n"
            "  - delegation\n"
        )

        overview = _fetch_hermes_toolset_overview(profile_home)
        assert overview["toolset_count"] == 3
        assert overview["all_tools"] is False
        assert overview["has_terminal"] is True
        assert overview["has_memory"] is True
        assert overview["has_delegation"] is True

    def test_skill_overview_reads_local_and_external_dirs(self, tmp_path):
        profile_home = tmp_path / "mesh-sidecar"
        local_skill = profile_home / "skills" / "devops" / "local-skill"
        external_root = tmp_path / "shared-skills"
        external_skill = external_root / "mesh" / "mesh-health"
        local_skill.mkdir(parents=True)
        external_skill.mkdir(parents=True)
        (local_skill / "SKILL.md").write_text("# local\n")
        (external_skill / "SKILL.md").write_text("# external\n")
        (profile_home / "config.yaml").write_text(
            "skills:\n"
            f"  external_dirs:\n"
            f"    - {external_root}\n"
        )

        overview = _fetch_hermes_skill_overview(profile_home)
        assert overview["local_skill_count"] == 1
        assert overview["external_dir_count"] == 1
        assert overview["external_skill_count"] == 1
        assert overview["shared_skills_connected"] is True
        assert "mesh/mesh-health" in overview["external_dirs"][0]["sample_skills"]

    def test_memory_overview_reads_built_in_files_and_provider_readiness(self, tmp_path):
        profile_home = tmp_path / "mesh-sidecar"
        memories_dir = profile_home / "memories"
        memories_dir.mkdir(parents=True)
        (memories_dir / "MEMORY.md").write_text("repo facts\n")
        (memories_dir / "USER.md").write_text("operator prefs\n")
        (profile_home / "config.yaml").write_text(
            "memory:\n"
            "  memory_enabled: true\n"
            "  user_profile_enabled: true\n"
            "  memory_char_limit: 4000\n"
            "  user_char_limit: 2500\n"
            "  nudge_interval: 10\n"
            "  flush_min_turns: 6\n"
            "mcp_servers:\n"
            "  openviking-memory:\n"
            "    url: http://127.0.0.1:2033/mcp\n"
        )

        overview = _fetch_hermes_memory_overview(profile_home)
        assert overview["memory_enabled"] is True
        assert overview["user_profile_enabled"] is True
        assert overview["memory_file_exists"] is True
        assert overview["user_file_exists"] is True
        assert overview["memory_char_count"] > 0
        assert overview["user_char_count"] > 0
        assert overview["external_provider_active"] is False
        assert overview["external_provider_available"] is True
        assert "openviking-memory" in overview["external_provider_candidates"]

    def test_memory_overview_marks_external_provider_active_when_selected(self, tmp_path):
        profile_home = tmp_path / "mesh-reasoning"
        memories_dir = profile_home / "memories"
        memories_dir.mkdir(parents=True)
        (profile_home / "config.yaml").write_text(
            "memory:\n"
            "  memory_enabled: true\n"
            "  user_profile_enabled: false\n"
            "  provider: openviking\n"
            "mcp_servers:\n"
            "  openviking-memory:\n"
            "    url: http://127.0.0.1:2033/mcp\n"
        )

        overview = _fetch_hermes_memory_overview(profile_home)
        assert overview["external_provider_name"] == "openviking"
        assert overview["external_provider_active"] is True
        assert overview["external_provider_endpoint"] == "http://127.0.0.1:2033/mcp"

    def test_background_log_endpoint_returns_tail(self, tmp_path, monkeypatch):
        import backend.routers.hermes as main_mod

        log_path = tmp_path / "task.log"
        log_path.write_text("line 1\nline 2\nline 3\n")
        monkeypatch.setattr(
            main_mod,
            "_fetch_hermes_background_tasks",
            lambda: [{"id": "bg_1", "log_path": str(log_path), "status": "finished", "running": False}],
        )

        response = client.get("/api/hermes/background/bg_1/log?lines=2")
        assert response.status_code == 200
        assert response.json()["log"] == "line 2\nline 3"

    def test_background_poll_endpoint_returns_task(self, monkeypatch):
        import backend.routers.hermes as main_mod

        monkeypatch.setattr(
            main_mod,
            "_fetch_hermes_background_tasks",
            lambda: [{"id": "bg_1", "status": "running", "running": True}],
        )

        response = client.get("/api/hermes/background/bg_1")
        assert response.status_code == 200
        assert response.json()["task"]["status"] == "running"


class TestHermesBackgroundTasks:
    def test_background_task_request_validation(self):
        req = HermesBackgroundTaskRequest(profile="mesh-sidecar", prompt="Summarize repo drift", title="sidecar run")
        assert req.profile == "mesh-sidecar"
        assert req.prompt == "Summarize repo drift"

    def test_build_background_command_uses_profile(self):
        assert _build_hermes_background_command("default", "hello")[1:] == ["chat", "-q", "hello"]
        assert _build_hermes_background_command("mesh-sidecar", "hello")[1:] == ["-p", "mesh-sidecar", "chat", "-q", "hello"]
        assert _build_hermes_background_command("mesh-sidecar", "hello", use_worktree=True)[1:] == ["-p", "mesh-sidecar", "chat", "--worktree", "-q", "hello"]

    def test_refresh_background_task_state_marks_finished(self):
        task = {"id": "bg_1", "pid": 999999, "status": "running", "running": True}
        refreshed = _refresh_background_task_state(task)
        assert refreshed["running"] is False
        assert refreshed["status"] == "finished"

    def test_refresh_background_task_state_extracts_worktree_metadata(self, tmp_path):
        log_path = tmp_path / "task.log"
        log_path.write_text("✓ Worktree created: /tmp/repo/.worktrees/hermes-1234\n  Branch: hermes/hermes-1234\n")
        task = {"id": "bg_1", "pid": None, "status": "finished", "running": False, "log_path": str(log_path)}
        refreshed = _refresh_background_task_state(task)
        assert refreshed["worktree_path"] == "/tmp/repo/.worktrees/hermes-1234"
        assert refreshed["worktree_branch"] == "hermes/hermes-1234"

    def test_reads_quick_commands_from_profile_config(self, tmp_path):
        profile_home = tmp_path / "profile"
        profile_home.mkdir()
        (profile_home / "config.yaml").write_text(
            "quick_commands:\n"
            "  status:\n"
            "    type: exec\n"
            "    command: echo ok\n"
        )
        commands = _read_hermes_quick_commands(profile_home)
        assert commands == [{"name": "status", "type": "exec", "command": "echo ok"}]

    def test_cleanup_worktree_removes_path(self, tmp_path, monkeypatch):
        import backend.helpers as main_mod

        worktree_path = tmp_path / "repo" / ".worktrees" / "hermes-1234"
        worktree_path.mkdir(parents=True)
        registry_path = tmp_path / "tasks.json"
        monkeypatch.setattr(main_mod, "HERMES_BACKGROUND_TASKS_PATH", registry_path)
        monkeypatch.setattr(main_mod, "_resolve_repo_root", lambda repo_path: tmp_path / "repo")
        registry_path.write_text(json.dumps([{
            "id": "bg_1",
            "running": False,
            "status": "finished",
            "mode": "worktree",
            "repo_path": str(tmp_path / "repo"),
            "worktree_path": str(worktree_path),
        }]))

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(main_mod.subprocess, "run", lambda *args, **kwargs: _Proc())

        task = _cleanup_hermes_worktree("bg_1")
        assert task is not None
        assert task["status"] == "cleaned"

    def test_cleanup_worktree_is_idempotent_when_already_removed(self, tmp_path, monkeypatch):
        import backend.helpers as main_mod

        worktree_path = tmp_path / "repo" / ".worktrees" / "hermes-1234"
        registry_path = tmp_path / "tasks.json"
        monkeypatch.setattr(main_mod, "HERMES_BACKGROUND_TASKS_PATH", registry_path)
        monkeypatch.setattr(main_mod, "_resolve_repo_root", lambda repo_path: tmp_path / "repo")
        registry_path.write_text(json.dumps([{
            "id": "bg_1",
            "running": False,
            "status": "finished",
            "mode": "worktree",
            "repo_path": str(tmp_path / "repo"),
            "worktree_path": str(worktree_path),
        }]))

        class _ListProc:
            returncode = 0
            stdout = "worktree /tmp/repo\n"
            stderr = ""

        monkeypatch.setattr(main_mod.subprocess, "run", lambda *args, **kwargs: _ListProc())

        task = _cleanup_hermes_worktree("bg_1")
        assert task is not None
        assert task["status"] == "cleaned"


class TestAvailabilityEndpoint:
    def test_set_availability_override(self, tmp_path, monkeypatch):
        import backend.helpers as main_mod
        monkeypatch.setattr(main_mod, "AVAILABILITY_OVERRIDES_PATH", tmp_path / "availability.json")
        monkeypatch.setattr(main_mod, "PERMISSION_AUDIT_LOG_PATH", tmp_path / "permission_audit.jsonl")
        monkeypatch.setitem(main_mod._state, "permission_audit_summary", {})
        r = client.post("/api/availability", json={
            "agent": "claude",
            "availability": "rate_limited",
            "note": "Anthropic limit reached",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["overrides"]["claude"]["availability"] == "rate_limited"
        audit = client.get("/api/permissions/audit?last=5").json()
        assert audit["entries"][-1]["tool"] == "availability-override"
        assert audit["entries"][-1]["decision"] == "allow"


class TestPresenceClassification:
    def test_finalize_agents_marks_registered_agents_distinct_from_offline(self):
        agents = [
            {
                "name": "hermes",
                "runtime_status": "offline",
                "status": "offline",
                "registration_status": "registered",
                "orchestration_status": "idle",
                "local_profiles": [],
            },
            {
                "name": "browser",
                "runtime_status": "offline",
                "status": "offline",
                "registration_status": "local-only",
                "orchestration_status": "unregistered",
                "local_profiles": [],
            },
        ]
        services = {
            "hermes_gateway": {"status": "down", "detail": {}},
            "aimaestro": {"status": "up"},
        }

        result = _finalize_agents(agents, services, {"hermes": None, "browser": None})

        hermes = next(agent for agent in result if agent["name"] == "hermes")
        browser = next(agent for agent in result if agent["name"] == "browser")
        assert hermes["presence"]["status"] == "registered"
        assert hermes["presence"]["kind"] == "external-registration"
        assert browser["presence"]["status"] == "offline"
        assert browser["presence"]["kind"] == "local-runtime"


class TestPermissionAudit:
    def test_permission_audit_request_rejects_invalid_decision(self):
        with pytest.raises(ValidationError, match="decision must be one of"):
            PermissionAuditRequest(source="codex", decision="approve", mode="default")

    def test_permission_audit_round_trip(self, tmp_path, monkeypatch):
        import backend.helpers as main_mod

        monkeypatch.setattr(main_mod, "PERMISSION_AUDIT_LOG_PATH", tmp_path / "permission_audit.jsonl")
        monkeypatch.setitem(main_mod._state, "permission_audit_summary", {})

        r = client.post("/api/permissions/audit", json={
            "source": "codex",
            "agent": "claude",
            "tool": "exec_command",
            "decision": "allow",
            "mode": "default",
            "reason": "safe local read",
            "input_summary": "rg -n mesh backend/main.py",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["entry"]["decision"] == "allow"
        assert body["summary"]["decision_counts"]["allow"] == 1

        r = client.get("/api/permissions/audit?last=10")
        assert r.status_code == 200
        data = r.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["tool"] == "exec_command"
        assert data["summary"]["count"] == 1


class TestLocalProfileActions:
    def test_start_profile_requires_installed_model(self, monkeypatch, tmp_path):
        import backend.helpers as main_mod

        monkeypatch.setattr(main_mod, "PERMISSION_AUDIT_LOG_PATH", tmp_path / "permission_audit.jsonl")
        monkeypatch.setitem(main_mod._state, "permission_audit_summary", {})
        monkeypatch.setitem(main_mod._state, "agents", [
            {
                "name": "hermes",
                "local_profiles": [
                    {
                        "name": "code-specialist",
                        "mode": "on-demand",
                        "installed": False,
                        "running": False,
                        "model_path": "/tmp/missing-model",
                        "base_url": "http://127.0.0.1:8084/v1",
                        "port": 8084,
                    }
                ],
            }
        ])
        r = client.post("/api/local-profiles/action", json={
            "agent": "hermes",
            "profile": "code-specialist",
            "action": "start",
        })
        assert r.status_code == 400
        assert "model not installed" in r.json()["detail"]
        audit = client.get("/api/permissions/audit?last=5").json()
        assert audit["entries"][-1]["tool"] == "local-profile-action"
        assert audit["entries"][-1]["decision"] == "deny"

    def test_stop_profile_without_pid_is_ok(self, monkeypatch):
        import backend.helpers as main_mod
        monkeypatch.setitem(main_mod._state, "agents", [
            {
                "name": "hermes",
                "local_profiles": [
                    {
                        "name": "code-specialist",
                        "mode": "on-demand",
                        "installed": True,
                        "running": False,
                        "model_path": "/tmp/model",
                        "base_url": "http://127.0.0.1:8084/v1",
                        "port": 8084,
                    }
                ],
            }
        ])
        r = client.post("/api/local-profiles/action", json={
            "agent": "hermes",
            "profile": "code-specialist",
            "action": "stop",
        })
        assert r.status_code == 200
        assert r.json()["status"] in {"not_running", "stopped"}

    def test_finalize_agents_adds_hermes_native_default_profile(self, monkeypatch, tmp_path):
        import backend.helpers as main_mod

        hermes_home = tmp_path / ".hermes"
        hermes_home.mkdir(parents=True)
        (hermes_home / "config.yaml").write_text(
            "model:\n"
            "  model: /tmp/qwen\n"
            "  provider: custom\n"
            "  base_url: http://127.0.0.1:8081/v1\n"
        )
        monkeypatch.setattr(main_mod, "HERMES_HOME", hermes_home)
        monkeypatch.setattr(main_mod, "HERMES_PROFILES_DIR", hermes_home / "profiles")
        monkeypatch.setattr(main_mod, "LOCAL_BIN_DIR", tmp_path / ".local" / "bin")

        agents = [{
            "name": "hermes",
            "runtime_status": "offline",
            "status": "offline",
            "registration_status": "local-only",
            "orchestration_status": "unknown",
            "local_profiles": [],
        }]
        services = {"hermes_gateway": {"status": "down", "detail": {}}, "aimaestro": {"status": "down"}}

        result = main_mod._finalize_agents(agents, services, {"hermes": None})
        hermes = result[0]
        native = next(profile for profile in hermes["local_profiles"] if profile["name"] == "profile:default")
        assert native["profile_kind"] == "hermes-native"
        assert native["installed"] is True
        assert native["hermes_profile"] == "default"
        assert native["base_url"] == "http://127.0.0.1:8081/v1"

    def test_start_hermes_native_profile_runs_gateway(self, monkeypatch, tmp_path):
        import backend.helpers as main_mod

        hermes_home = tmp_path / ".hermes"
        profile_home = hermes_home / "profiles" / "coder"
        profile_home.mkdir(parents=True)
        hermes_bin = tmp_path / "bin" / "hermes"
        hermes_bin.parent.mkdir(parents=True)
        hermes_bin.write_text("#!/bin/sh\n")
        monkeypatch.setattr(main_mod, "HERMES_HOME", hermes_home)
        monkeypatch.setattr(main_mod, "HERMES_PROFILES_DIR", hermes_home / "profiles")
        monkeypatch.setattr(main_mod, "HERMES_BIN", hermes_bin)
        monkeypatch.setattr(main_mod, "PERMISSION_AUDIT_LOG_PATH", tmp_path / "permission_audit.jsonl")
        monkeypatch.setitem(main_mod._state, "permission_audit_summary", {})
        monkeypatch.setitem(main_mod._state, "agents", [
            {
                "name": "hermes",
                "local_profiles": [
                    {
                        "name": "profile:coder",
                        "profile_kind": "hermes-native",
                        "hermes_profile": "coder",
                        "installed": True,
                        "running": False,
                    }
                ],
            }
        ])

        class _Proc:
            returncode = 0
            stdout = "gateway started"
            stderr = ""

        monkeypatch.setattr(main_mod.subprocess, "run", lambda *args, **kwargs: _Proc())

        r = client.post("/api/local-profiles/action", json={
            "agent": "hermes",
            "profile": "profile:coder",
            "action": "start",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "started"
        assert body["profile_kind"] == "hermes-native"
        assert body["hermes_profile"] == "coder"

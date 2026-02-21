"""
Tests for the manage() system management tool.
All Supervisor API calls are mocked — no real API calls.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from tools.manage import (
    manage,
    _get_tier,
    _confirmation_prompt,
    _handle_backup,
    _handle_update,
    _handle_restart,
    _handle_install,
    _handle_health,
    _handle_logs,
    set_audit_store,
)


# ── Tier classification ──────────────────────────────


class TestTierClassification:
    def test_backup_create_is_tier_0(self):
        assert _get_tier("backup", "create") == 0

    def test_backup_list_is_tier_0(self):
        assert _get_tier("backup", "list") == 0

    def test_health_is_tier_0(self):
        assert _get_tier("health", "") == 0

    def test_logs_core_is_tier_0(self):
        assert _get_tier("logs", "core") == 0

    def test_logs_addon_is_tier_0(self):
        assert _get_tier("logs", "addon:some_slug") == 0

    def test_backup_restore_is_tier_2(self):
        assert _get_tier("backup", "restore") == 2

    def test_update_core_is_tier_1(self):
        assert _get_tier("update", "core") == 1

    def test_update_os_is_tier_1(self):
        assert _get_tier("update", "os") == 1

    def test_restart_core_is_tier_1(self):
        assert _get_tier("restart", "core") == 1

    def test_restart_addon_is_tier_1(self):
        assert _get_tier("restart", "addon:xyz") == 1

    def test_install_addon_is_tier_1(self):
        assert _get_tier("install", "addon:xyz") == 1

    def test_backup_delete_is_tier_1(self):
        assert _get_tier("backup", "delete") == 1


# ── Confirmation prompt ──────────────────────────────


class TestConfirmationPrompt:
    def test_tier_1_prompt_contains_disruptive(self):
        result = _confirmation_prompt(
            "restart", "core", 1, "detail"
        )
        assert "DISRUPTIVE" in result
        assert "restart" in result
        assert "confirmed" in result

    def test_tier_2_prompt_contains_destructive(self):
        result = _confirmation_prompt(
            "backup", "restore", 2, "detail"
        )
        assert "DESTRUCTIVE" in result
        assert "confirmed" in result


# ── manage() integration ─────────────────────────────


class TestManageIntegration:
    """Test the main manage() function routing + tiers."""

    @pytest.mark.asyncio
    async def test_safe_op_executes_immediately(self):
        """Tier 0 ops should not require confirmation."""
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={
                "data": {"backups": []}
            },
        ):
            result = await manage(
                action="backup", target="list"
            )
            assert "No backups found" in result

    @pytest.mark.asyncio
    async def test_destructive_op_returns_confirmation(self):
        """Tier 1+ ops without confirmed=True return prompt."""
        result = await manage(
            action="restart", target="core"
        )
        assert "DISRUPTIVE" in result
        assert "confirmed" in result

    @pytest.mark.asyncio
    async def test_destructive_op_executes_with_confirm(self):
        """Tier 1+ ops with confirmed=True execute."""
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await manage(
                action="restart",
                target="core",
                config={"confirmed": True},
            )
            assert "restart initiated" in result

    @pytest.mark.asyncio
    async def test_tier_2_returns_confirmation(self):
        """Tier 2 ops return destructive warning."""
        result = await manage(
            action="backup", target="restore",
            config={"backup_id": "abc123"},
        )
        assert "DESTRUCTIVE" in result

    @pytest.mark.asyncio
    async def test_tier_2_executes_with_confirm(self):
        """Tier 2 ops with confirmed=True execute."""
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await manage(
                action="backup",
                target="restore",
                config={
                    "backup_id": "abc123",
                    "confirmed": True,
                },
            )
            assert "restore initiated" in result

    @pytest.mark.asyncio
    async def test_webhook_session_blocked_from_tier_1(self):
        """apex_events sessions can only use Tier 0."""
        result = await manage(
            action="restart",
            target="core",
            session_id="apex_events",
        )
        assert "restricted" in result
        assert "Tier 0" in result

    @pytest.mark.asyncio
    async def test_webhook_session_allowed_tier_0(self):
        """apex_events sessions can use Tier 0 ops."""
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={
                "data": {"backups": []}
            },
        ):
            result = await manage(
                action="backup",
                target="list",
                session_id="apex_events",
            )
            assert "No backups found" in result

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        """Unknown actions return helpful error."""
        result = await manage(
            action="explode", target="everything",
            config={"confirmed": True},
        )
        assert "Unknown action" in result
        assert "backup" in result  # lists valid actions


# ── Backup handlers ──────────────────────────────────


class TestBackupHandlers:
    @pytest.mark.asyncio
    async def test_backup_create(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={
                "data": {"slug": "abc123"}
            },
        ):
            result = await _handle_backup("create", {})
            assert "created" in result
            assert "abc123" in result

    @pytest.mark.asyncio
    async def test_backup_create_with_name(self):
        mock = AsyncMock(
            return_value={"data": {"slug": "abc"}}
        )
        with patch(
            "tools.manage._supervisor_request", mock
        ):
            result = await _handle_backup(
                "create", {"name": "my backup"}
            )
            assert "created" in result
            # Verify name was passed
            mock.assert_called_once_with(
                "POST", "/backups/new/full",
                {"name": "my backup"},
            )

    @pytest.mark.asyncio
    async def test_backup_list_with_backups(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={
                "data": {
                    "backups": [
                        {
                            "name": "daily",
                            "slug": "abc",
                            "date": "2026-02-17",
                            "type": "full",
                        },
                    ]
                }
            },
        ):
            result = await _handle_backup("list", {})
            assert "daily" in result
            assert "abc" in result

    @pytest.mark.asyncio
    async def test_backup_list_empty(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {"backups": []}},
        ):
            result = await _handle_backup("list", {})
            assert "No backups found" in result

    @pytest.mark.asyncio
    async def test_backup_restore_requires_id(self):
        result = await _handle_backup("restore", {})
        assert "backup_id is required" in result

    @pytest.mark.asyncio
    async def test_backup_restore(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_backup(
                "restore", {"backup_id": "abc"}
            )
            assert "restore initiated" in result

    @pytest.mark.asyncio
    async def test_backup_delete_requires_id(self):
        result = await _handle_backup("delete", {})
        assert "backup_id is required" in result

    @pytest.mark.asyncio
    async def test_backup_delete(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_backup(
                "delete", {"backup_id": "abc"}
            )
            assert "deleted" in result

    @pytest.mark.asyncio
    async def test_backup_unknown_target(self):
        result = await _handle_backup("bogus", {})
        assert "Unknown backup target" in result


# ── Update handlers ──────────────────────────────────


class TestUpdateHandlers:
    @pytest.mark.asyncio
    async def test_update_core(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_update("core", {})
            assert "Core update initiated" in result

    @pytest.mark.asyncio
    async def test_update_os(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_update("os", {})
            assert "HAOS update initiated" in result

    @pytest.mark.asyncio
    async def test_update_addon(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_update(
                "addon:my_addon", {}
            )
            assert "my_addon" in result
            assert "update initiated" in result

    @pytest.mark.asyncio
    async def test_update_unknown_target(self):
        result = await _handle_update("bogus", {})
        assert "Unknown update target" in result


# ── Restart handlers ─────────────────────────────────


class TestRestartHandlers:
    @pytest.mark.asyncio
    async def test_restart_core(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_restart("core", {})
            assert "Core restart initiated" in result

    @pytest.mark.asyncio
    async def test_restart_supervisor(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_restart(
                "supervisor", {}
            )
            assert "Supervisor restart initiated" in result

    @pytest.mark.asyncio
    async def test_restart_addon(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_restart(
                "addon:test_addon", {}
            )
            assert "test_addon" in result
            assert "restart initiated" in result

    @pytest.mark.asyncio
    async def test_restart_unknown_target(self):
        result = await _handle_restart("bogus", {})
        assert "Unknown restart target" in result


# ── Install handler ──────────────────────────────────


class TestInstallHandler:
    @pytest.mark.asyncio
    async def test_install_addon(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"data": {}},
        ):
            result = await _handle_install(
                "addon:new_addon", {}
            )
            assert "new_addon" in result
            assert "installation initiated" in result

    @pytest.mark.asyncio
    async def test_install_requires_addon_prefix(self):
        result = await _handle_install("core", {})
        assert "addon:<slug>" in result


# ── Health handler ───────────────────────────────────


class TestHealthHandler:
    @pytest.mark.asyncio
    async def test_health_aggregates_info(self):
        async def mock_request(method, path, **kw):
            if path == "/core/info":
                return {
                    "data": {
                        "version": "2026.2.0",
                        "machine": "amd64",
                    }
                }
            if path == "/os/info":
                return {"data": {"version": "12.0"}}
            if path == "/supervisor/info":
                return {"data": {"version": "2026.01"}}
            return {"error": "unknown"}

        with patch(
            "tools.manage._supervisor_request",
            side_effect=mock_request,
        ):
            result = await _handle_health("", {})
            assert "2026.2.0" in result
            assert "12.0" in result
            assert "2026.01" in result

    @pytest.mark.asyncio
    async def test_health_handles_errors(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value={"error": "no token"},
        ):
            result = await _handle_health("", {})
            assert "no token" in result


# ── Logs handler ─────────────────────────────────────


class TestLogsHandler:
    @pytest.mark.asyncio
    async def test_logs_core(self):
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value="line1\nline2\nline3",
        ):
            result = await _handle_logs("core", {})
            assert "line1" in result

    @pytest.mark.asyncio
    async def test_logs_default_target(self):
        mock = AsyncMock(return_value="log output")
        with patch(
            "tools.manage._supervisor_request", mock
        ):
            await _handle_logs("", {})
            mock.assert_called_once_with(
                "GET", "/core/logs", as_text=True
            )

    @pytest.mark.asyncio
    async def test_logs_supervisor(self):
        mock = AsyncMock(return_value="sup logs")
        with patch(
            "tools.manage._supervisor_request", mock
        ):
            await _handle_logs("supervisor", {})
            mock.assert_called_once_with(
                "GET", "/supervisor/logs", as_text=True
            )

    @pytest.mark.asyncio
    async def test_logs_addon(self):
        mock = AsyncMock(return_value="addon logs")
        with patch(
            "tools.manage._supervisor_request", mock
        ):
            await _handle_logs("addon:my_addon", {})
            mock.assert_called_once_with(
                "GET", "/addons/my_addon/logs", as_text=True
            )

    @pytest.mark.asyncio
    async def test_logs_unknown_target(self):
        result = await _handle_logs("bogus", {})
        assert "Unknown logs target" in result

    @pytest.mark.asyncio
    async def test_logs_truncated_to_50_lines(self):
        long_log = "\n".join(
            f"line {i}" for i in range(100)
        )
        with patch(
            "tools.manage._supervisor_request",
            new_callable=AsyncMock,
            return_value=long_log,
        ):
            result = await _handle_logs("core", {})
            lines = result.strip().splitlines()
            assert len(lines) == 50


# ── Supervisor unavailable ───────────────────────────


class TestSupervisorUnavailable:
    @pytest.mark.asyncio
    async def test_no_token_returns_error(self):
        with patch(
            "tools.manage._get_supervisor_token",
            return_value=None,
        ):
            result = await manage(
                action="backup", target="list"
            )
            assert "SUPERVISOR_TOKEN" in result
            assert "unavailable" in result


# ── Audit logging ────────────────────────────────────


class TestManageAuditLogging:
    @pytest.mark.asyncio
    async def test_safe_op_logged(self):
        mock_store = MagicMock()
        mock_store.log = AsyncMock(return_value=1)
        set_audit_store(mock_store)
        try:
            with patch(
                "tools.manage._supervisor_request",
                new_callable=AsyncMock,
                return_value={
                    "data": {"backups": []}
                },
            ):
                await manage(
                    action="backup", target="list"
                )
            mock_store.log.assert_called_once()
            call_kw = mock_store.log.call_args.kwargs
            assert call_kw["tool"] == "manage"
            assert call_kw["action"] == "backup"
            assert call_kw["result"] == "executed"
        finally:
            set_audit_store(None)

    @pytest.mark.asyncio
    async def test_confirmation_prompt_logged(self):
        mock_store = MagicMock()
        mock_store.log = AsyncMock(return_value=1)
        set_audit_store(mock_store)
        try:
            await manage(
                action="restart", target="core"
            )
            mock_store.log.assert_called_once()
            call_kw = mock_store.log.call_args.kwargs
            assert call_kw["result"] == "confirmation_prompted"
            assert call_kw["user_approved"] is False
        finally:
            set_audit_store(None)

    @pytest.mark.asyncio
    async def test_webhook_denial_logged(self):
        mock_store = MagicMock()
        mock_store.log = AsyncMock(return_value=1)
        set_audit_store(mock_store)
        try:
            await manage(
                action="restart",
                target="core",
                session_id="apex_events",
            )
            mock_store.log.assert_called_once()
            call_kw = mock_store.log.call_args.kwargs
            assert call_kw["result"] == "denied"
        finally:
            set_audit_store(None)

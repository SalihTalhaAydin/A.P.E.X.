"""
Tests for the configure() registry management tool.
All WebSocket API calls are mocked — no real connections.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from tools.configure import (
    configure,
    _get_tier,
    _confirmation_prompt,
    _handle_rename,
    _handle_assign_area,
    _handle_disable,
    _handle_enable,
    _handle_create_area,
    _handle_delete_area,
    _handle_remove,
    _handle_list_stale,
    set_audit_store,
)


# ── Tier classification ──────────────────────────────


class TestTierClassification:
    def test_rename_is_tier_0(self):
        assert _get_tier("rename") == 0

    def test_assign_area_is_tier_0(self):
        assert _get_tier("assign_area") == 0

    def test_enable_is_tier_0(self):
        assert _get_tier("enable") == 0

    def test_create_area_is_tier_0(self):
        assert _get_tier("create_area") == 0

    def test_list_stale_is_tier_0(self):
        assert _get_tier("list_stale") == 0

    def test_disable_is_tier_1(self):
        assert _get_tier("disable") == 1

    def test_delete_area_is_tier_1(self):
        assert _get_tier("delete_area") == 1

    def test_remove_is_tier_2(self):
        assert _get_tier("remove") == 2


# ── Confirmation prompt ──────────────────────────────


class TestConfirmationPrompt:
    def test_tier_1_prompt_contains_moderate(self):
        result = _confirmation_prompt(
            "disable", "sensor.test", 1, "detail"
        )
        assert "MODERATE" in result
        assert "confirmed" in result

    def test_tier_2_prompt_contains_destructive(self):
        result = _confirmation_prompt(
            "remove", "device_abc", 2, "detail"
        )
        assert "DESTRUCTIVE" in result
        assert "confirmed" in result


# ── configure() integration ──────────────────────────


class TestConfigureIntegration:
    @pytest.mark.asyncio
    async def test_safe_op_executes_immediately(self):
        """Tier 0 ops execute without confirmation."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={
                "entity_id": "light.kitchen",
                "name": "Kitchen Light",
            },
        ):
            result = await configure(
                action="rename",
                target="light.kitchen",
                data={"name": "Kitchen Light"},
            )
            assert "Renamed" in result

    @pytest.mark.asyncio
    async def test_tier_1_returns_confirmation(self):
        """Tier 1 ops without confirmed=True return prompt."""
        result = await configure(
            action="disable",
            target="sensor.test",
        )
        assert "MODERATE" in result
        assert "confirmed" in result

    @pytest.mark.asyncio
    async def test_tier_1_executes_with_confirm(self):
        """Tier 1 ops with confirmed=True execute."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={"entity_id": "sensor.test"},
        ):
            result = await configure(
                action="disable",
                target="sensor.test",
                data={"confirmed": True},
            )
            assert "Disabled" in result

    @pytest.mark.asyncio
    async def test_tier_2_returns_confirmation(self):
        """Tier 2 ops return destructive warning."""
        result = await configure(
            action="remove",
            target="device_abc",
        )
        assert "DESTRUCTIVE" in result

    @pytest.mark.asyncio
    async def test_tier_2_executes_with_confirm(self):
        """Tier 2 ops with confirmed=True execute."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await configure(
                action="remove",
                target="device_abc",
                data={"confirmed": True},
            )
            assert "removed" in result

    @pytest.mark.asyncio
    async def test_webhook_session_blocked(self):
        """apex_events sessions restricted to Tier 0."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
        ) as mock_ws:
            result = await configure(
                action="disable",
                target="sensor.test",
                session_id="apex_events",
            )
            assert "restricted" in result
            assert "Tier 0" in result
            mock_ws.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_session_blocked_unique_id(self):
        """apex_events_* (unique per event) sessions restricted to Tier 0."""
        result = await configure(
            action="disable",
            target="sensor.test",
            session_id="apex_events:binary_sensor.motion:abc123",
        )
        assert "restricted" in result
        assert "Tier 0" in result

    @pytest.mark.asyncio
    async def test_webhook_session_allowed_tier_0(self):
        """apex_events can use Tier 0 ops."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={
                "name": "New Name",
            },
        ):
            result = await configure(
                action="rename",
                target="light.test",
                data={"name": "New Name"},
                session_id="apex_events",
            )
            assert "Renamed" in result

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        result = await configure(
            action="explode",
            target="everything",
            data={"confirmed": True},
        )
        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_dry_run_disable(self):
        """Dry-run mode shows what would happen."""
        result = await configure(
            action="disable",
            target="sensor.test",
            data={"dry_run": True},
        )
        assert "DRY RUN" in result
        assert "sensor.test" in result

    @pytest.mark.asyncio
    async def test_dry_run_delete_area(self):
        result = await configure(
            action="delete_area",
            target="old_room",
            data={"dry_run": True},
        )
        assert "DRY RUN" in result
        assert "old_room" in result

    @pytest.mark.asyncio
    async def test_dry_run_remove(self):
        result = await configure(
            action="remove",
            target="device_abc",
            data={"dry_run": True},
        )
        assert "DRY RUN" in result
        assert "device_abc" in result


# ── Rename handler ───────────────────────────────────


class TestRenameHandler:
    @pytest.mark.asyncio
    async def test_rename_entity(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={"name": "New Name"},
        ) as mock_ws:
            result = await _handle_rename(
                "light.kitchen", {"name": "New Name"}
            )
            assert "Renamed" in result
            assert "New Name" in result
            mock_ws.assert_called_once()
            cmd = mock_ws.call_args[0][0]
            assert cmd["type"] == (
                "config/entity_registry/update"
            )
            assert cmd["entity_id"] == "light.kitchen"
            assert cmd["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_rename_requires_name(self):
        result = await _handle_rename(
            "light.kitchen", {}
        )
        assert "name is required" in result

    @pytest.mark.asyncio
    async def test_rename_requires_target(self):
        result = await _handle_rename(
            "", {"name": "Test"}
        )
        assert "target" in result.lower()


# ── Assign area handler ─────────────────────────────


class TestAssignAreaHandler:
    @pytest.mark.asyncio
    async def test_assign_entity_to_area(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_ws:
            result = await _handle_assign_area(
                "light.kitchen",
                {"area_id": "kitchen"},
            )
            assert "Assigned entity" in result
            cmd = mock_ws.call_args[0][0]
            assert cmd["type"] == (
                "config/entity_registry/update"
            )

    @pytest.mark.asyncio
    async def test_assign_device_to_area(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_ws:
            result = await _handle_assign_area(
                "abc123def",
                {"area_id": "kitchen"},
            )
            assert "Assigned device" in result
            cmd = mock_ws.call_args[0][0]
            assert cmd["type"] == (
                "config/device_registry/update"
            )

    @pytest.mark.asyncio
    async def test_assign_requires_area_id(self):
        result = await _handle_assign_area(
            "light.kitchen", {}
        )
        assert "area_id is required" in result

    @pytest.mark.asyncio
    async def test_assign_requires_target(self):
        result = await _handle_assign_area(
            "", {"area_id": "kitchen"}
        )
        assert "target is required" in result


# ── Disable/Enable handlers ─────────────────────────


class TestDisableEnableHandlers:
    @pytest.mark.asyncio
    async def test_disable_entity(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_ws:
            result = await _handle_disable(
                "sensor.test", {}
            )
            assert "Disabled" in result
            cmd = mock_ws.call_args[0][0]
            assert cmd["disabled_by"] == "user"

    @pytest.mark.asyncio
    async def test_disable_requires_target(self):
        result = await _handle_disable("", {})
        assert "target" in result.lower()

    @pytest.mark.asyncio
    async def test_enable_entity(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_ws:
            result = await _handle_enable(
                "sensor.test", {}
            )
            assert "Enabled" in result
            cmd = mock_ws.call_args[0][0]
            assert cmd["disabled_by"] in (None, "")

    @pytest.mark.asyncio
    async def test_enable_requires_target(self):
        result = await _handle_enable("", {})
        assert "target" in result.lower()


# ── Area CRUD handlers ──────────────────────────────


class TestAreaHandlers:
    @pytest.mark.asyncio
    async def test_create_area(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={"area_id": "new_room"},
        ) as mock_ws:
            result = await _handle_create_area(
                "", {"name": "New Room"}
            )
            assert "created" in result
            assert "new_room" in result
            cmd = mock_ws.call_args[0][0]
            assert cmd["type"] == (
                "config/area_registry/create"
            )

    @pytest.mark.asyncio
    async def test_create_area_from_target(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={"area_id": "garage"},
        ):
            result = await _handle_create_area(
                "Garage", {}
            )
            assert "Garage" in result
            assert "created" in result

    @pytest.mark.asyncio
    async def test_create_area_requires_name(self):
        result = await _handle_create_area("", {})
        assert "name" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_area(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_ws:
            result = await _handle_delete_area(
                "old_room", {}
            )
            assert "deleted" in result
            cmd = mock_ws.call_args[0][0]
            assert cmd["type"] == (
                "config/area_registry/delete"
            )
            assert cmd["area_id"] == "old_room"

    @pytest.mark.asyncio
    async def test_delete_area_requires_target(self):
        result = await _handle_delete_area("", {})
        assert "target" in result.lower()


# ── Remove handler ───────────────────────────────────


class TestRemoveHandler:
    @pytest.mark.asyncio
    async def test_remove_device(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_ws:
            result = await _handle_remove(
                "device_abc", {}
            )
            assert "removed" in result
            cmd = mock_ws.call_args[0][0]
            assert cmd["type"] == (
                "config/device_registry/remove"
            )

    @pytest.mark.asyncio
    async def test_remove_requires_target(self):
        result = await _handle_remove("", {})
        assert "target" in result.lower()


# ── List stale handler ───────────────────────────────


class TestListStaleHandler:
    @pytest.mark.asyncio
    async def test_list_stale_finds_unavailable(self):
        """Entities in unavailable state are reported as stale."""
        entities = [
            {
                "entity_id": "sensor.test",
                "name": "Test Sensor",
                "disabled_by": None,
            },
            {
                "entity_id": "light.old",
                "name": "Old Light",
                "disabled_by": None,
            },
        ]
        states = [
            {"entity_id": "sensor.test", "state": "unavailable"},
            {"entity_id": "light.old", "state": "on"},
        ]
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=entities,
        ), patch(
            "tools.ha_helpers.ha_request",
            new_callable=AsyncMock,
            return_value=states,
        ):
            result = await _handle_list_stale("", {})
            assert "1 stale" in result
            assert "sensor.test" in result
            assert "light.old" not in result

    @pytest.mark.asyncio
    async def test_list_stale_skips_disabled(self):
        """Disabled entities are excluded from stale check."""
        entities = [
            {
                "entity_id": "sensor.test",
                "name": "Test",
                "disabled_by": "user",
            },
        ]
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=entities,
        ):
            result = await _handle_list_stale("", {})
            # All entities disabled → no active entities
            assert "No active" in result

    @pytest.mark.asyncio
    async def test_list_stale_no_active_entities(self):
        """Empty registry returns appropriate message."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _handle_list_stale("", {})
            assert "No active" in result


# ── Bug 35: None/error result handling ─────────────────


class TestWsResultHandling:
    """Regression tests for ws_command returning None or error results."""

    @pytest.mark.asyncio
    async def test_rename_handles_none_result(self):
        """_handle_rename does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _handle_rename(
                "light.kitchen", {"name": "New Name"}
            )
            assert "Error" in result
            assert "No response" in result or "response" in result.lower()

    @pytest.mark.asyncio
    async def test_rename_handles_ws_exception(self):
        """_handle_rename catches unexpected exceptions from ws_command."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            side_effect=ValueError("Unexpected"),
        ):
            result = await _handle_rename(
                "light.kitchen", {"name": "New Name"}
            )
            assert "Error" in result
            assert "Unexpected" in result

    @pytest.mark.asyncio
    async def test_create_area_handles_none_result(self):
        """_handle_create_area does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _handle_create_area(
                "", {"name": "New Room"}
            )
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_assign_area_handles_none_result(self):
        """_handle_assign_area does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _handle_assign_area(
                "light.kitchen", {"area_id": "kitchen"}
            )
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_disable_handles_none_result(self):
        """_handle_disable does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _handle_disable("sensor.test", {})
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_enable_handles_none_result(self):
        """_handle_enable does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _handle_enable("sensor.test", {})
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_delete_area_handles_none_result(self):
        """_handle_delete_area does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _handle_delete_area("old_room", {})
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_remove_handles_none_result(self):
        """_handle_remove does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _handle_remove("device_abc", {})
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_list_stale_handles_none_result(self):
        """_handle_list_stale does not crash when ws_command returns None."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "tools.ha_helpers.ha_request",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _handle_list_stale("", {})
            assert "No active" in result

    @pytest.mark.asyncio
    async def test_rename_handles_error_result(self):
        """_handle_rename returns error when result has success=False or error key."""
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            return_value={"success": False, "error": {"message": "Entity not found"}},
        ):
            result = await _handle_rename(
                "light.missing", {"name": "Test"}
            )
            assert "Error" in result
            assert "Entity not found" in result or "not found" in result.lower()


# ── Error handling ───────────────────────────────────


class TestConfigureErrorHandling:
    @pytest.mark.asyncio
    async def test_ws_connection_error(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            side_effect=ConnectionError(
                "Cannot connect"
            ),
        ):
            result = await configure(
                action="rename",
                target="light.test",
                data={"name": "Test"},
            )
            assert "Connection" in result or "Cannot connect" in result

    @pytest.mark.asyncio
    async def test_ws_auth_error(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            side_effect=PermissionError("Auth failed"),
        ):
            result = await configure(
                action="rename",
                target="light.test",
                data={"name": "Test"},
            )
            assert "Auth error" in result

    @pytest.mark.asyncio
    async def test_ws_timeout_error(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            side_effect=TimeoutError("Timed out"),
        ):
            result = await configure(
                action="rename",
                target="light.test",
                data={"name": "Test"},
            )
            assert "Timeout" in result

    @pytest.mark.asyncio
    async def test_ws_runtime_error(self):
        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            side_effect=RuntimeError("No token"),
        ):
            result = await configure(
                action="rename",
                target="light.test",
                data={"name": "Test"},
            )
            assert "Error" in result


# ── Audit logging ────────────────────────────────────


class TestConfigureAuditLogging:
    @pytest.mark.asyncio
    async def test_safe_op_logged(self):
        mock_store = MagicMock()
        mock_store.log = AsyncMock(return_value=1)
        set_audit_store(mock_store)
        try:
            with patch(
                "tools.configure.ws_command",
                new_callable=AsyncMock,
                return_value={"name": "X"},
            ):
                await configure(
                    action="rename",
                    target="light.test",
                    data={"name": "X"},
                )
            mock_store.log.assert_called_once()
            kw = mock_store.log.call_args.kwargs
            assert kw["tool"] == "configure"
            assert kw["action"] == "rename"
            assert kw["result"] == "executed"
        finally:
            set_audit_store(None)

    @pytest.mark.asyncio
    async def test_confirmation_logged(self):
        mock_store = MagicMock()
        mock_store.log = AsyncMock(return_value=1)
        set_audit_store(mock_store)
        try:
            await configure(
                action="disable",
                target="sensor.test",
            )
            mock_store.log.assert_called_once()
            kw = mock_store.log.call_args.kwargs
            assert kw["result"] == "confirmation_prompted"
        finally:
            set_audit_store(None)

    @pytest.mark.asyncio
    async def test_dry_run_logged(self):
        mock_store = MagicMock()
        mock_store.log = AsyncMock(return_value=1)
        set_audit_store(mock_store)
        try:
            await configure(
                action="disable",
                target="sensor.test",
                data={"dry_run": True},
            )
            mock_store.log.assert_called_once()
            kw = mock_store.log.call_args.kwargs
            assert kw["result"] == "dry_run"
        finally:
            set_audit_store(None)

    @pytest.mark.asyncio
    async def test_webhook_denial_logged(self):
        mock_store = MagicMock()
        mock_store.log = AsyncMock(return_value=1)
        set_audit_store(mock_store)
        try:
            await configure(
                action="disable",
                target="sensor.test",
                session_id="apex_events",
            )
            mock_store.log.assert_called_once()
            kw = mock_store.log.call_args.kwargs
            assert kw["result"] == "denied"
        finally:
            set_audit_store(None)

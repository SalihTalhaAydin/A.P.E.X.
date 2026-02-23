"""Tests for lock control tool (control_lock).

Covers:
- control_lock always self-confirms (mints a token and passes confirmed+token)
- Successful execution for lock, unlock, and open actions
- Unavailable and jammed state handling
- Unknown action handling
- Registration and schema
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    """Ensure all tools (including lock) are discovered."""
    from tools import discover_tools

    discover_tools()


# ==================================================================
# Registration tests
# ==================================================================


class TestControlLockRegistration:
    """Verify control_lock is registered with correct schema."""

    def test_control_lock_registered(self):
        info = TOOL_REGISTRY.get("control_lock")
        assert info is not None

    def test_control_lock_has_confirmed_param(self):
        props = TOOL_REGISTRY["control_lock"]["parameters"]["properties"]
        assert "confirmed" in props
        assert props["confirmed"]["type"] == "boolean"
        assert props["confirmed"].get("default") is False

    def test_control_lock_required_params(self):
        required = TOOL_REGISTRY["control_lock"]["parameters"]["required"]
        assert "entity_id" in required
        assert "action" in required
        assert "confirmed" not in required


# ==================================================================
# control_lock() behavior tests
# ==================================================================


class TestControlLock:
    """Tests for control_lock() tool."""

    async def test_always_self_confirms_with_token(self):
        """control_lock always passes confirmed=True and a valid token to do()."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.front_door",
            "state": "unlocked",
            "attributes": {"friendly_name": "Front Door"},
        }
        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
                return_value="Done. Front Door: locked",
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.front_door",
                    action="lock",
                )

        # Should NOT return CONFIRMATION REQUIRED
        assert "CONFIRMATION REQUIRED" not in result
        assert "Done" in result

        # Verify do() was called with confirmed=True and a confirmation_token
        mock_do.assert_called_once()
        call_args = mock_do.call_args
        assert call_args[0][0] == "lock"
        assert call_args[0][1] == "lock"
        assert call_args[0][2] == {"entity_id": "lock.front_door"}
        data = call_args[0][3]
        assert data["confirmed"] is True
        assert "confirmation_token" in data
        assert isinstance(data["confirmation_token"], str)
        assert len(data["confirmation_token"]) > 0

    async def test_confirmed_false_still_self_confirms(self):
        """Even with confirmed=False, control_lock self-confirms (bug #10 fix)."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.front_door",
            "state": "unlocked",
            "attributes": {"friendly_name": "Front Door"},
        }
        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
                return_value="Done. Front Door: locked",
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.front_door",
                    action="lock",
                    confirmed=False,
                )

        assert "CONFIRMATION REQUIRED" not in result
        assert "Done" in result
        data = mock_do.call_args[0][3]
        assert data["confirmed"] is True
        assert "confirmation_token" in data

    async def test_confirmed_true_self_confirms(self):
        """control_lock(confirmed=True) also self-confirms correctly."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.front_door",
            "state": "unlocked",
            "attributes": {"friendly_name": "Front Door"},
        }

        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
                return_value="Done. Front Door: locked",
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.front_door",
                    action="lock",
                    confirmed=True,
                )

        assert "Done" in result
        mock_do.assert_called_once()
        call_args = mock_do.call_args
        assert call_args[0][0] == "lock"
        assert call_args[0][1] == "lock"
        assert call_args[0][2] == {"entity_id": "lock.front_door"}
        data = call_args[0][3]
        assert data["confirmed"] is True
        assert "confirmation_token" in data

    async def test_unlock_self_confirms(self):
        """control_lock(action='unlock') self-confirms and passes unlock service."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.garage",
            "state": "locked",
            "attributes": {"friendly_name": "Garage Lock"},
        }

        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
                return_value="Done. Garage Lock: unlocked",
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.garage",
                    action="unlock",
                )

        assert "CONFIRMATION REQUIRED" not in result
        call_args = mock_do.call_args
        assert call_args[0][1] == "unlock"
        data = call_args[0][3]
        assert data["confirmed"] is True
        assert "confirmation_token" in data

    async def test_open_self_confirms(self):
        """control_lock(action='open') self-confirms and passes open service."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.electric_strike",
            "state": "locked",
            "attributes": {"friendly_name": "Electric Strike"},
        }

        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
                return_value="Done. Electric Strike: open",
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.electric_strike",
                    action="open",
                )

        assert "CONFIRMATION REQUIRED" not in result
        call_args = mock_do.call_args
        assert call_args[0][1] == "open"
        data = call_args[0][3]
        assert data["confirmed"] is True
        assert "confirmation_token" in data

    async def test_unavailable_lock_returns_error(self):
        """control_lock returns error for unavailable lock without calling do()."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.front_door",
            "state": "unavailable",
            "attributes": {"friendly_name": "Front Door"},
        }
        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.front_door",
                    action="lock",
                )

        assert "unavailable" in result
        mock_do.assert_not_called()

    async def test_jammed_lock_returns_warning(self):
        """control_lock returns warning for jammed lock without calling do()."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.front_door",
            "state": "jammed",
            "attributes": {"friendly_name": "Front Door"},
        }
        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.front_door",
                    action="lock",
                )

        assert "jammed" in result
        mock_do.assert_not_called()

    async def test_unknown_action_returns_error(self):
        """control_lock returns error for unknown action without calling do()."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.front_door",
            "state": "locked",
            "attributes": {"friendly_name": "Front Door"},
        }
        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
            ) as mock_do:
                result = await control_lock(
                    entity_id="lock.front_door",
                    action="smash",
                )

        assert "Unknown lock action" in result
        mock_do.assert_not_called()

    async def test_unique_token_per_call(self):
        """Each call to control_lock generates a unique confirmation token."""
        from tools.lock import control_lock

        state = {
            "entity_id": "lock.front_door",
            "state": "unlocked",
            "attributes": {"friendly_name": "Front Door"},
        }

        tokens = []
        with patch(
            "tools.lock.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            with patch(
                "tools.lock.do",
                new_callable=AsyncMock,
                return_value="Done. Front Door: locked",
            ) as mock_do:
                await control_lock(
                    entity_id="lock.front_door",
                    action="lock",
                )
                tokens.append(mock_do.call_args[0][3]["confirmation_token"])

                await control_lock(
                    entity_id="lock.front_door",
                    action="lock",
                )
                tokens.append(mock_do.call_args[0][3]["confirmation_token"])

        assert tokens[0] != tokens[1], "Each call should generate a unique token"

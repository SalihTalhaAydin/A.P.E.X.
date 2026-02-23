"""Tests for security tools (control_alarm).

Covers:
- control_alarm always self-confirms (mints a token and passes confirmed+token)
- With and without code parameter
- Successful execution for arm_home, arm_away, disarm, etc.
- Unknown action handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ==================================================================
# control_alarm() behavior tests
# ==================================================================


class TestControlAlarm:
    """Tests for control_alarm() tool."""

    async def test_always_self_confirms_without_code(self):
        """control_alarm passes confirmed=True and token when code is None."""
        from tools.security import control_alarm

        with patch(
            "tools.security.do",
            new_callable=AsyncMock,
            return_value="Done. Home Alarm: armed_home",
        ) as mock_do:
            result = await control_alarm(
                entity_id="alarm_control_panel.home",
                action="arm_home",
            )

        assert "CONFIRMATION REQUIRED" not in result
        assert "Done" in result

        mock_do.assert_called_once()
        call_args = mock_do.call_args
        assert call_args[0][0] == "alarm_control_panel"
        assert call_args[0][1] == "alarm_arm_home"
        assert call_args[0][2] == {"entity_id": "alarm_control_panel.home"}
        data = call_args[0][3]
        assert data["confirmed"] is True
        assert "confirmation_token" in data
        assert isinstance(data["confirmation_token"], str)
        assert len(data["confirmation_token"]) > 0
        assert "code" not in data

    async def test_always_self_confirms_with_code(self):
        """control_alarm passes confirmed=True, token, and code when code given."""
        from tools.security import control_alarm

        with patch(
            "tools.security.do",
            new_callable=AsyncMock,
            return_value="Done. Home Alarm: disarmed",
        ) as mock_do:
            result = await control_alarm(
                entity_id="alarm_control_panel.home",
                action="disarm",
                code="1234",
            )

        assert "CONFIRMATION REQUIRED" not in result
        assert "Done" in result

        mock_do.assert_called_once()
        call_args = mock_do.call_args
        assert call_args[0][0] == "alarm_control_panel"
        assert call_args[0][1] == "alarm_disarm"
        assert call_args[0][2] == {"entity_id": "alarm_control_panel.home"}
        data = call_args[0][3]
        assert data["confirmed"] is True
        assert data["code"] == "1234"
        assert "confirmation_token" in data
        assert isinstance(data["confirmation_token"], str)

    async def test_arm_away_self_confirms(self):
        """control_alarm(action='arm_away') self-confirms."""
        from tools.security import control_alarm

        with patch(
            "tools.security.do",
            new_callable=AsyncMock,
            return_value="Done. Away",
        ) as mock_do:
            result = await control_alarm(
                entity_id="alarm_control_panel.home",
                action="arm_away",
            )

        assert "CONFIRMATION REQUIRED" not in result
        call_args = mock_do.call_args
        assert call_args[0][1] == "alarm_arm_away"
        data = call_args[0][3]
        assert data["confirmed"] is True
        assert "confirmation_token" in data

    async def test_disarm_with_code(self):
        """control_alarm(action='disarm', code='5678') passes code and confirmation."""
        from tools.security import control_alarm

        with patch(
            "tools.security.do",
            new_callable=AsyncMock,
            return_value="Done.",
        ) as mock_do:
            await control_alarm(
                entity_id="alarm_control_panel.home",
                action="disarm",
                code="5678",
            )

        data = mock_do.call_args[0][3]
        assert data["confirmed"] is True
        assert data["code"] == "5678"
        assert "confirmation_token" in data

    async def test_unknown_action_returns_error(self):
        """control_alarm returns error for unknown action without calling do()."""
        from tools.security import control_alarm

        with patch(
            "tools.security.do",
            new_callable=AsyncMock,
        ) as mock_do:
            result = await control_alarm(
                entity_id="alarm_control_panel.home",
                action="explode",
            )

        assert "Unknown alarm action" in result
        mock_do.assert_not_called()

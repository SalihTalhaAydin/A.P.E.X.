"""Tests for smart_home tools (control_media power on/off, control_area, etc.)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    """Ensure all tools (including smart_home) are discovered."""
    discover_tools()


def test_control_media_has_turn_on_turn_off():
    """control_media supports turn_on and turn_off for TVs."""
    info = TOOL_REGISTRY.get("control_media")
    assert info is not None
    action_enum = info["parameters"]["properties"]["action"]["enum"]
    assert "turn_on" in action_enum
    assert "turn_off" in action_enum


# --------------------------------------------------
# control_area registration tests
# --------------------------------------------------


def test_control_area_registered():
    """control_area tool is present in the registry."""
    info = TOOL_REGISTRY.get("control_area")
    assert info is not None, "control_area not found in TOOL_REGISTRY"


def test_control_area_required_params():
    """control_area requires area_name and action."""
    info = TOOL_REGISTRY["control_area"]
    required = info["parameters"]["required"]
    assert "area_name" in required
    assert "action" in required


def test_control_area_action_enum():
    """control_area action must be one of on/off/toggle."""
    info = TOOL_REGISTRY["control_area"]
    enum = info["parameters"]["properties"]["action"]["enum"]
    assert set(enum) == {"on", "off", "toggle"}


def test_control_area_optional_params():
    """control_area has optional brightness_pct, color_temp_kelvin, domain."""
    info = TOOL_REGISTRY["control_area"]
    props = info["parameters"]["properties"]
    assert "brightness_pct" in props
    assert "color_temp_kelvin" in props
    assert "domain" in props
    # These must NOT be in required
    required = info["parameters"]["required"]
    assert "brightness_pct" not in required
    assert "color_temp_kelvin" not in required
    assert "domain" not in required


# --------------------------------------------------
# control_area functional tests (mocked ha_request)
# --------------------------------------------------

# Simulated area template response from HA
_AREA_TEMPLATE_RESPONSE = (
    "area_basement|Basement\n"
    "area_kitchen|Kitchen\n"
    "area_bedroom|Bedroom\n"
)


@pytest.mark.asyncio
async def test_control_area_resolves_area_and_calls_service():
    """control_area resolves area name to area_id and calls do()."""

    async def mock_template_request(method, path, json_data=None, **kwargs):
        return _AREA_TEMPLATE_RESPONSE

    with patch(
        "tools.smart_home.ha_request",
        side_effect=mock_template_request,
    ), patch(
        "tools.generic.ha_request", new_callable=AsyncMock,
        return_value=[],
    ) as mock_do_ha, patch(
        "tools.generic.verify_generic", new_callable=AsyncMock,
        return_value="Kitchen lights: on",
    ), patch(
        "tools.generic.asyncio.sleep", new_callable=AsyncMock,
    ):
        from tools.smart_home import control_area

        result = await control_area(
            area_name="kitchen",
            action="on",
            domain="light",
        )

    assert "kitchen" in result.lower() or "Kitchen" in result
    assert "done" in result.lower()
    # do() calls ha_request at least once (service call)
    assert mock_do_ha.await_count >= 1


@pytest.mark.asyncio
async def test_control_area_uses_area_id_not_entity_id():
    """The service call payload must contain area_id, not entity_id."""
    captured_payload = {}

    async def mock_template_request(method, path, json_data=None, **kwargs):
        return _AREA_TEMPLATE_RESPONSE

    async def mock_do_ha(method, path, json_data=None, **kwargs):
        captured_payload.update(json_data or {})
        return []

    with patch(
        "tools.smart_home.ha_request",
        side_effect=mock_template_request,
    ), patch(
        "tools.generic.ha_request",
        side_effect=mock_do_ha,
    ), patch(
        "tools.generic.verify_generic", new_callable=AsyncMock,
        return_value="Basement lights: on",
    ), patch(
        "tools.generic.asyncio.sleep", new_callable=AsyncMock,
    ):
        from tools.smart_home import control_area

        await control_area(
            area_name="basement",
            action="on",
            domain="light",
        )

    assert "area_id" in captured_payload, (
        "Service call must use area_id, not entity_id"
    )
    assert captured_payload["area_id"] == "area_basement"
    assert "entity_id" not in captured_payload


@pytest.mark.asyncio
async def test_control_area_passes_brightness_and_color_temp():
    """brightness_pct and color_temp_kelvin are forwarded in turn_on payload."""
    captured_payload = {}

    async def mock_template_request(method, path, json_data=None, **kwargs):
        return _AREA_TEMPLATE_RESPONSE

    async def mock_do_ha(method, path, json_data=None, **kwargs):
        captured_payload.update(json_data or {})
        return []

    with patch(
        "tools.smart_home.ha_request",
        side_effect=mock_template_request,
    ), patch(
        "tools.generic.ha_request",
        side_effect=mock_do_ha,
    ), patch(
        "tools.generic.verify_generic", new_callable=AsyncMock,
        return_value="Bedroom lights: on at 50%",
    ), patch(
        "tools.generic.asyncio.sleep", new_callable=AsyncMock,
    ):
        from tools.smart_home import control_area

        await control_area(
            area_name="bedroom",
            action="on",
            domain="light",
            brightness_pct=50,
            color_temp_kelvin=3000,
        )

    assert captured_payload.get("brightness_pct") == 50
    assert captured_payload.get("color_temp_kelvin") == 3000


@pytest.mark.asyncio
async def test_control_area_unknown_area_returns_error_with_known_areas():
    """Unknown area name returns a descriptive error listing known areas."""

    async def mock_ha_request(method, path, json_data=None, **kwargs):
        return _AREA_TEMPLATE_RESPONSE

    with patch(
        "tools.smart_home.ha_request",
        side_effect=mock_ha_request,
    ):
        from tools.smart_home import control_area

        result = await control_area(
            area_name="garage",
            action="off",
            domain="light",
        )

    # Must not say "Done"
    assert "done" not in result.lower()
    # Must mention the unknown area
    assert "garage" in result.lower()
    # Must list at least one known area
    assert any(
        name in result
        for name in ("Basement", "Kitchen", "Bedroom")
    ), f"Known areas not listed in error: {result!r}"


@pytest.mark.asyncio
async def test_control_area_case_insensitive_match():
    """Area name lookup is case-insensitive."""
    captured_payload = {}

    async def mock_template_request(method, path, json_data=None, **kwargs):
        return _AREA_TEMPLATE_RESPONSE

    async def mock_do_ha(method, path, json_data=None, **kwargs):
        captured_payload.update(json_data or {})
        return []

    with patch(
        "tools.smart_home.ha_request",
        side_effect=mock_template_request,
    ), patch(
        "tools.generic.ha_request",
        side_effect=mock_do_ha,
    ), patch(
        "tools.generic.verify_generic", new_callable=AsyncMock,
        return_value="Kitchen lights: off",
    ), patch(
        "tools.generic.asyncio.sleep", new_callable=AsyncMock,
    ):
        from tools.smart_home import control_area

        result = await control_area(
            area_name="KITCHEN",
            action="off",
            domain="light",
        )

    # Must have matched and called service (area_id present)
    assert captured_payload.get("area_id") == "area_kitchen"
    assert "done" in result.lower()


@pytest.mark.asyncio
async def test_control_area_turn_off_omits_brightness():
    """When action='off', brightness_pct is NOT sent even if provided."""
    captured_payload = {}

    async def mock_template_request(method, path, json_data=None, **kwargs):
        return _AREA_TEMPLATE_RESPONSE

    async def mock_do_ha(method, path, json_data=None, **kwargs):
        captured_payload.update(json_data or {})
        return []

    with patch(
        "tools.smart_home.ha_request",
        side_effect=mock_template_request,
    ), patch(
        "tools.generic.ha_request",
        side_effect=mock_do_ha,
    ), patch(
        "tools.generic.verify_generic", new_callable=AsyncMock,
        return_value="Kitchen lights: off",
    ), patch(
        "tools.generic.asyncio.sleep", new_callable=AsyncMock,
    ):
        from tools.smart_home import control_area

        # Providing brightness_pct with action='off' — should be ignored
        await control_area(
            area_name="kitchen",
            action="off",
            domain="light",
            brightness_pct=80,
        )

    # brightness_pct must NOT appear in turn_off payload
    assert "brightness_pct" not in captured_payload


@pytest.mark.asyncio
async def test_control_area_empty_template_response():
    """If HA returns empty area list, return a sensible error."""

    async def mock_ha_request(method, path, json_data=None, **kwargs):
        return ""  # No areas

    with patch(
        "tools.smart_home.ha_request",
        side_effect=mock_ha_request,
    ):
        from tools.smart_home import control_area

        result = await control_area(
            area_name="kitchen",
            action="on",
        )

    assert "done" not in result.lower()
    assert "kitchen" in result.lower()

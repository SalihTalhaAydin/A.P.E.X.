"""Tests for get_device_summary() in tools.ha_helpers.

Covers:
- Existing domains (vacuum, notify, todo) are still included
- New domains (light, climate, media_player, lock, cover) are included
- Light entities are capped at 15 when more than 15 are present
- Domains with no entities produce no section in the output
"""

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(entity_id: str, state: str = "on", friendly: str | None = None) -> dict:
    """Return a minimal HA state dict."""
    attrs = {}
    if friendly is not None:
        attrs["friendly_name"] = friendly
    return {"entity_id": entity_id, "state": state, "attributes": attrs}


def _build_states(*groups) -> list[dict]:
    """Concatenate multiple lists of state dicts."""
    result: list[dict] = []
    for group in groups:
        result.extend(group)
    return result


# ---------------------------------------------------------------------------
# Tests — existing domains (regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_summary_includes_vacuum():
    """vacuum entities still appear in the output."""
    from tools.ha_helpers import get_device_summary

    states = [_make_state("vacuum.dusty", "docked", "Dusty")]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "vacuum.dusty" in result
    assert "Dusty" in result
    assert "docked" in result


@pytest.mark.asyncio
async def test_get_device_summary_includes_notify():
    """notify entities still appear in the output."""
    from tools.ha_helpers import get_device_summary

    states = [_make_state("notify.mobile_app_phone", "unknown", "Phone")]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "notify.mobile_app_phone" in result


@pytest.mark.asyncio
async def test_get_device_summary_includes_todo():
    """todo entities still appear in the output."""
    from tools.ha_helpers import get_device_summary

    states = [_make_state("todo.shopping_list", "0", "Shopping List")]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "todo.shopping_list" in result


# ---------------------------------------------------------------------------
# Tests — new domains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_summary_includes_light():
    """light entities appear in the output when present."""
    from tools.ha_helpers import get_device_summary

    states = [
        _make_state("light.living_room", "on", "Living Room Light"),
        _make_state("light.bedroom", "off", "Bedroom Light"),
    ]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "light.living_room" in result
    assert "light.bedroom" in result
    assert "Living Room Light" in result


@pytest.mark.asyncio
async def test_get_device_summary_caps_light_at_15():
    """When more than 15 light entities exist, only 15 appear in the output
    and the header shows the cap notation."""
    from tools.ha_helpers import get_device_summary

    # Build 20 light entities
    states = [
        _make_state(f"light.room_{i}", "on", f"Room {i} Light")
        for i in range(20)
    ]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    # Count how many light entity_ids appear in output
    light_lines = [
        line for line in result.splitlines()
        if "light.room_" in line
    ]
    assert len(light_lines) == 15, (
        f"Expected 15 light lines, got {len(light_lines)}"
    )

    # Header must indicate the cap
    assert "15 of 20" in result


@pytest.mark.asyncio
async def test_get_device_summary_includes_climate():
    """climate entities appear in the output."""
    from tools.ha_helpers import get_device_summary

    states = [
        _make_state("climate.living_room", "heat", "Living Room Thermostat"),
    ]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "climate.living_room" in result
    assert "Living Room Thermostat" in result
    assert "heat" in result


@pytest.mark.asyncio
async def test_get_device_summary_includes_media_player():
    """media_player entities appear in the output."""
    from tools.ha_helpers import get_device_summary

    states = [
        _make_state("media_player.living_room_tv", "playing", "Living Room TV"),
    ]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "media_player.living_room_tv" in result
    assert "Living Room TV" in result
    assert "playing" in result


@pytest.mark.asyncio
async def test_get_device_summary_includes_lock():
    """lock entities appear in the output."""
    from tools.ha_helpers import get_device_summary

    states = [
        _make_state("lock.front_door", "locked", "Front Door"),
    ]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "lock.front_door" in result
    assert "locked" in result


@pytest.mark.asyncio
async def test_get_device_summary_includes_cover():
    """cover entities appear in the output."""
    from tools.ha_helpers import get_device_summary

    states = [
        _make_state("cover.garage_door", "closed", "Garage Door"),
    ]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "cover.garage_door" in result
    assert "closed" in result


# ---------------------------------------------------------------------------
# Tests — mixed state (all domains at once)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_summary_mixed_domains():
    """All domains co-exist correctly in a single summary."""
    from tools.ha_helpers import get_device_summary

    states = _build_states(
        [_make_state("vacuum.dusty", "docked", "Dusty")],
        [_make_state("notify.mobile_app", "unknown")],
        [_make_state("todo.groceries", "0", "Groceries")],
        [_make_state("light.kitchen", "on", "Kitchen Light")],
        [_make_state("climate.office", "cool", "Office AC")],
        [_make_state("media_player.sonos", "idle", "Sonos")],
        [_make_state("lock.back_door", "unlocked", "Back Door")],
        [_make_state("cover.blinds", "open", "Window Blinds")],
    )

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    assert "vacuum.dusty" in result
    assert "notify.mobile_app" in result
    assert "todo.groceries" in result
    assert "light.kitchen" in result
    assert "climate.office" in result
    assert "media_player.sonos" in result
    assert "lock.back_door" in result
    assert "cover.blinds" in result


# ---------------------------------------------------------------------------
# Tests — empty domain produces no section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_summary_skips_empty_domains():
    """Domains with no entities produce no output section."""
    from tools.ha_helpers import get_device_summary

    # Only a vacuum entity; all other domains are absent
    states = [_make_state("vacuum.dusty", "docked", "Dusty")]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    # Confirmed absent domains must not appear
    assert "light." not in result
    assert "climate." not in result
    assert "media_player." not in result
    assert "lock." not in result
    assert "cover." not in result


# ---------------------------------------------------------------------------
# Tests — light cap header NOT shown when <= 15 lights
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_summary_light_no_cap_header_when_under_limit():
    """When <= 15 lights exist, the header does NOT show a cap notation."""
    from tools.ha_helpers import get_device_summary

    states = [
        _make_state(f"light.room_{i}", "on") for i in range(10)
    ]

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        return_value=states,
    ):
        result = await get_device_summary()

    # All 10 should appear
    light_lines = [l for l in result.splitlines() if "light.room_" in l]
    assert len(light_lines) == 10

    # No "X of Y" style cap notation
    assert "of 10" not in result


# ---------------------------------------------------------------------------
# Tests — ha_request failure returns empty string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_device_summary_returns_empty_on_error():
    """get_device_summary returns '' when HA is unreachable."""
    from tools.ha_helpers import get_device_summary

    with patch(
        "tools.ha_helpers.ha_request",
        new_callable=AsyncMock,
        side_effect=Exception("connection refused"),
    ):
        result = await get_device_summary()

    assert result == ""

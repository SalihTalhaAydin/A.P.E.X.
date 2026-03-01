"""Tests for routines tool."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from tools.base import TOOL_REGISTRY
from tools.routines import define_routine, run_routine, set_routine_store


@pytest.fixture(scope="module")
def _tools_loaded():
    from tools import discover_tools

    discover_tools()


@pytest.mark.usefixtures("_tools_loaded")
def test_define_routine_registered():
    """define_routine is in the registry."""
    info = TOOL_REGISTRY.get("define_routine")
    assert info is not None
    req = info["parameters"]["required"]
    assert "name" in req
    assert "steps" in req


@pytest.mark.usefixtures("_tools_loaded")
def test_define_routine_has_trigger():
    """define_routine has optional trigger."""
    info = TOOL_REGISTRY["define_routine"]
    props = info["parameters"]["properties"]
    assert "trigger" in props
    req = info["parameters"]["required"]
    assert "trigger" not in req


@pytest.mark.usefixtures("_tools_loaded")
def test_list_routines_registered():
    """list_routines is in the registry."""
    info = TOOL_REGISTRY.get("list_routines")
    assert info is not None


@pytest.mark.usefixtures("_tools_loaded")
def test_run_routine_registered():
    """run_routine requires name."""
    info = TOOL_REGISTRY.get("run_routine")
    assert info is not None
    req = info["parameters"]["required"]
    assert "name" in req


@pytest.mark.usefixtures("_tools_loaded")
def test_delete_routine_registered():
    """delete_routine requires name."""
    info = TOOL_REGISTRY.get("delete_routine")
    assert info is not None
    req = info["parameters"]["required"]
    assert "name" in req


# define_routine step parsing and run_routine (mocked _routine_store)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_define_routine_parses_steps_by_period_space_not_period():
    """define_routine splits on '. ' (period-space), not '.', preserving decimals like 3.14."""
    mock_store = MagicMock()
    mock_store.get_routine = AsyncMock(return_value=None)
    mock_store.save_routine = AsyncMock()
    set_routine_store(mock_store)

    result = await define_routine(
        name="precision",
        steps="Set temperature to 3.14 degrees. Next step here.",
    )

    mock_store.save_routine.assert_called_once()
    step_list = mock_store.save_routine.call_args[0][1]
    assert len(step_list) == 2
    assert "3.14" in step_list[0], (
        "Decimal 3.14 must not be split by '.' alone"
    )
    assert step_list[0] == "Set temperature to 3.14 degrees"
    assert step_list[1] == "Next step here"
    assert "2 steps" in result


@pytest.mark.asyncio
async def test_define_routine_parses_steps_by_period_and_newline():
    """define_routine splits steps on '. ' and newlines, preserving numbers like 72.5."""
    mock_store = MagicMock()
    mock_store.get_routine = AsyncMock(return_value=None)
    mock_store.save_routine = AsyncMock()
    set_routine_store(mock_store)

    result = await define_routine(
        name="morning",
        steps="Turn on kitchen lights to 80%. Set thermostat to 72.5. Get the weather.\nRead today calendar.",
    )

    mock_store.save_routine.assert_called_once()
    call_args = mock_store.save_routine.call_args
    step_list = call_args[0][1]
    assert len(step_list) == 4
    assert "80%" in step_list[0]
    assert "72.5" in step_list[1]
    assert "weather" in step_list[2]
    assert "calendar" in step_list[3]
    assert "4 steps" in result


@pytest.mark.asyncio
async def test_define_routine_rejects_when_name_exists():
    """define_routine returns message when routine with same name already exists."""
    mock_store = MagicMock()
    mock_store.get_routine = AsyncMock(
        return_value={
            "name": "bedtime",
            "steps": ["Dim lights", "Set temp"],
            "use_count": 3,
        }
    )
    set_routine_store(mock_store)

    result = await define_routine(name="bedtime", steps="New step.")

    mock_store.save_routine.assert_not_called()
    assert "already exists" in result
    assert "bedtime" in result


@pytest.mark.asyncio
async def test_run_routine_returns_steps_when_exists():
    """run_routine returns formatted steps and prompts execution."""
    mock_store = MagicMock()
    mock_store.get_routine = AsyncMock(
        return_value={
            "name": "good morning",
            "steps": ["Turn on lights", "Get weather", "Read calendar"],
            "use_count": 5,
        }
    )
    mock_store.record_usage = AsyncMock()
    set_routine_store(mock_store)

    result = await run_routine(name="good morning")

    mock_store.record_usage.assert_called_once_with("good morning")
    assert "good morning" in result
    assert "6 times" in result
    assert "1. Turn on lights" in result
    assert "2. Get weather" in result
    assert "3. Read calendar" in result
    assert "Execute each step" in result


@pytest.mark.asyncio
async def test_run_routine_returns_error_when_not_found():
    """run_routine returns available names when routine does not exist."""
    mock_store = MagicMock()
    mock_store.get_routine = AsyncMock(return_value=None)
    mock_store.list_routines = AsyncMock(
        return_value=[
            {"name": "morning", "steps": [], "use_count": 0},
        ]
    )
    set_routine_store(mock_store)

    result = await run_routine(name="nonexistent")

    assert "No routine named" in result
    assert "nonexistent" in result
    assert "morning" in result or "Available" in result

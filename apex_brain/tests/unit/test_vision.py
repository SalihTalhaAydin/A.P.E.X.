"""Tests for vision tool — camera snapshot + AI analysis."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


# ---------------------------------------------------
# Registration test
# ---------------------------------------------------


def test_see_registered():
    """see is registered in TOOL_REGISTRY with correct name."""
    info = TOOL_REGISTRY.get("see")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "camera_entity_id" in props
    assert "question" in props
    assert "camera_entity_id" in info["parameters"]["required"]


# ---------------------------------------------------
# Camera state / availability tests
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_camera_state_error_returns_error_message():
    """read_state returns a dict with 'error' key → error message."""
    from tools.vision import see

    with patch(
        "tools.vision.read_state",
        new_callable=AsyncMock,
        return_value={"error": "Entity not found"},
    ):
        result = await see(camera_entity_id="camera.front_door")

    assert result == "Camera error: Entity not found"


@pytest.mark.asyncio
async def test_camera_unavailable_returns_unavailable_message():
    """Camera with state 'unavailable' returns friendly name + unavailable."""
    from tools.vision import see

    with patch(
        "tools.vision.read_state",
        new_callable=AsyncMock,
        return_value={
            "state": "unavailable",
            "attributes": {"friendly_name": "Front Door"},
        },
    ):
        result = await see(camera_entity_id="camera.front_door")

    assert result == "Front Door is unavailable."


@pytest.mark.asyncio
async def test_camera_unavailable_falls_back_to_entity_id():
    """Camera unavailable with no friendly_name falls back to entity_id."""
    from tools.vision import see

    with patch(
        "tools.vision.read_state",
        new_callable=AsyncMock,
        return_value={
            "state": "unavailable",
            "attributes": {},
        },
    ):
        result = await see(camera_entity_id="camera.front_door")

    assert result == "camera.front_door is unavailable."


@pytest.mark.asyncio
async def test_read_state_exception_returns_error_message():
    """read_state raising an exception → error message."""
    from tools.vision import see

    with patch(
        "tools.vision.read_state",
        new_callable=AsyncMock,
        side_effect=Exception("connection refused"),
    ):
        result = await see(camera_entity_id="camera.front_door")

    assert result == "Error accessing camera: connection refused"


# ---------------------------------------------------
# Snapshot fetch tests
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_http_error_fetching_snapshot():
    """Non-success HTTP status when fetching camera proxy → error message."""
    from tools.vision import see

    mock_state = {
        "state": "idle",
        "attributes": {"friendly_name": "Front Door"},
    }

    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 502

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.ha_api_url = "http://ha.local:8123/api"
    mock_settings.ha_headers = {"Authorization": "Bearer fake"}

    with (
        patch(
            "tools.vision.read_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "tools.vision.get_ha_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch(
            "tools.vision.settings",
            mock_settings,
        ),
    ):
        result = await see(camera_entity_id="camera.front_door")

    assert result == "Error fetching snapshot: HTTP 502"


@pytest.mark.asyncio
async def test_snapshot_fetch_exception():
    """Exception during snapshot fetch → error message."""
    from tools.vision import see

    mock_state = {
        "state": "idle",
        "attributes": {"friendly_name": "Front Door"},
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))

    mock_settings = MagicMock()
    mock_settings.ha_api_url = "http://ha.local:8123/api"
    mock_settings.ha_headers = {"Authorization": "Bearer fake"}

    with (
        patch(
            "tools.vision.read_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "tools.vision.get_ha_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch(
            "tools.vision.settings",
            mock_settings,
        ),
    ):
        result = await see(camera_entity_id="camera.front_door")

    assert result == "Error fetching camera snapshot: timeout"


# ---------------------------------------------------
# Successful vision analysis tests
# ---------------------------------------------------


def _make_successful_mocks(
    *, question: str = "", content_type: str = "image/jpeg"
):
    """Build common mocks for a successful snapshot fetch + LLM call."""
    mock_state = {
        "state": "idle",
        "attributes": {"friendly_name": "Front Door"},
    }

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.content = b"\x89PNG\r\n\x1a\nfakeimage"
    mock_response.headers = {"content-type": content_type}
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.ha_api_url = "http://ha.local:8123/api"
    mock_settings.ha_headers = {"Authorization": "Bearer fake"}
    mock_settings.litellm_model = "gpt-4o"

    return mock_state, mock_client, mock_settings


@pytest.mark.asyncio
async def test_successful_vision_analysis():
    """Successful end-to-end: returns '[FriendlyName] description'."""
    from tools.vision import see

    mock_state, mock_client, mock_settings = _make_successful_mocks()

    # Build a mock LLM result
    mock_message = MagicMock()
    mock_message.content = "A person standing at the front door."
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_llm_result = MagicMock()
    mock_llm_result.choices = [mock_choice]

    with (
        patch(
            "tools.vision.read_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "tools.vision.get_ha_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch(
            "tools.vision.settings",
            mock_settings,
        ),
        patch(
            "tools.vision.litellm",
        ) as mock_litellm,
    ):
        mock_litellm.acompletion = AsyncMock(return_value=mock_llm_result)
        result = await see(camera_entity_id="camera.front_door")

    assert result == "[Front Door] A person standing at the front door."


@pytest.mark.asyncio
async def test_custom_question_used_as_prompt():
    """Custom question is sent to the LLM instead of the default prompt."""
    from tools.vision import see

    mock_state, mock_client, mock_settings = _make_successful_mocks()

    mock_message = MagicMock()
    mock_message.content = "Yes, there is a package on the porch."
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_llm_result = MagicMock()
    mock_llm_result.choices = [mock_choice]

    with (
        patch(
            "tools.vision.read_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "tools.vision.get_ha_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch(
            "tools.vision.settings",
            mock_settings,
        ),
        patch(
            "tools.vision.litellm",
        ) as mock_litellm,
    ):
        mock_litellm.acompletion = AsyncMock(return_value=mock_llm_result)
        result = await see(
            camera_entity_id="camera.front_door",
            question="Is there a package on the porch?",
        )

    # Verify the custom question was sent (not the default)
    call_args = mock_litellm.acompletion.call_args
    messages = call_args.kwargs["messages"]
    text_part = messages[0]["content"][1]
    assert text_part["text"] == "Is there a package on the porch?"
    assert "Describe what you see" not in text_part["text"]

    assert "[Front Door]" in result


@pytest.mark.asyncio
async def test_default_prompt_when_no_question():
    """Default description prompt is used when question is empty."""
    from tools.vision import see

    mock_state, mock_client, mock_settings = _make_successful_mocks()

    mock_message = MagicMock()
    mock_message.content = "An empty driveway."
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_llm_result = MagicMock()
    mock_llm_result.choices = [mock_choice]

    with (
        patch(
            "tools.vision.read_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "tools.vision.get_ha_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch(
            "tools.vision.settings",
            mock_settings,
        ),
        patch(
            "tools.vision.litellm",
        ) as mock_litellm,
    ):
        mock_litellm.acompletion = AsyncMock(return_value=mock_llm_result)
        result = await see(camera_entity_id="camera.front_door")

    call_args = mock_litellm.acompletion.call_args
    messages = call_args.kwargs["messages"]
    text_part = messages[0]["content"][1]
    assert (
        text_part["text"] == "Describe what you see in this camera image."
    )


# ---------------------------------------------------
# LLM failure / edge-case tests
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_llm_no_choices_returns_no_response():
    """LLM returns empty choices → 'Vision analysis returned no response.'"""
    from tools.vision import see

    mock_state, mock_client, mock_settings = _make_successful_mocks()

    mock_llm_result = MagicMock()
    mock_llm_result.choices = []

    with (
        patch(
            "tools.vision.read_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "tools.vision.get_ha_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch(
            "tools.vision.settings",
            mock_settings,
        ),
        patch(
            "tools.vision.litellm",
        ) as mock_litellm,
    ):
        mock_litellm.acompletion = AsyncMock(return_value=mock_llm_result)
        result = await see(camera_entity_id="camera.front_door")

    assert result == "Vision analysis returned no response."


@pytest.mark.asyncio
async def test_llm_exception_returns_error():
    """LLM acompletion raises exception → error message."""
    from tools.vision import see

    mock_state, mock_client, mock_settings = _make_successful_mocks()

    with (
        patch(
            "tools.vision.read_state",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "tools.vision.get_ha_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
        patch(
            "tools.vision.settings",
            mock_settings,
        ),
        patch(
            "tools.vision.litellm",
        ) as mock_litellm,
    ):
        mock_litellm.acompletion = AsyncMock(
            side_effect=Exception("rate limit exceeded")
        )
        result = await see(camera_entity_id="camera.front_door")

    assert result == "Vision analysis error: rate limit exceeded"

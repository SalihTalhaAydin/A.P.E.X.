"""Tests for brain.server FastAPI app."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from brain.config import settings
from brain.event_handler import WebhookResponse
from brain.server import (
    ChatRequest,
    _close_stores_if_present,
    _embed_text,
    app,
)
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI TestClient. Lifespan runs; DB and HA use test env from conftest."""
    with TestClient(app) as c:
        yield c


def test_chat_request_message_max_length_valid():
    """BUG-21: ChatRequest accepts messages up to 50,000 chars."""
    req = ChatRequest(message="x" * 50_000, session_id="test")
    assert len(req.message) == 50_000


def test_chat_request_message_max_length_rejected():
    """BUG-21: ChatRequest rejects messages over 50,000 chars."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        ChatRequest(message="x" * 50_001, session_id="test")
    errs = exc_info.value.errors()
    assert any(e.get("loc") == ("message",) for e in errs)


def test_health_returns_200(client):
    """GET /health returns 200 and status online."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "model" in data
    assert "ha_reachable" in data


def test_debug_ha_returns_ha_reachable(client):
    """GET /api/debug/ha returns ha_reachable and ha_url."""
    response = client.get("/api/debug/ha")
    assert response.status_code == 200
    data = response.json()
    assert "ha_reachable" in data
    assert "ha_url" in data


@pytest.mark.asyncio
async def test_shutdown_with_none_stores_does_not_crash():
    """BUG-5: Shutdown must not crash when stores are None (startup failed partway)."""
    await _close_stores_if_present(
        None, None, None, None
    )  # no AttributeError


@pytest.mark.asyncio
async def test_shutdown_with_partial_none_stores():
    """BUG-5: Shutdown works when only some stores are None (partial startup failure)."""
    mock_store = AsyncMock()
    # Only shared_db initialized, others are None
    await _close_stores_if_present(mock_store, None, None, None)
    mock_store.close.assert_awaited_once()

    mock_store.reset_mock()
    # Only routine_store initialized, others are None
    await _close_stores_if_present(None, mock_store, None, None)
    mock_store.close.assert_awaited_once()

    mock_store.reset_mock()
    # Only convo_store initialized, others are None
    await _close_stores_if_present(None, None, mock_store, None)
    mock_store.close.assert_awaited_once()

    mock_store.reset_mock()
    # Only knowledge_store initialized, others are None
    await _close_stores_if_present(None, None, None, mock_store)
    mock_store.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_with_all_stores_present():
    """BUG-5: Shutdown closes all stores when all are present."""
    shared_db = AsyncMock()
    routine = AsyncMock()
    convo = AsyncMock()
    knowledge = AsyncMock()
    await _close_stores_if_present(shared_db, routine, convo, knowledge)
    routine.close.assert_awaited_once()
    convo.close.assert_awaited_once()
    knowledge.close.assert_awaited_once()
    shared_db.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_embed_text_empty_data_returns_none_no_crash():
    """BUG-94: litellm.aembedding returning empty data causes IndexError.
    Verify _embed_text returns None and does not crash."""
    mock_response = MagicMock()
    mock_response.data = []

    with patch(
        "brain.server.litellm.aembedding", new_callable=AsyncMock
    ) as mock_aembed:
        mock_aembed.return_value = mock_response
        result = await _embed_text("sample text for embedding")
        assert result is None


# ---------------------------------------------------------
# BUG-16, BUG-134: Server endpoint tests
# /v1/chat/completions (main), /api/chat, /api/webhook, rate limiting
# ---------------------------------------------------------


# ---------------------------------------------------------
# Endpoint routing & validation (minimal requests, mocked deps)
# ---------------------------------------------------------


def test_post_v1_chat_completions_accepts_minimal_returns_json(client):
    """POST /v1/chat/completions accepts minimal valid request and returns JSON."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Hi")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith(
        "application/json"
    )
    data = response.json()
    assert "choices" in data
    assert data["choices"][0]["message"]["content"] == "Hi"
    mock_conv.handle.assert_called_once_with(
        "Hello", "default", voice_mode=True,
    )


def test_post_api_chat_accepts_chat_request_returns_response(client):
    """POST /api/chat accepts ChatRequest and returns response."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Pong")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/api/chat",
            json={"message": "ping", "session_id": "my-session"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Pong"
    assert data["session_id"] == "my-session"
    mock_conv.handle.assert_called_once_with("ping", "my-session")


def test_post_api_webhook_accepts_payload_returns_result(client):
    """POST /api/webhook accepts webhook payload and returns result."""
    mock_handler = MagicMock()
    mock_handler.process_event = AsyncMock(
        return_value=WebhookResponse(status="processed", message="OK")
    )
    with patch("brain.server.event_handler", mock_handler):
        with patch.object(settings, "webhook_enabled", True):
            with patch.object(settings, "webhook_secret", ""):
                response = client.post(
                    "/api/webhook",
                    json={
                        "event_type": "motion",
                        "entity_id": "binary_sensor.hallway",
                        "new_state": "on",
                    },
                )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    mock_handler.process_event.assert_called_once()
    call_arg = mock_handler.process_event.call_args[0][0]
    assert call_arg.event_type == "motion"
    assert call_arg.entity_id == "binary_sensor.hallway"
    assert call_arg.new_state == "on"


def test_api_chat_503_when_not_ready(client):
    """POST /api/chat returns 503 when conversation is None."""
    with patch("brain.server.conversation", None):
        response = client.post(
            "/api/chat",
            json={"message": "hello", "session_id": "test"},
        )
    assert response.status_code == 503
    assert response.json() == {"error": "Not ready"}


def test_api_chat_200_with_mocked_response(client):
    """POST /api/chat returns 200 with mocked conversation.handle response."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Mocked reply from AI")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/api/chat",
            json={"message": "hello", "session_id": "s1"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Mocked reply from AI"
    assert data["session_id"] == "s1"


def test_api_chat_validation_missing_message(client):
    """POST /api/chat returns 422 when message is missing."""
    response = client.post(
        "/api/chat",
        json={"session_id": "test"},
    )
    assert response.status_code == 422


def test_api_chat_validation_invalid_json(client):
    """POST /api/chat returns 422 for invalid JSON (FastAPI/Pydantic validation)."""
    response = client.post(
        "/api/chat",
        data="not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_api_webhook_503_when_not_ready(client):
    """POST /api/webhook returns 503 when event_handler is None."""
    with patch("brain.server.event_handler", None):
        with patch.object(settings, "webhook_enabled", True):
            response = client.post(
                "/api/webhook",
                json={
                    "event_type": "motion",
                    "entity_id": "binary_sensor.hallway",
                    "new_state": "on",
                },
            )
    assert response.status_code == 503
    assert response.json() == {"error": "Not ready"}


def test_api_webhook_200_with_mocked_response(client):
    """POST /api/webhook returns 200 with mocked event_handler.process_event."""
    mock_handler = MagicMock()
    mock_handler.process_event = AsyncMock(
        return_value=WebhookResponse(
            status="processed",
            message="Handled",
            actions_taken=["Turned on light"],
        )
    )
    with patch("brain.server.event_handler", mock_handler):
        with patch.object(settings, "webhook_enabled", True):
            with patch.object(settings, "webhook_secret", ""):
                response = client.post(
                    "/api/webhook",
                    json={
                        "event_type": "motion",
                        "entity_id": "binary_sensor.hallway",
                        "new_state": "on",
                    },
                )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["message"] == "Handled"
    assert data["actions_taken"] == ["Turned on light"]


def test_api_webhook_validation_missing_event_type(client):
    """POST /api/webhook returns 422 when event_type is missing."""
    with patch.object(settings, "webhook_enabled", True):
        response = client.post(
            "/api/webhook",
            json={"entity_id": "binary_sensor.hallway", "new_state": "on"},
        )
    assert response.status_code == 422


def test_api_webhook_validation_invalid_json(client):
    """POST /api/webhook returns 422 for invalid JSON."""
    response = client.post(
        "/api/webhook",
        data="not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_v1_chat_completions_503_when_not_ready(client):
    """POST /v1/chat/completions returns 503 when conversation is None."""
    with patch("brain.server.conversation", None):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    assert response.status_code == 503
    assert response.json() == {"error": "Not ready"}


def test_v1_chat_completions_200_with_mocked_response(client):
    """POST /v1/chat/completions returns 200 with OpenAI-style response."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="OpenAI-style reply")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "OpenAI-style reply"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["finish_reason"] == "stop"


def test_v1_chat_completions_400_invalid_json(client):
    """POST /v1/chat/completions returns 400 for invalid JSON."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="x")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            data="not valid json",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid JSON in request body"}


def test_v1_chat_completions_400_no_user_message(client):
    """POST /v1/chat/completions returns 400 when no user message found."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="x")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "system", "content": "You are a bot"}
                ],
            },
        )
    assert response.status_code == 400
    assert response.json() == {"error": "No user message found"}


def test_api_chat_504_on_timeout(client):
    """POST /api/chat returns 504 when conversation.handle times out."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(side_effect=TimeoutError())
    with patch("brain.server.conversation", mock_conv):
        with patch(
            "brain.server.asyncio.wait_for", new_callable=AsyncMock
        ) as m:
            m.side_effect = TimeoutError()
            response = client.post(
                "/api/chat",
                json={"message": "hello", "session_id": "test"},
            )
    assert response.status_code == 504
    assert response.json() == {"error": "Request timed out"}


def test_api_webhook_ignored_when_disabled(client):
    """POST /api/webhook returns ignored when webhooks disabled."""
    with patch.object(settings, "webhook_enabled", False):
        response = client.post(
            "/api/webhook",
            json={
                "event_type": "motion",
                "entity_id": "binary_sensor.hallway",
                "new_state": "on",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
    assert "disabled" in data["message"].lower()


def test_api_webhook_403_invalid_secret(client):
    """POST /api/webhook returns 403 when secret does not match."""
    mock_handler = MagicMock()
    mock_handler.process_event = AsyncMock(
        return_value=WebhookResponse(status="processed", message="Handled")
    )
    with patch("brain.server.event_handler", mock_handler):
        with patch.object(settings, "webhook_enabled", True):
            with patch.object(
                settings, "webhook_secret", "correct_secret"
            ):
                response = client.post(
                    "/api/webhook",
                    json={
                        "event_type": "motion",
                        "entity_id": "binary_sensor.hallway",
                        "new_state": "on",
                        "attributes": {"secret": "wrong_secret"},
                    },
                )
    assert response.status_code == 403
    assert response.json() == {"error": "Invalid secret"}
    mock_handler.process_event.assert_not_called()


def test_api_webhook_200_with_valid_secret(client):
    """POST /api/webhook accepts request when secret matches."""
    mock_handler = MagicMock()
    mock_handler.process_event = AsyncMock(
        return_value=WebhookResponse(status="processed", message="OK")
    )
    with patch("brain.server.event_handler", mock_handler):
        with patch.object(settings, "webhook_enabled", True):
            with patch.object(settings, "webhook_secret", "my_secret"):
                response = client.post(
                    "/api/webhook",
                    json={
                        "event_type": "motion",
                        "entity_id": "binary_sensor.hallway",
                        "new_state": "on",
                        "attributes": {"secret": "my_secret"},
                    },
                )
    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    mock_handler.process_event.assert_called_once()


def test_v1_chat_completions_504_on_timeout(client):
    """POST /v1/chat/completions returns 504 when conversation.handle times out."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(side_effect=TimeoutError())
    with patch("brain.server.conversation", mock_conv):
        with patch(
            "brain.server.asyncio.wait_for", new_callable=AsyncMock
        ) as m:
            m.side_effect = TimeoutError()
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
    assert response.status_code == 504
    assert response.json() == {"error": "Request timed out"}


def test_v1_chat_completions_multimodal_content(client):
    """POST /v1/chat/completions extracts user message from multimodal content."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Reply to image")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "What's in this image?",
                            },
                            {
                                "type": "image_url",
                                "url": "https://example.com/img.png",
                            },
                        ],
                    }
                ],
            },
        )
    assert response.status_code == 200
    assert (
        response.json()["choices"][0]["message"]["content"]
        == "Reply to image"
    )
    mock_conv.handle.assert_called_once_with(
        "What's in this image?", "default", voice_mode=True,
    )


def test_v1_chat_completions_session_id_from_header(client):
    """POST /v1/chat/completions uses x-session-id header for session."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Session-specific reply")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hi"}],
            },
            headers={"x-session-id": "custom-session-123"},
        )
    assert response.status_code == 200
    mock_conv.handle.assert_called_once_with(
        "Hi", "custom-session-123", voice_mode=True,
    )


def test_v1_chat_completions_session_id_sanitized(client):
    """POST /v1/chat/completions sanitizes session_id (strips invalid chars)."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="OK")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hi"}],
                "user": "session/with/slashes!!",
            },
        )
    assert response.status_code == 200
    # Sanitization: [^a-zA-Z0-9_-] stripped, result is "sessionwithslashes"
    mock_conv.handle.assert_called_once()
    call_args = mock_conv.handle.call_args[0]
    assert call_args[1] == "sessionwithslashes"


def test_v1_chat_completions_response_structure(client):
    """POST /v1/chat/completions returns full OpenAI-style structure."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Hello back")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["id"].startswith("chatcmpl-")
    assert data["object"] == "chat.completion"
    assert "created" in data
    assert data["model"] is not None
    assert "choices" in data
    assert len(data["choices"]) == 1
    assert data["choices"][0]["finish_reason"] == "stop"
    assert "usage" in data
    assert data["usage"]["total_tokens"] == 0


# ---------------------------------------------------------
# Minimal smoke tests (mocked deps, no full startup required)
# ---------------------------------------------------------


def test_post_v1_chat_completions_minimal(client):
    """POST /v1/chat/completions accepts valid request and returns completion."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Hi there!")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "Hi there!"


def test_post_api_chat_minimal(client):
    """POST /api/chat accepts valid request and returns response."""
    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="Test reply")
    with patch("brain.server.conversation", mock_conv):
        response = client.post(
            "/api/chat",
            json={"message": "ping", "session_id": "test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Test reply"
    assert data["session_id"] == "test"


def test_post_api_webhook_minimal(client):
    """POST /api/webhook processes event and returns result."""
    mock_handler = MagicMock()
    mock_handler.process_event = AsyncMock(
        return_value=WebhookResponse(status="processed", message="OK")
    )
    with patch("brain.server.event_handler", mock_handler):
        with patch.object(settings, "webhook_enabled", True):
            with patch.object(settings, "webhook_secret", ""):
                response = client.post(
                    "/api/webhook",
                    json={
                        "event_type": "motion",
                        "entity_id": "binary_sensor.hallway",
                        "new_state": "on",
                    },
                )
    assert response.status_code == 200
    assert response.json()["status"] == "processed"


# ---------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------


def test_rate_limit_api_chat_returns_429(client):
    """Repeated requests to /api/chat get rate-limited (429) after limit."""
    from brain.server import RateLimiter

    mock_conv = MagicMock()
    mock_conv.handle = AsyncMock(return_value="ok")
    # Use fresh limiter so we don't affect other tests
    fresh_limiter = RateLimiter()
    with patch("brain.server.conversation", mock_conv):
        with patch("brain.server.rate_limiter", fresh_limiter):
            # Limit is 30/min for /api/chat
            for i in range(30):
                r = client.post(
                    "/api/chat",
                    json={"message": "hi", "session_id": "s"},
                )
                assert r.status_code == 200, (
                    f"Request {i + 1} should succeed"
                )
            r = client.post(
                "/api/chat",
                json={"message": "hi", "session_id": "s"},
            )
    assert r.status_code == 429
    assert "Too many requests" in r.json().get("error", "")


def test_rate_limit_api_webhook_returns_429(client):
    """Repeated requests to /api/webhook get rate-limited (429) after limit."""
    from brain.server import RateLimiter

    mock_handler = MagicMock()
    mock_handler.process_event = AsyncMock(
        return_value=WebhookResponse(status="processed", message="OK")
    )
    fresh_limiter = RateLimiter()
    with patch("brain.server.event_handler", mock_handler):
        with patch.object(settings, "webhook_enabled", True):
            with patch.object(settings, "webhook_secret", ""):
                with patch("brain.server.rate_limiter", fresh_limiter):
                    # Limit is 60/min for /api/webhook
                    for i in range(60):
                        r = client.post(
                            "/api/webhook",
                            json={
                                "event_type": "motion",
                                "entity_id": "binary_sensor.test",
                                "new_state": "on",
                            },
                        )
                        assert r.status_code == 200, (
                            f"Request {i + 1} should succeed"
                        )
                    r = client.post(
                        "/api/webhook",
                        json={
                            "event_type": "motion",
                            "entity_id": "binary_sensor.test",
                            "new_state": "on",
                        },
                    )
    assert r.status_code == 429
    assert "Too many requests" in r.json().get("error", "")
    assert "webhook" in r.json().get("error", "").lower()

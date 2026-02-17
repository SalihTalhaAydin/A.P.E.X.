"""Tests for webhook / event handler."""

import time

from brain.event_handler import (
    EventHandler,
    WebhookEvent,
    WebhookResponse,
)


def test_webhook_event_model():
    """WebhookEvent accepts all fields."""
    event = WebhookEvent(
        event_type="motion",
        entity_id="binary_sensor.hallway_motion",
        new_state="on",
        old_state="off",
        attributes={"friendly_name": "Hallway Motion"},
        timestamp="2026-02-17T23:30:00",
    )
    assert event.event_type == "motion"
    assert event.entity_id == (
        "binary_sensor.hallway_motion"
    )


def test_webhook_event_defaults():
    """WebhookEvent works with minimal fields."""
    event = WebhookEvent(
        event_type="door",
        entity_id="binary_sensor.front_door",
    )
    assert event.new_state == ""
    assert event.old_state == ""
    assert event.attributes == {}


def test_webhook_response_model():
    """WebhookResponse has correct fields."""
    resp = WebhookResponse(
        status="processed",
        message="Lights turned on.",
        actions_taken=["control_light"],
    )
    assert resp.status == "processed"


def test_event_handler_cooldown():
    """Cooldown prevents rapid re-processing."""
    handler = EventHandler(
        conversation=None, cooldown=60
    )
    key = "motion:binary_sensor.hallway"

    # First call: should pass
    assert handler._check_cooldown(key) is True

    # Second call within cooldown: should block
    assert handler._check_cooldown(key) is False


def test_event_handler_cooldown_expires():
    """Cooldown expires after the specified time."""
    handler = EventHandler(
        conversation=None, cooldown=0
    )
    key = "motion:binary_sensor.hallway"

    assert handler._check_cooldown(key) is True
    # With cooldown=0, immediately passes again
    assert handler._check_cooldown(key) is True


def test_event_message_motion():
    """Motion events build correct message."""
    handler = EventHandler(
        conversation=None, cooldown=60
    )
    event = WebhookEvent(
        event_type="motion",
        entity_id="binary_sensor.hallway_motion",
        new_state="on",
        attributes={
            "friendly_name": "Hallway Motion"
        },
    )
    msg = handler._build_event_message(event)
    assert "Motion detected" in msg
    assert "Hallway Motion" in msg


def test_event_message_door():
    """Door events build correct message."""
    handler = EventHandler(
        conversation=None, cooldown=60
    )
    event = WebhookEvent(
        event_type="door",
        entity_id="binary_sensor.front_door",
        new_state="open",
    )
    msg = handler._build_event_message(event)
    assert "Door event" in msg
    assert "open" in msg


def test_event_message_generic():
    """Unknown event types get generic message."""
    handler = EventHandler(
        conversation=None, cooldown=60
    )
    event = WebhookEvent(
        event_type="custom_alert",
        entity_id="sensor.smoke",
        new_state="detected",
    )
    msg = handler._build_event_message(event)
    assert "custom_alert" in msg
    assert "Smoke" in msg

"""
Event Handler - Processes webhook events from HA.
Converts events to natural language, passes to the
conversation pipeline, and returns actions taken.
Includes cooldown to prevent reaction storms.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from pydantic import BaseModel

from brain.config import settings

logger = logging.getLogger(__name__)


def _is_high_priority(event_type: str, hour: int) -> bool:
    """Return True if this event warrants a voice announcement."""
    if event_type in ("door", "alarm"):
        return True
    if event_type == "motion" and (hour >= 22 or hour < 6):
        return True
    if "security" in event_type or "alarm" in event_type:
        return True
    return False


class WebhookEvent(BaseModel):
    """Incoming event from HA automation."""

    event_type: str  # motion, door, temperature, etc
    entity_id: str
    new_state: str = ""
    old_state: str = ""
    attributes: dict = {}
    timestamp: str = ""


class WebhookResponse(BaseModel):
    """Response after processing an event."""

    status: str  # processed, ignored, error
    message: str = ""
    actions_taken: list[str] = []


class EventHandler:
    """Receives HA events, decides action, delegates
    to the conversation pipeline."""

    def __init__(self, conversation, cooldown: int = 60):
        self.conversation = conversation
        self._cooldown_sec = cooldown
        self._cooldowns: dict[str, float] = {}

    def _cleanup_cooldowns(self) -> None:
        """Remove stale cooldown entries (older than 2x cooldown period)."""
        now = time.time()
        max_age = self._cooldown_sec * 2
        stale = [
            k
            for k, ts in self._cooldowns.items()
            if now - ts > max_age
        ]
        for k in stale:
            del self._cooldowns[k]

    def _check_cooldown(self, key: str) -> bool:
        """True if cooldown elapsed (ok to act)."""
        now = time.time()
        last = self._cooldowns.get(key, 0)
        if now - last < self._cooldown_sec:
            return False
        self._cooldowns[key] = now
        return True

    def _build_event_message(
        self, event: WebhookEvent
    ) -> str:
        """Convert event to natural language."""
        entity = event.entity_id
        name = (
            event.attributes.get("friendly_name")
            or entity.split(".")[-1]
            .replace("_", " ")
            .title()
        )

        templates = {
            "motion": (
                f"Motion detected: {name} "
                f"({entity}) changed to "
                f"'{event.new_state}'."
            ),
            "door": (
                f"Door event: {name} ({entity}) "
                f"is now '{event.new_state}'."
            ),
            "temperature": (
                f"Temperature alert: {name} "
                f"({entity}) is {event.new_state}."
            ),
            "state_changed": (
                f"State changed: {name} ({entity}) "
                f"went from '{event.old_state}' "
                f"to '{event.new_state}'."
            ),
        }

        msg = templates.get(
            event.event_type,
            f"Event '{event.event_type}' on "
            f"{name} ({entity}): "
            f"state={event.new_state}.",
        )

        if event.timestamp:
            msg += f" Time: {event.timestamp}."

        msg += (
            " Assess the situation and take "
            "appropriate action if needed."
        )
        return msg

    @staticmethod
    def _is_redundant(event: WebhookEvent) -> str:
        """Return a reason string if the event should be
        silently dropped, or empty string if it should be
        processed.

        Filters out:
        - identical old/new state (no real change)
        - transitions to/from 'unavailable' (connectivity
          bounces from flaky integrations like Kasa)
        """
        old = event.old_state.strip().lower()
        new = event.new_state.strip().lower()

        # Same state repeated — not a real change
        if old and new and old == new:
            return (
                f"redundant: state unchanged ({new})"
            )

        # Unavailable bounces — device connectivity noise
        if new == "unavailable":
            return "device went unavailable"
        if old == "unavailable" and new:
            return (
                f"recovery from unavailable to {new}"
            )

        return ""

    async def process_event(
        self, event: WebhookEvent
    ) -> WebhookResponse:
        """Process an incoming event."""
        self._cleanup_cooldowns()

        # Filter redundant / noisy state transitions
        skip_reason = self._is_redundant(event)
        if skip_reason:
            logger.debug(
                "Dropping noisy event %s on %s: %s",
                event.event_type,
                event.entity_id,
                skip_reason,
            )
            return WebhookResponse(
                status="ignored",
                message=(
                    f"Filtered: {skip_reason} "
                    f"for {event.entity_id}."
                ),
            )

        cooldown_key = (
            f"{event.event_type}:{event.entity_id}"
        )

        if not self._check_cooldown(cooldown_key):
            return WebhookResponse(
                status="ignored",
                message=(
                    f"Cooldown active for "
                    f"{cooldown_key} "
                    f"({self._cooldown_sec}s)."
                ),
            )

        msg = self._build_event_message(event)

        try:
            response = await self.conversation.handle(
                msg, session_id="apex_events"
            )
            return WebhookResponse(
                status="processed",
                message=response,
            )
        except Exception as e:
            logger.exception(
                "Error processing event %s on %s",
                event.event_type,
                event.entity_id,
            )
            return WebhookResponse(
                status="error",
                message="Internal processing error.",
            )

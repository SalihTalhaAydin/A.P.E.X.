"""
Event Handler - Processes webhook events from HA.
Converts events to natural language, passes to the
conversation pipeline, and returns actions taken.
Includes cooldown to prevent reaction storms.
"""

import logging
import time

from pydantic import BaseModel

logger = logging.getLogger(__name__)


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

    async def process_event(
        self, event: WebhookEvent
    ) -> WebhookResponse:
        """Process an incoming event."""
        self._cleanup_cooldowns()
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
            return WebhookResponse(
                status="error",
                message=f"Error processing: {e}",
            )

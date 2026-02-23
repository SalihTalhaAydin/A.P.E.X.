"""
Event Handler - Processes webhook events from HA.
Converts events to natural language, passes to the
conversation pipeline, and returns actions taken.
Includes cooldown to prevent reaction storms.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

from brain.config import settings
from brain.cooldown import CooldownTracker

logger = logging.getLogger(__name__)


def _effective_event_type(event_type: str, entity_id: str) -> str:
    """Derive event type from entity when event_type is state_changed (BUG-159).
    WebSocket events are always state_changed; derive alarm/door from domain."""
    if event_type != "state_changed":
        return event_type
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    if domain == "alarm_control_panel":
        return "alarm"
    if domain in ("lock", "cover"):
        return "door"
    return event_type


def _is_high_priority(event_type: str, hour: int, entity_id: str = "") -> bool:
    """Return True if this event warrants a voice announcement."""
    effective = _effective_event_type(event_type, entity_id)
    if effective in ("door", "alarm"):
        return True
    if effective == "motion" and (hour >= 22 or hour < 6):
        return True
    if "security" in effective or "alarm" in effective:
        return True
    return False


def _build_announcement_message(event: "WebhookEvent") -> str:
    """Build a short, TTS-friendly message for voice announcement."""
    name = (
        event.attributes.get("friendly_name")
        or event.entity_id.split(".")[-1].replace("_", " ").title()
    )
    templates = {
        "motion": f"Motion detected in {name}",
        "door": f"Door event: {name} is {event.new_state}",
        "alarm": f"Alarm alert: {name}",
        "temperature": f"Temperature alert in {name}",
    }
    return templates.get(
        event.event_type,
        f"Alert: {name} – {event.new_state}",
    )


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
        self._cooldown = CooldownTracker(cooldown)

    def _build_event_message(self, event: WebhookEvent) -> str:
        """Convert event to natural language."""
        entity = event.entity_id
        name = (
            event.attributes.get("friendly_name")
            or entity.split(".")[-1].replace("_", " ").title()
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
            " Report this event to the user. "
            "Do NOT take any device actions unless "
            "the event clearly requires an immediate "
            "safety response."
        )
        return msg

    @staticmethod
    def _is_redundant(event: WebhookEvent) -> str:
        """Return a reason string if the event should be
        silently dropped, or empty string if it should be
        processed.

        Filters out:
        - identical old/new state (no real change)
        - transitions to/from 'unavailable'
          (connectivity bounces)
        """
        old = event.old_state.strip().lower()
        new = event.new_state.strip().lower()

        # Same state repeated — not a real change
        if old and new and old == new:
            return f"redundant: state unchanged ({new})"

        # Unavailable bounces — device connectivity noise
        if new == "unavailable":
            return "device went unavailable"
        # Recovery from unavailable: do NOT drop (users need to know when
        # devices come back online; BUG-88)
        # Removed: if old == "unavailable" and new: return "recovery..."

        return ""

    async def process_event(self, event: WebhookEvent) -> WebhookResponse:
        """Process an incoming event."""
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
                    f"Filtered: {skip_reason} for {event.entity_id}."
                ),
            )

        cooldown_key = f"{event.event_type}:{event.entity_id}"

        if not self._cooldown.check_and_set(cooldown_key):
            return WebhookResponse(
                status="ignored",
                message=(f"Cooldown active for {cooldown_key}."),
            )

        msg = self._build_event_message(event)

        # Check if event warrants a voice announcement
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(settings.timezone)
        except Exception:
            tz = timezone.utc
            logger.debug(
                "Could not load timezone '%s', using UTC",
                settings.timezone,
            )
        now = datetime.now(tz)
        high_priority = _is_high_priority(
            event.event_type, now.hour, event.entity_id
        )
        if high_priority:
            logger.info(
                "High-priority event: %s on %s",
                event.event_type,
                event.entity_id,
            )

        actions_taken: list[str] = []
        if high_priority:
            actions_taken.append("high_priority_alert")
            if settings.announce_on_events and settings.announce_target:
                try:
                    from tools.notify import announce

                    announcement_msg = _build_announcement_message(event)
                    await announce(
                        announcement_msg,
                        target=settings.announce_target,
                    )
                    actions_taken.append("voice_announcement")
                except Exception:
                    logger.exception(
                        "Failed to announce high-priority event %s on %s",
                        event.event_type,
                        event.entity_id,
                    )

        try:
            session_id = f"apex_events:{event.entity_id}:{uuid.uuid4().hex[:12]}"
            response = await self.conversation.handle(msg, session_id=session_id)
            return WebhookResponse(
                status="processed",
                message=response,
                actions_taken=actions_taken,
            )
        except Exception:
            logger.exception(
                "Error processing event %s on %s",
                event.event_type,
                event.entity_id,
            )
            return WebhookResponse(
                status="error",
                message="Internal processing error.",
            )

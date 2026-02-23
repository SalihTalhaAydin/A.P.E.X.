"""
Webhook tools for Home Assistant.
Fire webhook triggers and list webhook automations.
"""

from __future__ import annotations

import logging

from tools.base import tool
from tools.ha_helpers import ha_request

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Fire a Home Assistant webhook by ID. "
        "Webhooks can trigger automations, scripts, "
        "or integrations. Use for 'trigger my "
        "webhook', 'fire the doorbell webhook', etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "webhook_id": {
                "type": "string",
                "description": (
                    "The webhook ID to fire. "
                    "This is the ID configured in "
                    "the HA automation or integration."
                ),
            },
            "data": {
                "type": "object",
                "description": (
                    "Optional JSON payload to send "
                    "with the webhook. This data is "
                    "available as trigger.json in "
                    "the automation."
                ),
            },
        },
        "required": ["webhook_id"],
    },
)
async def fire_webhook(webhook_id: str, data: dict | None = None) -> str:
    """Fire an HA webhook."""
    try:
        await ha_request(
            "POST",
            f"/webhook/{webhook_id}",
            json_data=data or {},
            skip_auth=True,
        )
        return f"Done. Webhook '{webhook_id}' fired successfully."
    except Exception as e:
        return f"Error firing webhook: {e}"


@tool(
    description=(
        "List automations that use webhook triggers. "
        "Helps discover available webhook IDs."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def list_webhook_automations() -> str:
    """List automations with webhook triggers."""
    try:
        states = await ha_request("GET", "/states")
        if not isinstance(states, list):
            return "Error: Unable to reach Home Assistant."
        automations = [
            s for s in states if s.get("entity_id", "").startswith("automation.")
        ]

        webhook_autos = []
        for a in automations:
            attrs = a.get("attributes", {})
            eid = a["entity_id"]
            fn = attrs.get("friendly_name", eid)

            # Check trigger list for webhook platform entries
            triggers = attrs.get("trigger", [])
            if not isinstance(triggers, list):
                triggers = [triggers]
            webhook_trigger_ids = [
                t.get("webhook_id", "")
                for t in triggers
                if isinstance(t, dict)
                and t.get("platform") == "webhook"
            ]
            has_webhook_trigger = bool(webhook_trigger_ids)

            # Also match by name/entity_id substring
            name_match = (
                "webhook" in fn.lower()
                or "webhook" in eid.lower()
            )

            if has_webhook_trigger or name_match:
                state = a.get("state", "unknown")
                if webhook_trigger_ids:
                    ids_str = ", ".join(
                        i for i in webhook_trigger_ids if i
                    )
                    entry = (
                        f"- {fn} ({eid}): {state}"
                        + (
                            f" [webhook_id: {ids_str}]"
                            if ids_str
                            else ""
                        )
                    )
                else:
                    entry = f"- {fn} ({eid}): {state}"
                webhook_autos.append(entry)

        if not webhook_autos:
            return (
                "No webhook-related automations found. "
                "Webhook IDs are configured in HA "
                "automations with webhook triggers."
            )

        return (
            f"Found {len(webhook_autos)} webhook-related "
            "automation(s):\n" + "\n".join(webhook_autos)
        )
    except Exception as e:
        return f"Error listing webhook automations: {e}"


@tool(
    description=(
        "Fire a Home Assistant event on the event bus. "
        "Use for triggering custom events that "
        "automations can listen for. Use for "
        "'fire event', 'trigger custom event', etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": (
                    "Event type to fire, e.g. "
                    "'custom_alarm', 'apex_trigger'."
                ),
            },
            "event_data": {
                "type": "object",
                "description": (
                    "Optional data payload for the "
                    "event. Available as trigger.event"
                    ".data in automations."
                ),
            },
        },
        "required": ["event_type"],
    },
)
async def fire_event(
    event_type: str, event_data: dict | None = None
) -> str:
    """Fire a custom event on the HA event bus."""
    try:
        await ha_request(
            "POST",
            f"/events/{event_type}",
            json_data=event_data or {},
        )
        return f"Done. Event '{event_type}' fired successfully."
    except Exception as e:
        return f"Error firing event: {e}"

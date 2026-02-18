"""
Webhook tools for Home Assistant.
Fire webhook triggers and list webhook automations.
"""

import logging

import httpx
from brain.config import settings

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
        url = f"{settings.ha_url}/api/webhook/{webhook_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=data or {})
            # Webhooks return 200 on success
            if response.status_code == 200:
                return f"Done. Webhook '{webhook_id}' fired successfully."
            return (
                f"Webhook returned status "
                f"{response.status_code}: "
                f"{response.text[:200]}"
            )
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
        automations = [
            s for s in states if s["entity_id"].startswith("automation.")
        ]

        webhook_autos = []
        for a in automations:
            attrs = a.get("attributes", {})
            # Check if "webhook" appears in the
            # automation's friendly name or id
            eid = a["entity_id"]
            fn = attrs.get("friendly_name", eid)
            if "webhook" in fn.lower() or "webhook" in eid.lower():
                state = a.get("state", "unknown")
                webhook_autos.append(f"- {fn} ({eid}): {state}")

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

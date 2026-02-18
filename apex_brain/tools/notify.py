"""
Notification tool for Home Assistant.
Supports Echo speakers (speak/announce) and mobile phone notifications.

HA 2024.11+ uses entity-based notify: call notify.send_message
with an entity_id instead of per-device service names.
Legacy services (persistent_notification) are kept as fallback.
"""

from __future__ import annotations

import logging

import httpx

from tools.base import tool
from tools.ha_helpers import format_ha_error, ha_request

logger = logging.getLogger(__name__)

# Legacy services that still use the old calling convention
_LEGACY_SERVICES = frozenset(
    {"persistent_notification", "notify"}
)


@tool(
    description=(
        "Send a notification or announcement. For Echo "
        "speakers use announce entities to broadcast, or "
        "speak entities for a single speaker. For phone "
        "use mobile_app notify entities. Use "
        "list_entities(domain='notify') to discover targets."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Notify entity ID (use "
                    "list_entities to discover)."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "The message to send or announce."
                ),
            },
            "title": {
                "type": "string",
                "description": (
                    "Optional title for phone "
                    "notifications. Ignored for Echo."
                ),
            },
        },
        "required": ["entity_id", "message"],
    },
)
async def send_notification(
    entity_id: str,
    message: str,
    title: str | None = None,
) -> str:
    """Send a notification via HA notify service."""
    try:
        service_name = entity_id.replace(
            "notify.", "", 1
        )
        target = (
            service_name.replace("_", " ").title()
        )

        data: dict = {"message": message}
        if title is not None:
            data["title"] = title

        if service_name in _LEGACY_SERVICES:
            # Legacy services (persistent_notification)
            await ha_request(
                "POST",
                f"/services/notify/{service_name}",
                json_data=data,
            )
        else:
            # Entity-based notify (HA 2024.11+)
            await ha_request(
                "POST",
                "/services/notify/send_message",
                json_data={
                    "entity_id": entity_id,
                    **data,
                },
            )

        return f"Sent to {target}: \"{message}\""

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "notify", e)
    except Exception as e:
        return f"Error sending notification: {e}"

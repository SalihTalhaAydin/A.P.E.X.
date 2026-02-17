"""
Notification tool for Home Assistant.
Supports Echo speakers (speak/announce) and mobile phone notifications.
"""

import httpx

from tools.base import tool
from tools.ha_helpers import format_ha_error, ha_request


@tool(
    description=(
        "Send a notification or announcement. For Echo "
        "speakers use announce entities (e.g. "
        "'notify.everywhere_announce') to broadcast, or "
        "speak entities for a single speaker. For phone "
        "use 'notify.mobile_app_salih_iphone'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Notify entity ID, e.g. "
                    "'notify.everywhere_announce', "
                    "'notify.bedroom_echo_dot_speak', "
                    "'notify.mobile_app_salih_iphone'."
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
        # Extract service name from entity_id
        # notify.everywhere_announce -> everywhere_announce
        service_name = entity_id.replace("notify.", "", 1)

        data: dict = {"message": message}
        if title is not None:
            data["title"] = title

        await ha_request(
            "POST",
            f"/services/notify/{service_name}",
            json_data=data,
        )
        target = service_name.replace("_", " ").title()
        return f"Sent to {target}: \"{message}\""

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "notify", e)
    except Exception as e:
        return f"Error sending notification: {e}"

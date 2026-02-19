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

from brain.config import settings
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


@tool(
    description=(
        "Speak a message aloud in the home via Alexa/Echo "
        "speakers or send a phone notification. "
        "target: 'alexa_all' (default) for all Alexa devices, "
        "'phone' for the mobile app, or a specific notify.* "
        "entity name (without the domain prefix)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to announce.",
            },
            "target": {
                "type": "string",
                "description": (
                    "'alexa_all' (default), 'phone', or a "
                    "specific notify service/entity name."
                ),
            },
        },
        "required": ["message"],
    },
)
async def announce(
    message: str,
    target: str = "alexa_all",
) -> str:
    """Announce a message via Alexa or phone notification."""
    try:
        if target == "phone":
            await ha_request(
                "POST",
                f"/services/notify/{settings.phone_notify_target}",
                json_data={"message": message},
            )
            return f"Phone notification sent: \"{message}\""

        if target == "alexa_all":
            # Try the Alexa Media Player "everywhere" group first
            try:
                await ha_request(
                    "POST",
                    "/services/notify/alexa_media_everywhere",
                    json_data={
                        "message": message,
                        "data": {"type": "announce"},
                    },
                )
                return (
                    f"Announced on all Alexa devices: \"{message}\""
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (400, 404):
                    raise
                # Service not found — discover Alexa notify entities
                logger.warning(
                    "alexa_media_everywhere not found, "
                    "discovering Alexa notify entities…"
                )

            # Discover notify.* entities containing "alexa"
            try:
                services_resp = await ha_request(
                    "GET", "/services"
                )
            except Exception as disc_err:
                return (
                    f"Could not discover notify targets: {disc_err}"
                )

            alexa_services: list[str] = []
            if isinstance(services_resp, list):
                for domain_info in services_resp:
                    if domain_info.get("domain") != "notify":
                        continue
                    for svc_name in domain_info.get(
                        "services", {}
                    ).keys():
                        if "alexa" in svc_name.lower():
                            alexa_services.append(svc_name)

            if not alexa_services:
                # Last resort: list states for notify.*
                try:
                    states = await ha_request("GET", "/states")
                    alexa_services = [
                        s["entity_id"].replace("notify.", "", 1)
                        for s in states
                        if s["entity_id"].startswith("notify.")
                        and "alexa" in s["entity_id"].lower()
                    ]
                except Exception:
                    pass

            if not alexa_services:
                # Report what notify services are available
                available: list[str] = []
                if isinstance(services_resp, list):
                    for domain_info in services_resp:
                        if domain_info.get("domain") == "notify":
                            available = list(
                                domain_info.get(
                                    "services", {}
                                ).keys()
                            )
                            break
                return (
                    "No Alexa notify targets found. "
                    f"Available notify services: {available}"
                )

            results: list[str] = []
            for svc in alexa_services:
                try:
                    await ha_request(
                        "POST",
                        f"/services/notify/{svc}",
                        json_data={
                            "message": message,
                            "data": {"type": "announce"},
                        },
                    )
                    results.append(svc)
                except Exception as svc_err:
                    logger.warning(
                        "Failed to announce on %s: %s",
                        svc,
                        svc_err,
                    )
            if results:
                return (
                    f"Announced on {results}: \"{message}\""
                )
            return (
                f"Announce failed on all discovered targets: "
                f"{alexa_services}"
            )

        # Specific target (service name or entity name)
        try:
            await ha_request(
                "POST",
                f"/services/notify/{target}",
                json_data={"message": message},
            )
            return f"Notified {target}: \"{message}\""
        except httpx.HTTPStatusError as e:
            return format_ha_error(target, "notify", e)

    except httpx.HTTPStatusError as e:
        return format_ha_error(target, "notify", e)
    except Exception as e:
        return f"Error in announce: {e}"

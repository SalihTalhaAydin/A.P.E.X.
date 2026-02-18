"""
Shared helpers for Home Assistant API access.
Used by all smart-home tool modules. No @tool decorators here.
"""

from __future__ import annotations

import logging

import httpx
from brain.config import settings

logger = logging.getLogger(__name__)

# Shared client — created once at module load, reused for all HA API calls.
# This avoids the overhead of opening/closing a TCP connection per request.
# A module-level AsyncClient is safe for a long-running asyncio server.
_ha_client = httpx.AsyncClient(timeout=15.0)


def format_ha_error(
    entity_id: str, domain: str, e: Exception
) -> str:
    """Return a short, model-friendly error."""
    if isinstance(e, httpx.HTTPStatusError):
        r = getattr(e, "response", None)
        if r is not None:
            code = r.status_code
            body = (r.text or "")[:200]
            if code == 404:
                return (
                    f"Entity not found: {entity_id}. "
                    "Check the entity_id with list_entities."
                )
            if code == 422:
                return (
                    "HA rejected the request (422). "
                    f"{body or str(e)}"
                )
            return f"HA error {code}: {body or str(e)}"
    return f"Error ({domain}): {e}"


async def ha_request(
    method: str,
    path: str,
    json_data: dict | None = None,
    *,
    return_response: bool = False,
) -> dict | list | str:
    """Make an authenticated request to the HA REST API.

    Set *return_response=True* for service calls that
    require ``?return_response`` (e.g. todo/get_items,
    weather/get_forecasts).  The wrapper is automatically
    stripped so callers receive the ``service_response``
    dict directly.
    """
    url = f"{settings.ha_api_url}{path}"
    if return_response:
        sep = "&" if "?" in path else "?"
        url += f"{sep}return_response"
    headers = settings.ha_headers
    token = headers.get("Authorization", "")
    tok = "set" if len(token) > 10 else "MISSING"
    logger.debug("HA API %s %s (token: %s)", method, url, tok)
    response = await _ha_client.request(
        method=method,
        url=url,
        headers=headers,
        json=json_data,
    )
    if not response.is_success:
        logger.error(
            "HA API error: %s %s",
            response.status_code,
            response.text[:300],
        )
    response.raise_for_status()
    content_type = response.headers.get(
        "content-type", ""
    )
    if "application/json" in content_type:
        result = response.json()
        if (
            return_response
            and isinstance(result, dict)
            and "service_response" in result
        ):
            return result["service_response"]
        return result
    text = response.text
    if text:
        logger.debug("Non-JSON HA response: %s", text[:200])
        return text
    return {}


def friendly_name(entity_id: str) -> str:
    """Derive a human-friendly name from an entity_id."""
    return (
        entity_id.split(".")[-1].replace("_", " ").title()
    )


async def call_ha_service(
    domain: str,
    service: str,
    entity_id: str,
    data: dict | None = None,
) -> None:
    """Call an HA service and log the full payload."""
    payload = {"entity_id": entity_id}
    if data:
        payload.update(data)
    logger.debug(
        "HA service call: %s.%s -> %s data=%s",
        domain, service, entity_id, data,
    )
    await ha_request(
        "POST",
        f"/services/{domain}/{service}",
        json_data=payload,
    )


async def read_state(entity_id: str) -> dict:
    """Read entity state. Returns the full state dict."""
    return await ha_request("GET", f"/states/{entity_id}")


# Domains whose entities are injected into the system prompt so
# the AI always knows the current devices without hardcoding.
# Each entry is either a plain string (no cap) or a
# (domain, max_entities) tuple (cap applied).
_DISCOVERY_DOMAINS: tuple = (
    "vacuum",
    "notify",
    "todo",
    ("light", 15),
    "climate",
    "media_player",
    "lock",
    "cover",
)


async def get_device_summary() -> str:
    """Fetch key device entities from HA for the system prompt.

    Returns a short summary string the AI can reference
    to know exact entity IDs and friendly names.  Called once
    per conversation turn by the context builder.
    """
    try:
        states = await ha_request("GET", "/states")
    except Exception:
        return ""

    sections: list[str] = []
    for entry in _DISCOVERY_DOMAINS:
        if isinstance(entry, tuple):
            domain, cap = entry
        else:
            domain, cap = entry, None

        entities = [
            s
            for s in states
            if s["entity_id"].startswith(f"{domain}.")
        ]
        if not entities:
            continue

        total = len(entities)
        if cap is not None and total > cap:
            shown = entities[:cap]
            header = (
                f"## {domain.replace('_', ' ').title()}"
                f" ({cap} of {total}):"
            )
        else:
            shown = entities
            header = f"## {domain.replace('_', ' ').title()}:"

        lines: list[str] = []
        for s in shown:
            eid = s["entity_id"]
            fn = s.get("attributes", {}).get(
                "friendly_name", friendly_name(eid)
            )
            st = s.get("state", "unknown")
            lines.append(f"  - {fn} ({eid}): {st}")

        sections.append(header + "\n" + "\n".join(lines))

    return "\n".join(sections)


async def get_battery_level(entity_id: str) -> int | None:
    """Get battery level for an entity, falling back to
    a companion ``sensor.<name>_battery`` entity when the
    attribute is missing (common after HA integration
    updates, e.g. Roborock vacuums).

    Returns the battery percentage as int, or None.
    """
    # 1. Try the entity's own attributes first
    try:
        state = await read_state(entity_id)
        level = state.get("attributes", {}).get(
            "battery_level"
        )
        if level is not None:
            return int(level)
    except Exception:
        pass

    # 2. Fallback: look for sensor.<name>_battery
    name = entity_id.split(".", 1)[-1]  # e.g. "dusty"
    sensor_id = f"sensor.{name}_battery"
    try:
        sensor = await read_state(sensor_id)
        val = sensor.get("state", "")
        if val not in ("unknown", "unavailable", ""):
            return int(float(val))
    except Exception:
        pass

    return None


async def verify_generic(entity_id: str) -> str:
    """Read back any entity's basic state."""
    try:
        state = await read_state(entity_id)
        fn = state.get("attributes", {}).get(
            "friendly_name", friendly_name(entity_id)
        )
        return f"{fn}: {state.get('state', 'unknown')}"
    except Exception:
        return (
            f"{friendly_name(entity_id)}: "
            "(state unconfirmed)"
        )

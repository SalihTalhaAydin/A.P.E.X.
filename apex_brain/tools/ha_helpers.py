"""
Shared helpers for Home Assistant API access.
Used by all smart-home tool modules. No @tool decorators here.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from brain.config import settings

logger = logging.getLogger(__name__)


class HomeAssistantError(Exception):
    """Raised when an HA API call fails (connection, timeout, HTTP error).

    Converts what were previously silent error-dicts into visible exceptions
    so callers cannot accidentally treat failures as empty results.
    """


# Lazy-initialized client — created on first use, not at import.
# Avoids connection pool issues when the process forks (e.g. uvicorn workers):
# each worker gets its own client in the correct process/event-loop context.
_ha_client: httpx.AsyncClient | None = None
_ha_client_lock: asyncio.Lock | None = None


def _get_ha_client_lock() -> asyncio.Lock:
    """Lazy-init lock to avoid RuntimeError when importing without event loop."""
    global _ha_client_lock
    if _ha_client_lock is None:
        _ha_client_lock = asyncio.Lock()
    return _ha_client_lock


async def get_ha_client() -> httpx.AsyncClient:
    """Get the shared HA client, creating it on first use (lazy init)."""
    global _ha_client
    if _ha_client is not None:
        return _ha_client
    async with _get_ha_client_lock():
        if _ha_client is not None:
            return _ha_client
        _ha_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
        return _ha_client


async def close_ha_client():
    """Close the shared HA client on shutdown."""
    global _ha_client
    if _ha_client is not None:
        await _ha_client.aclose()
        _ha_client = None


def format_ha_error(entity_id: str, domain: str, e: Exception) -> str:
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
                return f"HA rejected the request (422). {body or str(e)}"
            return f"HA error {code}: {body or str(e)}"
    return f"Error ({domain}): {e}"


async def ha_request(
    method: str,
    path: str,
    json_data: dict | None = None,
    *,
    return_response: bool = False,
    skip_auth: bool = False,
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
    headers = {} if skip_auth else settings.ha_headers
    token = headers.get("Authorization", "")
    tok = "set" if len(token) > 10 else "MISSING"
    logger.debug("HA API %s %s (token: %s)", method, url, tok)
    try:
        client = await get_ha_client()
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
        )
    except httpx.ConnectError as exc:
        raise HomeAssistantError(
            "Cannot connect to Home Assistant. Check HA_URL and network."
        ) from exc
    except httpx.TimeoutException as exc:
        raise HomeAssistantError(
            "Home Assistant API request timed out."
        ) from exc
    if not response.is_success:
        logger.debug(
            "HA API error: %s %s",
            response.status_code,
            response.text[:300],
        )
        raise HomeAssistantError(
            f"HA API error {response.status_code}: {response.text[:300]}"
        )
    content_type = response.headers.get("content-type", "")
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
    return entity_id.split(".")[-1].replace("_", " ").title()


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
        domain,
        service,
        entity_id,
        data,
    )
    await ha_request(
        "POST",
        f"/services/{domain}/{service}",
        json_data=payload,
    )


async def read_state(entity_id: str | list[str]) -> dict:
    """Read entity state. Returns the full state dict.

    Accepts entity_id as str or list (HA services accept both);
    if list, uses the first element for the GET /states/{id} URL.

    Raises HomeAssistantError on connection/timeout/HTTP errors
    (propagated from ha_request).
    """
    eid = entity_id[0] if isinstance(entity_id, list) else entity_id
    return await ha_request("GET", f"/states/{eid}")


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
    "camera",
)


def _entity_area_lookup_placeholder(entity_ids: list[str]) -> str:
    """Build Jinja2 template to get area_id for each entity.

    Returns template string; call via POST /template.
    """
    import json

    ids_json = json.dumps(entity_ids)
    return (
        "{% for eid in " + ids_json + " %}"
        "{{ eid }}|{{ area_id(eid) or '' }}\n"
        "{% endfor %}"
    )


async def _fetch_area_ids(entity_ids: list[str]) -> dict[str, str]:
    """Fetch area_id for each entity via HA template API.

    Returns dict mapping entity_id -> area_id (empty string if no area).
    """
    if not entity_ids:
        return {}
    try:
        template = _entity_area_lookup_placeholder(entity_ids)
        raw = await ha_request(
            "POST",
            "/template",
            json_data={"template": template},
        )
        if not isinstance(raw, str):
            return {}
        result: dict[str, str] = {}
        for line in raw.strip().split("\n"):
            line = line.strip()
            if "|" in line:
                eid, aid = line.split("|", 1)
                result[eid.strip()] = (aid or "").strip()
        return result
    except Exception as exc:
        logger.debug("Area lookup template failed: %s", exc)
        return {}


async def get_device_summary() -> str:
    """Fetch key device entities from HA for the system prompt.

    Returns a short summary string the AI can reference
    to know exact entity IDs, friendly names, and area_id.
    Area info helps the model map "basement" / "kitchen" to
    correct area_id for do() targets.
    """
    try:
        states = await ha_request("GET", "/states")
    except Exception as exc:
        logger.warning("Device summary fetch failed: %s", exc)
        return ""

    if not isinstance(states, list):
        logger.warning("Device summary: /states returned non-list: %s", type(states).__name__)
        return ""

    # Collect all entity IDs we will show; sections_data = (header, state dicts)
    all_shown_ids: list[str] = []
    sections_data: list[tuple[str, list[dict]]] = []

    for entry in _DISCOVERY_DOMAINS:
        if isinstance(entry, tuple):
            domain, cap = entry
        else:
            domain, cap = entry, None

        entities = [
            s for s in states if s.get("entity_id", "").startswith(f"{domain}.")
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

        all_shown_ids.extend(s.get("entity_id", "") for s in shown)
        sections_data.append((header, shown))

    # Fetch area_id for each entity (single template call)
    area_map = await _fetch_area_ids(all_shown_ids)

    # Build output with area_id in each line when available
    sections: list[str] = []
    for header, shown in sections_data:
        lines: list[str] = []
        for s in shown:
            eid = s.get("entity_id", "")
            fn = s.get("attributes", {}).get(
                "friendly_name", friendly_name(eid)
            )
            st = s.get("state", "unknown")
            aid = area_map.get(eid, "")
            if aid:
                lines.append(f"  - {fn} ({eid}) [area: {aid}]: {st}")
            else:
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
        level = state.get("attributes", {}).get("battery_level")
        if level is not None:
            return int(level)
    except Exception as exc:
        logger.debug(
            "Battery attr lookup failed for %s: %s", entity_id, exc
        )

    # 2. Fallback: look for sensor.<name>_battery
    name = entity_id.split(".", 1)[-1]  # e.g. "dusty"
    sensor_id = f"sensor.{name}_battery"
    try:
        sensor = await read_state(sensor_id)
        val = sensor.get("state", "")
        if val not in ("unknown", "unavailable", ""):
            return int(float(val))
    except Exception as exc:
        logger.debug(
            "Battery sensor lookup failed for %s: %s", sensor_id, exc
        )

    return None


async def verify_generic(entity_id: str | list[str]) -> str:
    """Read back any entity's basic state.

    Accepts entity_id as str or list; if list, uses first element.
    """
    eid = entity_id[0] if isinstance(entity_id, list) else entity_id
    try:
        state = await read_state(eid)
        fn = state.get("attributes", {}).get(
            "friendly_name", friendly_name(eid)
        )
        return f"{fn}: {state.get('state', 'unknown')}"
    except Exception:
        return f"{friendly_name(eid)}: (state unconfirmed)"

"""
Shared helpers for Home Assistant API access.
Used by all smart-home tool modules. No @tool decorators here.
"""

import logging

import httpx
from brain.config import settings

logger = logging.getLogger(__name__)


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
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
        )
        if response.status_code != 200:
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
        return response.text


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
_DISCOVERY_DOMAINS = (
    "vacuum",
    "notify",
    "todo",
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
    for domain in _DISCOVERY_DOMAINS:
        entities = [
            s
            for s in states
            if s["entity_id"].startswith(f"{domain}.")
        ]
        if not entities:
            continue
        lines: list[str] = []
        for s in entities:
            eid = s["entity_id"]
            fn = s.get("attributes", {}).get(
                "friendly_name", friendly_name(eid)
            )
            st = s.get("state", "unknown")
            lines.append(f"  - {fn} ({eid}): {st}")
        sections.append(
            f"{domain.upper()} devices:\n" + "\n".join(lines)
        )

    return "\n".join(sections)


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

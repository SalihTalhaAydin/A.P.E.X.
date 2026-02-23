"""
Generic tools for Home Assistant — Phase 1 redesign.

Four universal tools that replace 35+ domain-specific tools:
  discover() — find entities, services, areas, devices, integrations
  query()    — read entity state or evaluate Jinja2 templates
  do()       — call any HA service with verification
  history()  — state change history and logbook entries

All HA API calls go through ha_helpers.py. No httpx used directly.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from tools.base import tool
from tools.ha_helpers import (
    HomeAssistantError,
    format_ha_error,
    friendly_name,
    ha_request,
    read_state,
    verify_generic,
)

logger = logging.getLogger(__name__)

# Sensitive domains that require user confirmation before execution.
PROTECTED_DOMAINS = frozenset(
    {
        "lock",
        "alarm_control_panel",
        "camera",
        "cover",
    }
)

# Pending confirmations: token -> expires_at (UTC). 60-second TTL.
_pending_confirmations: dict[str, datetime] = {}
CONFIRMATION_TTL_SECONDS = 60


def _create_confirmation_token() -> str:
    """Generate a short-lived confirmation token and store it."""
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=CONFIRMATION_TTL_SECONDS
    )
    _pending_confirmations[token] = expires_at
    _cleanup_expired_confirmations()
    return token


def _cleanup_expired_confirmations() -> None:
    """Remove expired tokens from the pending store."""
    now = datetime.now(timezone.utc)
    expired = [t for t, exp in _pending_confirmations.items() if exp <= now]
    for t in expired:
        del _pending_confirmations[t]


def _consume_confirmation_token(token: str | None) -> bool:
    """Validate and consume a confirmation token. Returns True if valid."""
    if not token:
        return False
    _cleanup_expired_confirmations()
    expires_at = _pending_confirmations.get(token)
    if expires_at is None:
        return False
    if datetime.now(timezone.utc) > expires_at:
        del _pending_confirmations[token]
        return False
    del _pending_confirmations[token]
    return True


# ------------------------------------------------------------------
# discover()
# ------------------------------------------------------------------


@tool(
    description=(
        "Find entities, services, areas, floors, "
        "devices, integrations, or HA system info."
    ),
    parameters={
        "type": "object",
        "properties": {
            "what": {
                "type": "string",
                "enum": [
                    "entities",
                    "services",
                    "areas",
                    "floors",
                    "devices",
                    "integrations",
                    "info",
                ],
                "description": (
                    "What to discover: entities, "
                    "services, areas, floors, "
                    "devices, integrations, or info."
                ),
            },
            "filter_str": {
                "type": "string",
                "description": (
                    "Optional filter: domain "
                    "(e.g. 'light'), area name, "
                    "keyword, or empty for all."
                ),
                "default": "",
            },
        },
        "required": ["what"],
    },
)
async def discover(
    what: str,
    filter_str: str = "",
) -> str:
    """Find entities, services, areas, floors,
    devices, integrations, or HA system info."""
    try:
        if what == "entities":
            return await _discover_entities(filter_str)
        elif what == "services":
            return await _discover_services(filter_str)
        elif what == "areas":
            return await _discover_areas(filter_str)
        elif what == "floors":
            return await _discover_floors(filter_str)
        elif what == "devices":
            return await _discover_devices(filter_str)
        elif what == "integrations":
            return await _discover_integrations(filter_str)
        elif what == "info":
            return await _discover_info()
        else:
            return (
                f"Unknown discover target: {what}. "
                "Use: entities, services, areas, "
                "floors, devices, integrations, "
                "or info."
            )
    except HomeAssistantError as e:
        return f"Home Assistant connection error while discovering {what}: {e}"
    except Exception as e:
        return f"Error discovering {what}: {e}"


async def _discover_entities(filter_str: str) -> str:
    """List entities, optionally filtered by domain or keyword."""
    states = await ha_request("GET", "/states")
    if not isinstance(states, list):
        return "Unexpected response from Home Assistant (expected entity list)."

    filt = filter_str.strip().lower()
    if filt:
        matches = [
            s
            for s in states
            if filt in s["entity_id"].lower()
            or filt
            in s.get("attributes", {}).get("friendly_name", "").lower()
        ]
    else:
        matches = states

    if not matches:
        return f"No entities matching '{filter_str}'."

    lines = []
    for s in matches[:50]:
        eid = s["entity_id"]
        fn = s.get("attributes", {}).get(
            "friendly_name", friendly_name(eid)
        )
        st = s.get("state", "unknown")
        lines.append(f"  - {fn} ({eid}): {st}")

    header = f"Entities ({len(matches)} found"
    if len(matches) > 50:
        header += ", showing first 50"
    header += "):"
    return header + "\n" + "\n".join(lines)


async def _discover_services(filter_str: str) -> str:
    """List services, optionally filtered by domain.
    When filtered, include full schemas."""
    services = await ha_request("GET", "/services")
    if not isinstance(services, list):
        return "Unexpected response from Home Assistant (expected service list)."

    filt = filter_str.strip().lower()

    if filt:
        # Filter to matching domain and show full schemas
        matched = [s for s in services if filt in s.get("domain", "")]
        if not matched:
            return f"No services matching domain '{filter_str}'."

        lines = []
        for svc_domain in matched:
            domain = svc_domain.get("domain", "?")
            svc_list = svc_domain.get("services", {})
            for svc_name, svc_info in svc_list.items():
                desc = svc_info.get("description", "")
                fields = svc_info.get("fields", {})
                line = f"  {domain}.{svc_name}"
                if desc:
                    line += f" — {desc}"
                lines.append(line)
                for fname, finfo in fields.items():
                    ftype = finfo.get("selector", {})
                    freq = finfo.get("required", False)
                    fdesc = finfo.get("description", "")
                    type_str = _selector_to_type(ftype) if ftype else "any"
                    req_str = " (required)" if freq else ""
                    lines.append(
                        f"    {fname}: {type_str}{req_str} — {fdesc}"
                        if fdesc
                        else f"    {fname}: {type_str}{req_str}"
                    )

        return (
            f"Services for '{filt}' "
            f"({len(lines)} entries):\n" + "\n".join(lines)
        )
    else:
        # No filter — list domains only
        domains = [s.get("domain", "?") for s in services]
        return f"Service domains ({len(domains)}):\n" + ", ".join(
            sorted(domains)
        )


def _selector_to_type(selector: dict) -> str:
    """Convert a HA service field selector to a short type string."""
    if not selector:
        return "any"
    key = next(iter(selector), "")
    if key == "number":
        num = selector[key] or {}
        mn = num.get("min", "")
        mx = num.get("max", "")
        if mn or mx:
            return f"number({mn}..{mx})"
        return "number"
    elif key == "boolean":
        return "boolean"
    elif key == "text":
        return "string"
    elif key == "select":
        opts = (selector[key] or {}).get("options", [])
        if opts and len(opts) <= 6:
            return "enum[" + ",".join(str(o) for o in opts) + "]"
        return "select"
    elif key == "entity":
        domain = (selector[key] or {}).get("domain", "")
        if domain:
            return f"entity({domain})"
        return "entity"
    elif key == "target":
        return "target"
    elif key == "color_rgb":
        return "rgb[r,g,b]"
    elif key == "color_temp":
        return "color_temp"
    elif key == "time":
        return "time(HH:MM:SS)"
    return key or "any"


async def _discover_areas(filter_str: str) -> str:
    """List all areas via template API."""
    template = (
        "{% for area in areas() %}"
        "{{ area }}|{{ area_name(area) }}\n"
        "{% endfor %}"
    )
    result = await ha_request(
        "POST", "/template", json_data={"template": template}
    )
    if not result or not isinstance(result, str):
        return "Unexpected response from Home Assistant (expected area list)."

    lines = []
    for line in result.strip().split("\n"):
        if "|" not in line:
            continue
        area_id, area_nm = line.split("|", 1)
        filt = filter_str.strip().lower()
        if filt and filt not in area_nm.lower():
            continue
        lines.append(f"  - {area_nm} ({area_id})")

    if not lines:
        if filter_str:
            return f"No areas matching '{filter_str}'."
        return "No areas found."

    return f"Areas ({len(lines)}):\n" + "\n".join(lines)


async def _discover_floors(filter_str: str) -> str:
    """List all floors and their areas via template."""
    template = (
        "{% for floor in floors() %}"
        "{{ floor }}|{{ floor_name(floor) }}|"
        "{{ floor_areas(floor) | join(',') }}\n"
        "{% endfor %}"
    )
    try:
        result = await ha_request(
            "POST",
            "/template",
            json_data={"template": template},
        )
    except HomeAssistantError:
        raise  # Let discover() wrapper handle connection/auth errors
    except Exception:
        return "Floors not available (requires Home Assistant 2024.2+)."
    if not result or not isinstance(result, str):
        return "Unexpected response from Home Assistant (expected floor list)."

    filt = filter_str.strip().lower()
    lines = []
    for line in result.strip().split("\n"):
        if "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 2:
            continue
        floor_id = parts[0].strip()
        floor_nm = parts[1].strip()
        areas = parts[2].strip() if len(parts) > 2 else ""
        if filt and filt not in floor_nm.lower():
            continue
        entry = f"  - {floor_nm} ({floor_id})"
        if areas:
            entry += f" — areas: {areas}"
        lines.append(entry)

    if not lines:
        if filter_str:
            return f"No floors matching '{filter_str}'."
        return "No floors found."

    return f"Floors ({len(lines)}):\n" + "\n".join(lines)


async def _discover_devices(filter_str: str) -> str:
    """List devices via template API."""
    # Use a Jinja template to list devices with area info
    template = (
        "{% for state in states %}"
        "{% if state.attributes.device_class is defined "
        "or state.entity_id.split('.')[0] "
        "in ['light','switch','sensor','binary_sensor',"
        "'climate','media_player','vacuum','cover','lock',"
        "'fan','camera'] %}"
        "{{ state.entity_id }}|"
        "{{ state.attributes.friendly_name "
        "| default(state.entity_id) }}|"
        "{{ state.state }}\n"
        "{% endif %}"
        "{% endfor %}"
    )
    result = await ha_request(
        "POST", "/template", json_data={"template": template}
    )

    if not result or not isinstance(result, str):
        return "Unexpected response from Home Assistant (expected device list)."

    filt = filter_str.strip().lower()
    lines = []
    for line in result.strip().split("\n"):
        if "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        eid, fn, st = parts
        if filt and filt not in fn.lower() and filt not in eid.lower():
            continue
        lines.append(f"  - {fn} ({eid}): {st}")

    if not lines:
        if filter_str:
            return f"No devices matching '{filter_str}'."
        return "No devices found."

    if len(lines) > 50:
        return (
            f"Devices ({len(lines)} found, "
            f"showing first 50):\n" + "\n".join(lines[:50])
        )
    return f"Devices ({len(lines)}):\n" + "\n".join(lines)


async def _discover_integrations(filter_str: str) -> str:
    """List configured integrations via config entries."""
    # Try the config entries endpoint
    try:
        entries = await ha_request("GET", "/config/config_entries/entry")
    except HomeAssistantError:
        raise  # Let discover() wrapper handle connection/auth errors
    except Exception:
        return (
            "Could not list integrations (endpoint may not be available)."
        )

    if not isinstance(entries, list):
        return "Unexpected response from Home Assistant (expected integration list)."

    filt = filter_str.strip().lower()
    seen = {}
    for entry in entries:
        domain = entry.get("domain", "unknown")
        title = entry.get("title", domain)
        state = entry.get("state", "unknown")
        if filt and filt not in domain and filt not in title.lower():
            continue
        key = f"{domain}:{title}"
        if key not in seen:
            seen[key] = f"  - {title} ({domain}): {state}"

    if not seen:
        if filter_str:
            return f"No integrations matching '{filter_str}'."
        return "No integrations found."

    lines = sorted(seen.values())
    return f"Integrations ({len(lines)}):\n" + "\n".join(lines)


async def _discover_info() -> str:
    """Return HA system info."""
    try:
        config = await ha_request("GET", "/config")
    except HomeAssistantError:
        raise  # Let discover() wrapper handle connection/auth errors
    except Exception as e:
        return f"Could not get HA info: {e}"

    if not isinstance(config, dict):
        return "Unexpected response from Home Assistant (expected config dict)."

    version = config.get("version", "unknown")
    name = config.get("location_name", "Home")
    tz = config.get("time_zone", "unknown")
    unit = config.get("unit_system", {})
    temp_unit = unit.get("temperature", "unknown")
    elevation = config.get("elevation", "?")
    lat = config.get("latitude", "?")
    lon = config.get("longitude", "?")

    return (
        f"Home Assistant Info:\n"
        f"  Version: {version}\n"
        f"  Location: {name} ({lat}, {lon})\n"
        f"  Timezone: {tz}\n"
        f"  Temperature unit: {temp_unit}\n"
        f"  Elevation: {elevation}m"
    )


# ------------------------------------------------------------------
# query()
# ------------------------------------------------------------------


@tool(
    description=(
        "Read entity state or evaluate a Jinja2 template "
        "against Home Assistant."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "An entity_id (e.g. 'light.kitchen') or a "
                    "Jinja2 template string "
                    "(e.g. '{{ states(\"sensor.temp\") }}')."
                ),
            },
        },
        "required": ["target"],
    },
)
async def query(target: str) -> str:
    """Read entity state or evaluate a Jinja2 template."""
    try:
        if _is_template(target):
            return await _query_template(target)
        elif "." in target:
            return await _query_entity(target)
        else:
            return (
                f"Cannot query '{target}'. "
                "Provide an entity_id (e.g. 'light.kitchen') "
                "or a Jinja2 template (e.g. "
                "'{{ states(\"sensor.temp\") }}')."
            )
    except Exception as e:
        return f"Error querying '{target}': {e}"


def _is_template(target: str) -> bool:
    """Check if target looks like a Jinja2 template."""
    return "{{" in target or "{%" in target


_ENTITY_RE = re.compile(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$")


async def _query_entity(entity_id: str) -> str:
    """Read a single entity's state and key attributes."""
    try:
        state = await read_state(entity_id)
    except HomeAssistantError as exc:
        err_msg = str(exc)
        if "404" in err_msg:
            # Validate entity_id before template injection
            if not _ENTITY_RE.match(entity_id):
                return (
                    f"Invalid entity_id format: "
                    f"'{entity_id}'. Expected format: "
                    "domain.name (e.g. light.kitchen)."
                )
            # Smart fallback: try as template
            try:
                result = await ha_request(
                    "POST",
                    "/template",
                    json_data={
                        "template": ("{{ states('" + entity_id + "') }}")
                    },
                )
                if result and result != "unknown":
                    return f"{entity_id}: {result}"
            except Exception as fallback_exc:
                logger.debug(
                    "Template fallback failed for %s: %s",
                    entity_id,
                    fallback_exc,
                )
            return (
                f"Entity '{entity_id}' not found. "
                "Check the entity_id with "
                "discover(what='entities')."
            )
        # Connection/timeout/other HA errors: surface clearly
        return f"Home Assistant error: {err_msg}"

    attrs = state.get("attributes", {})
    fn = attrs.get("friendly_name", friendly_name(entity_id))
    st = state.get("state", "unknown")
    domain = entity_id.split(".")[0]

    # Build key attributes based on domain
    extra = _format_domain_attrs(domain, attrs)
    result = f"{fn} ({entity_id}): {st}"
    if extra:
        result += f"\n  {extra}"
    return result


def _format_domain_attrs(domain: str, attrs: dict) -> str:
    """Format key attributes based on entity domain."""
    parts = []
    if domain == "climate":
        if "temperature" in attrs:
            parts.append(f"target: {attrs['temperature']}°")
        if "current_temperature" in attrs:
            parts.append(f"current: {attrs['current_temperature']}°")
        if "hvac_action" in attrs:
            parts.append(f"action: {attrs['hvac_action']}")
    elif domain == "light":
        if attrs.get("brightness") is not None:
            pct = round(attrs["brightness"] / 255 * 100)
            parts.append(f"brightness: {pct}%")
        if attrs.get("color_temp_kelvin") is not None:
            parts.append(f"color_temp: {attrs['color_temp_kelvin']}K")
    elif domain == "media_player":
        if attrs.get("media_title") is not None:
            parts.append(f"playing: {attrs['media_title']}")
        if attrs.get("volume_level") is not None:
            vol = round(attrs["volume_level"] * 100)
            parts.append(f"volume: {vol}%")
        if "source" in attrs:
            parts.append(f"source: {attrs['source']}")
    elif domain == "vacuum":
        if "battery_level" in attrs:
            parts.append(f"battery: {attrs['battery_level']}%")
        if "fan_speed" in attrs:
            parts.append(f"fan_speed: {attrs['fan_speed']}")
    elif domain == "cover":
        if "current_position" in attrs:
            parts.append(f"position: {attrs['current_position']}%")
    elif domain in ("sensor", "binary_sensor"):
        if "unit_of_measurement" in attrs:
            parts.append(f"unit: {attrs['unit_of_measurement']}")
        if "device_class" in attrs:
            parts.append(f"class: {attrs['device_class']}")
    return ", ".join(parts)


async def _query_template(template: str) -> str:
    """Evaluate a Jinja2 template against HA."""
    try:
        result = await ha_request(
            "POST",
            "/template",
            json_data={"template": template},
        )
    except HomeAssistantError as exc:
        return f"Home Assistant error: {exc}"
    if isinstance(result, str):
        return result
    return str(result)


# ------------------------------------------------------------------
# do()
# ------------------------------------------------------------------


@tool(
    description=(
        "Call ANY Home Assistant service. "
        "Use discover(what='services', filter_str='domain') "
        "to see available services and their parameters."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Service domain, e.g. 'light', 'climate', "
                    "'vacuum', 'script'."
                ),
            },
            "service": {
                "type": "string",
                "description": (
                    "Service name, e.g. 'turn_on', "
                    "'set_temperature', 'start'."
                ),
            },
            "targets": {
                "type": "object",
                "description": (
                    'Target(s): {"entity_id": "..."} or '
                    '{"area_id": "..."} or '
                    '{"device_id": "..."}.'
                ),
            },
            "data": {
                "type": "object",
                "description": (
                    "Service-specific parameters, e.g. "
                    '{"brightness_pct": 50}. '
                    "For protected domains (lock, alarm, cover, camera), "
                    "first call returns confirmation_token. Second call "
                    "must include 'confirmed': true and "
                    "'confirmation_token': '<token>'."
                ),
            },
        },
        "required": ["domain", "service"],
    },
)
async def do(
    domain: str,
    service: str,
    targets: dict = None,
    data: dict = None,
) -> str:
    """Call any Home Assistant service with verification."""
    try:
        # Two-step confirmation for protected domains: first call returns
        # a short-lived token; second call must include that token.
        confirmed = bool(data and data.get("confirmed"))
        confirmation_token = (data or {}).get("confirmation_token") if data else None
        if isinstance(confirmation_token, str):
            confirmation_token = confirmation_token.strip() or None

        # Security gate for protected domains
        if domain in PROTECTED_DOMAINS:
            token_valid = _consume_confirmation_token(confirmation_token)
            if confirmed and token_valid:
                # Valid two-step confirmation: strip confirmation fields
                data = {
                    k: v
                    for k, v in (data or {}).items()
                    if k not in ("confirmed", "confirmation_token")
                }
                if not data:
                    data = None
            elif confirmed and not token_valid:
                # Bypass attempt: confirmed=true but no valid token
                entity = targets.get("entity_id", "") if targets else ""
                token = _create_confirmation_token()
                return (
                    f"CONFIRMATION REQUIRED: About to call {domain}.{service}"
                    + (f" on {entity}" if entity else "")
                    + ". This is a sensitive action. "
                    "You must first call do() without confirmed to get "
                    "a confirmation_token. Then call do() again with "
                    "'confirmed': true and 'confirmation_token': '<token>' in data. "
                    f"confirmation_token: {token}"
                )
            else:
                # First call: no confirmation yet
                entity = targets.get("entity_id", "") if targets else ""
                token = _create_confirmation_token()
                return (
                    f"CONFIRMATION REQUIRED: About to call {domain}.{service}"
                    + (f" on {entity}" if entity else "")
                    + ". This is a sensitive action. "
                    "Please confirm by calling do() again with the same "
                    "parameters and add 'confirmed': true and "
                    "'confirmation_token': '<token>' in data. "
                    f"confirmation_token: {token}"
                )

        # Build the payload
        payload = {}
        if targets:
            payload.update(targets)
        if data:
            payload.update(data)

        # Extract targets for logging and verification
        entity_id = ""
        area_id = ""
        floor_id = ""
        if targets:
            entity_id = targets.get("entity_id", "")
            area_id = targets.get("area_id", "")
            floor_id = targets.get("floor_id", "")
        # Log area/floor targeting for diagnostics (basement-lights-type issues)
        if area_id or floor_id:
            logger.info(
                "do() area/floor target: domain=%s service=%s area_id=%s floor_id=%s",
                domain,
                service,
                area_id or "(none)",
                floor_id or "(none)",
            )
        # Make the service call
        await ha_request(
            "POST",
            f"/services/{domain}/{service}",
            json_data=payload or None,
        )

        # Wait for state to settle
        await asyncio.sleep(0.5)

        # Verify by reading back entity state
        if entity_id:
            status = await verify_generic(entity_id)
            return f"Done. {status}"

        if area_id or floor_id:
            return await _verify_area_or_floor(
                domain, service, area_id, floor_id
            )

        return f"Done. Called {domain}.{service}."

    except Exception as e:
        entity_id = ""
        if targets:
            entity_id = targets.get("entity_id", "")
        return format_ha_error(
            entity_id or f"{domain}.{service}", domain, e
        )


async def _verify_area_or_floor(
    domain: str,
    service: str,
    area_id: str,
    floor_id: str,
) -> str:
    """Verify area/floor-based service call by listing
    affected entities."""
    try:
        # Sanitize inputs to prevent Jinja2 template
        # injection — only allow alphanumerics, underscores,
        # and hyphens in area/floor/domain identifiers
        import re

        _ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
        for name, val in [
            ("domain", domain),
            ("area_id", area_id),
            ("floor_id", floor_id),
        ]:
            if val and not _ID_RE.match(val):
                return (
                    f"Invalid {name}: '{val}'. "
                    "Only letters, digits, underscores, "
                    "and hyphens are allowed."
                )

        # Build a Jinja2 template to list entities of the
        # target domain in the area or on the floor
        if area_id:
            template = (
                "{%- for e in area_entities('" + area_id + "') "
                "if e.startswith('" + domain + ".') -%}"
                "{{ e }}|"
                "{{ states[e].state }}|"
                "{{ state_attr(e, 'friendly_name')"
                " or e }}\n"
                "{%- endfor -%}"
            )
            label = area_id
        else:
            # Floor: get all areas on the floor,
            # then entities in those areas
            template = (
                "{%- for a in floor_areas('" + floor_id + "') -%}"
                "{%- for e in area_entities(a) "
                "if e.startswith('" + domain + ".') -%}"
                "{{ e }}|"
                "{{ states[e].state }}|"
                "{{ state_attr(e, 'friendly_name')"
                " or e }}\n"
                "{%- endfor -%}"
                "{%- endfor -%}"
            )
            label = floor_id

        raw = await ha_request(
            "POST",
            "/template",
            json_data={"template": template},
        )

        if not isinstance(raw, str):
            return f"Done. Called {domain}.{service} on {label}."

        lines = [
            ln.strip()
            for ln in raw.strip().split("\n")
            if ln.strip() and "|" in ln
        ]
        if not lines:
            msg = (
                f"Done. Called {domain}.{service} "
                f"on {label} (no {domain} entities "
                f"found in this area)."
            )
            logger.info(
                "do() area/floor verify: NO ENTITIES - %s (area_id=%s floor_id=%s)",
                msg,
                area_id or "(none)",
                floor_id or "(none)",
            )
            return msg

        parts = []
        for line in lines:
            segs = line.split("|", 2)
            if len(segs) >= 3:
                name = segs[2].strip()
                state = segs[1].strip()
                parts.append(f"{name}: {state}")
            elif len(segs) == 2:
                parts.append(f"{segs[0]}: {segs[1]}")

        summary = ", ".join(parts)
        return f"Done. {summary}"

    except Exception:
        logger.debug("Area/floor verify failed", exc_info=True)
        return f"Done. Called {domain}.{service} on {area_id or floor_id}."


# ------------------------------------------------------------------
# history()
# ------------------------------------------------------------------


@tool(
    description=(
        "Get state change history or logbook entries for an entity."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Entity to get history for, e.g. 'light.kitchen'."
                ),
            },
            "hours": {
                "type": "integer",
                "description": (
                    "How many hours of history to fetch (default 24)."
                ),
                "default": 24,
            },
            "mode": {
                "type": "string",
                "enum": ["changes", "logbook"],
                "description": (
                    "'changes' for state transitions, "
                    "'logbook' for human-readable event log."
                ),
                "default": "changes",
            },
        },
        "required": ["entity_id"],
    },
)
async def history(
    entity_id: str,
    hours: int = 24,
    mode: str = "changes",
) -> str:
    """Get state change history or logbook entries."""
    try:
        if mode == "logbook":
            return await _history_logbook(entity_id, hours)
        else:
            return await _history_changes(entity_id, hours)
    except Exception as e:
        return f"Error fetching history for {entity_id}: {e}"


async def _history_changes(entity_id: str, hours: int) -> str:
    """Fetch state change history for an entity."""
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    result = await ha_request(
        "GET",
        f"/history/period/{start_str}"
        f"?filter_entity_id={entity_id}"
        "&minimal_response&no_attributes",
    )

    if (
        not result
        or not isinstance(result, list)
        or len(result) == 0
        or not result[0]
    ):
        return f"No state changes for {entity_id} in the last {hours}h."

    entries = result[0]
    lines = []
    prev_state = None
    for entry in entries:
        st = entry.get("state", "unknown")
        ts = entry.get("last_changed", "")
        if st == prev_state:
            continue
        # Format timestamp
        ts_short = _format_timestamp(ts)
        if prev_state is not None:
            lines.append(f"  {ts_short}: {prev_state} → {st}")
        else:
            lines.append(f"  {ts_short}: {st}")
        prev_state = st

    if not lines:
        return f"No state changes for {entity_id} in the last {hours}h."

    fn = friendly_name(entity_id)
    return (
        f"History for {fn} ({entity_id}), "
        f"last {hours}h ({len(lines)} changes):\n" + "\n".join(lines)
    )


async def _history_logbook(entity_id: str, hours: int) -> str:
    """Fetch logbook entries for an entity."""
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    result = await ha_request(
        "GET",
        f"/logbook/{start_str}?entity={entity_id}",
    )

    if not result or not isinstance(result, list):
        return f"No logbook entries for {entity_id} in the last {hours}h."

    lines = []
    for entry in result[:50]:
        name = entry.get("name", entity_id)
        message = entry.get("message", "")
        state = entry.get("state", "")
        ts = entry.get("when", "")
        ts_short = _format_timestamp(ts)

        if message:
            lines.append(f"  {ts_short}: {name} {message}")
        elif state:
            lines.append(f"  {ts_short}: {name} → {state}")
        else:
            lines.append(f"  {ts_short}: {name}")

    if not lines:
        return f"No logbook entries for {entity_id} in the last {hours}h."

    fn = friendly_name(entity_id)
    header = f"Logbook for {fn} ({entity_id}), last {hours}h"
    if len(result) > 50:
        header += f" (showing 50 of {len(result)})"
    header += ":"
    return header + "\n" + "\n".join(lines)


def _format_timestamp(ts: str) -> str:
    """Convert ISO timestamp to short readable format."""
    if not ts:
        return "?"
    try:
        # Handle various ISO formats
        ts_clean = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_clean)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ts[:19] if len(ts) > 19 else ts

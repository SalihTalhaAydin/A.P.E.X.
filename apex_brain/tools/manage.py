"""
System management tool — Supervisor API operations.
Backups, updates, restarts, add-on lifecycle, health, logs.
All calls go to http://supervisor/<endpoint> with SUPERVISOR_TOKEN.

Implements tiered confirmation system:
  Tier 0 (Safe): backup/create, backup/list, health, logs
  Tier 1 (Disruptive): update/*, restart/*, install, backup/delete
  Tier 2 (Destructive): backup/restore
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx
from tools.base import tool

logger = logging.getLogger(__name__)

# Shared HTTP client for Supervisor API calls
_supervisor_client = httpx.AsyncClient(
    timeout=30.0,
    limits=httpx.Limits(
        max_connections=10,
        max_keepalive_connections=5,
    ),
)

# Supervisor base URL (only available inside HAOS add-on)
_SUPERVISOR_URL = "http://supervisor"

# --- Tier classification ---

_TIER_0_SAFE: set[tuple[str, str]] = {
    ("backup", "create"),
    ("backup", "list"),
    ("health", ""),
    ("logs", ""),
    ("logs", "core"),
    ("logs", "supervisor"),
}

_TIER_2_DESTRUCTIVE: set[tuple[str, str]] = {
    ("backup", "restore"),
}

# Everything not in Tier 0 or Tier 2 is Tier 1 (disruptive)


def _get_tier(action: str, target: str) -> int:
    """Determine the confirmation tier for an operation."""
    key = (action, target)
    # Also match by action alone for logs with any target
    if key in _TIER_0_SAFE:
        return 0
    if action == "logs":
        return 0
    if key in _TIER_2_DESTRUCTIVE:
        return 2
    return 1


def _get_supervisor_token() -> str | None:
    """Get the Supervisor API token."""
    return os.environ.get("SUPERVISOR_TOKEN", "") or None


def _supervisor_headers() -> dict:
    """Build headers for Supervisor API calls."""
    token = _get_supervisor_token()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _supervisor_request(
    method: str,
    path: str,
    json_data: dict | None = None,
    as_text: bool = False,
) -> dict | str:
    """Make a request to the Supervisor API."""
    token = _get_supervisor_token()
    if not token:
        return {
            "error": (
                "Supervisor API unavailable. "
                "SUPERVISOR_TOKEN is not set. "
                "This operation only works inside "
                "a Home Assistant add-on."
            )
        }

    url = f"{_SUPERVISOR_URL}{path}"
    headers = _supervisor_headers()
    logger.debug("Supervisor %s %s", method, url)

    try:
        response = await _supervisor_client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
        )
        if as_text:
            if not response.is_success:
                return f"Error fetching text: HTTP {response.status_code}"
            return response.text
        response.raise_for_status()
        ct = response.headers.get("content-type", "")
        if "application/json" in ct:
            return response.json()
        return response.text or ""
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        body = (e.response.text or "")[:300]
        return {"error": f"Supervisor API error {code}: {body}"}
    except httpx.ConnectError:
        return {
            "error": (
                "Cannot connect to Supervisor API. "
                "Are you running inside HAOS?"
            )
        }
    except httpx.TimeoutException:
        return {"error": "Supervisor API request timed out."}


def _confirmation_prompt(
    action: str,
    target: str,
    tier: int,
    detail: str = "",
) -> str:
    """Build a confirmation prompt for Tier 1/2 ops."""
    labels = {1: "DISRUPTIVE", 2: "DESTRUCTIVE"}
    label = labels.get(tier, "REQUIRES CONFIRMATION")
    msg = (
        f"⚠ {label} OPERATION: {action} {target}\n"
        f"{detail}\n"
        f"To execute, call manage() again with "
        f'config={{"confirmed": true}}'
    )
    return msg.strip()


# --- Tier detail generators ---

_TIER_DETAILS: dict[tuple[str, str], str] = {
    ("update", "core"): (
        "This will update HA Core and trigger a restart. "
        "Expect ~30 seconds of downtime."
    ),
    ("update", "os"): (
        "This will update the HAOS operating system "
        "and trigger a full reboot."
    ),
    ("restart", "core"): (
        "This will restart HA Core. "
        "Expect ~30 seconds of downtime. "
        "All automations will briefly stop."
    ),
    ("restart", "supervisor"): (
        "This will restart the HA Supervisor. "
        "Add-ons may be briefly interrupted."
    ),
    ("backup", "restore"): (
        "This will WIPE the current HA state "
        "and restore from a backup snapshot. "
        "All changes since the backup will be lost."
    ),
    ("backup", "delete"): (
        "This will permanently delete the backup. This cannot be undone."
    ),
}


def _get_detail(action: str, target: str, config: dict | None) -> str:
    """Get a human-readable detail string for a confirm."""
    # Check for exact match first
    detail = _TIER_DETAILS.get((action, target), "")
    if detail:
        return detail
    # Addon-specific messages
    if target.startswith("addon:"):
        slug = target.split(":", 1)[1]
        if action == "update":
            return f"This will update add-on '{slug}' and restart it."
        if action == "restart":
            return (
                f"This will restart add-on '{slug}'. "
                f"It will be briefly unavailable."
            )
        if action == "install":
            return f"This will install add-on '{slug}' on your system."
    return f"This will execute: {action} {target}"


# --- Route handlers ---


async def _handle_backup(target: str, config: dict | None) -> str:
    """Handle backup operations."""
    config = config or {}

    if target == "create":
        name = config.get("name", "")
        payload = {}
        if name:
            payload["name"] = name
        result = await _supervisor_request(
            "POST", "/backups/new/full", payload or None
        )
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        data = result.get("data", result)
        slug = data.get("slug", "unknown")
        return f"Backup created successfully. Slug: {slug}"

    if target == "list":
        result = await _supervisor_request("GET", "/backups")
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        data = result.get("data", result)
        backups = data.get("backups", [])
        if not backups:
            return "No backups found."
        lines = ["Available backups:"]
        for b in backups:
            name = b.get("name", "unnamed")
            slug = b.get("slug", "?")
            date = b.get("date", "?")
            btype = b.get("type", "?")
            lines.append(f"  - {name} ({slug}) [{btype}] {date}")
        return "\n".join(lines)

    if target == "restore":
        backup_id = config.get("backup_id", "")
        if not backup_id:
            return "Error: config.backup_id is required."
        if not re.match(r"^[\w.-]+$", backup_id):
            return "Error: invalid backup_id format."
        result = await _supervisor_request(
            "POST", f"/backups/{backup_id}/restore"
        )
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return (
            f"Backup '{backup_id}' restore initiated. System will restart."
        )

    if target == "delete":
        backup_id = config.get("backup_id", "")
        if not backup_id:
            return "Error: config.backup_id is required."
        if not re.match(r"^[\w.-]+$", backup_id):
            return "Error: invalid backup_id format."
        result = await _supervisor_request(
            "DELETE", f"/backups/{backup_id}"
        )
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return f"Backup '{backup_id}' deleted."

    return f"Unknown backup target: {target}"


async def _handle_update(target: str, config: dict | None) -> str:
    """Handle update operations."""
    if target == "core":
        result = await _supervisor_request("POST", "/core/update")
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return "HA Core update initiated."

    if target == "os":
        result = await _supervisor_request("POST", "/os/update")
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return "HAOS update initiated."

    if target.startswith("addon:"):
        slug = target.split(":", 1)[1]
        result = await _supervisor_request(
            "POST", f"/addons/{slug}/update"
        )
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return f"Add-on '{slug}' update initiated."

    return f"Unknown update target: {target}"


async def _handle_restart(target: str, config: dict | None) -> str:
    """Handle restart operations."""
    if target == "core":
        result = await _supervisor_request("POST", "/core/restart")
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return "HA Core restart initiated."

    if target == "supervisor":
        result = await _supervisor_request("POST", "/supervisor/restart")
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return "Supervisor restart initiated."

    if target.startswith("addon:"):
        slug = target.split(":", 1)[1]
        result = await _supervisor_request(
            "POST", f"/addons/{slug}/restart"
        )
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        return f"Add-on '{slug}' restart initiated."

    return f"Unknown restart target: {target}"


async def _handle_install(target: str, config: dict | None) -> str:
    """Handle add-on installation."""
    if not target.startswith("addon:"):
        return "Error: target must be 'addon:<slug>' for install action."
    slug = target.split(":", 1)[1]
    result = await _supervisor_request("POST", f"/addons/{slug}/install")
    if isinstance(result, dict) and "error" in result:
        return result["error"]
    return f"Add-on '{slug}' installation initiated."


async def _handle_health(target: str, config: dict | None) -> str:
    """Handle health/system stats."""
    sections = []

    core = await _supervisor_request("GET", "/core/info")
    if isinstance(core, dict) and "error" not in core:
        data = core.get("data", core)
        sections.append(
            f"HA Core: v{data.get('version', '?')} "
            f"({data.get('machine', '?')})"
        )

    os_info = await _supervisor_request("GET", "/os/info")
    if isinstance(os_info, dict) and "error" not in os_info:
        data = os_info.get("data", os_info)
        sections.append(f"HAOS: v{data.get('version', '?')}")

    sup = await _supervisor_request("GET", "/supervisor/info")
    if isinstance(sup, dict) and "error" not in sup:
        data = sup.get("data", sup)
        sections.append(f"Supervisor: v{data.get('version', '?')}")

    if not sections:
        err = ""
        for r in [core, os_info, sup]:
            if isinstance(r, dict) and "error" in r:
                err = r["error"]
                break
        return err or "Unable to retrieve system health."

    return "System Health:\n" + "\n".join(f"  {s}" for s in sections)


async def _handle_logs(target: str, config: dict | None) -> str:
    """Handle log retrieval."""
    if target in ("core", ""):
        path = "/core/logs"
    elif target == "supervisor":
        path = "/supervisor/logs"
    elif target.startswith("addon:"):
        slug = target.split(":", 1)[1]
        path = f"/addons/{slug}/logs"
    else:
        return f"Unknown logs target: {target}"

    result = await _supervisor_request("GET", path, as_text=True)
    if isinstance(result, dict) and "error" in result:
        return result["error"]
    # Truncate to last 50 lines
    lines = str(result).strip().splitlines()
    if len(lines) > 50:
        lines = lines[-50:]
    return "\n".join(lines)


# --- Action router ---

_HANDLERS = {
    "backup": _handle_backup,
    "update": _handle_update,
    "restart": _handle_restart,
    "install": _handle_install,
    "health": _handle_health,
    "logs": _handle_logs,
}


# Module-level audit store reference (injected at startup)
_audit_store = None


def set_audit_store(store) -> None:
    """Inject the audit store at application startup."""
    global _audit_store
    _audit_store = store


@tool(
    description=(
        "Manage HA system: backups, add-ons, updates, "
        "and system health. Safe operations execute "
        "immediately. Destructive operations require "
        "confirmation (pass config={'confirmed': true})."
    )
)
async def manage(
    action: str,
    target: str = "",
    config: dict | None = None,
    session_id: str = "default",
) -> str:
    """Supervisor API operations with tiered confirmation.

    action: backup, update, restart, install, health, logs
    target: core, os, supervisor, addon:<slug>, create,
            list, restore, delete, or empty
    config: extra config (backup name, backup_id, etc.)
            Use config={"confirmed": true} to confirm
            destructive operations.
    session_id: originating session for audit logging.
    """
    config = config or {}
    tier = _get_tier(action, target)

    # Session-based escalation: webhook sessions
    # are restricted to Tier 0 only
    if session_id == "apex_events" and tier > 0:
        msg = (
            f"Operation '{action} {target}' requires "
            f"Tier {tier} access. Webhook sessions "
            f"(apex_events) are restricted to safe "
            f"(Tier 0) operations only. Use a direct "
            f"conversation to perform this action."
        )
        if _audit_store:
            await _audit_store.log(
                tool="manage",
                action=action,
                target=target,
                config=config,
                result="denied",
                session_id=session_id,
                user_approved=False,
            )
        return msg

    # Tier 1/2: require confirmation
    if tier > 0 and not config.get("confirmed"):
        detail = _get_detail(action, target, config)
        prompt = _confirmation_prompt(action, target, tier, detail)
        if _audit_store:
            await _audit_store.log(
                tool="manage",
                action=action,
                target=target,
                config=config,
                result="confirmation_prompted",
                session_id=session_id,
                user_approved=False,
            )
        return prompt

    # Execute the operation
    handler = _HANDLERS.get(action)
    if not handler:
        return (
            f"Unknown action: {action}. "
            f"Valid actions: "
            f"{', '.join(sorted(_HANDLERS.keys()))}"
        )

    result = await handler(target, config)

    # Audit log
    if _audit_store:
        await _audit_store.log(
            tool="manage",
            action=action,
            target=target,
            config=config,
            result="executed",
            session_id=session_id,
            user_approved=tier > 0,
        )

    return result

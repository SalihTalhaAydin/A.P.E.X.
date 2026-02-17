"""
Presence tool for Home Assistant.
Queries person entities to determine who is home or away.
Also exposes a helper for the context builder to inject
presence into the system prompt automatically.
"""

import httpx

from tools.base import tool
from tools.ha_helpers import (
    format_ha_error,
    ha_request,
)


async def get_presence_summary() -> str:
    """Fetch all person entities and return a summary.

    Used by the context builder to inject presence
    into the system prompt every turn.
    Returns '' if no person entities or on error.
    """
    try:
        states = await ha_request("GET", "/states")
        persons = [
            s
            for s in states
            if s["entity_id"].startswith("person.")
        ]
        if not persons:
            return ""

        lines = []
        for p in persons:
            name = p.get("attributes", {}).get(
                "friendly_name",
                p["entity_id"].split(".")[-1].title(),
            )
            state = p.get("state", "unknown")
            lines.append(f"{name}: {state}")

        return ", ".join(lines)
    except Exception:
        return ""


@tool(
    description=(
        "Check who is home or away. Queries Home "
        "Assistant person entities for presence status. "
        "Optionally filter by a specific person's name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "person": {
                "type": "string",
                "description": (
                    "Person name to filter by "
                    "(e.g. 'Salih'). Optional."
                ),
            },
        },
        "required": [],
    },
)
async def get_presence(person: str = "") -> str:
    """Check who is home or away."""
    try:
        states = await ha_request("GET", "/states")
        persons = [
            s
            for s in states
            if s["entity_id"].startswith("person.")
        ]

        if person:
            person_lower = person.lower()
            persons = [
                p
                for p in persons
                if person_lower
                in p.get("attributes", {})
                .get("friendly_name", "")
                .lower()
            ]

        if not persons:
            suffix = (
                f" matching '{person}'"
                if person
                else ""
            )
            return (
                f"No person entities found{suffix}."
            )

        lines = []
        for p in persons:
            attrs = p.get("attributes", {})
            name = attrs.get(
                "friendly_name",
                p["entity_id"]
                .split(".")[-1]
                .title(),
            )
            state = p.get("state", "unknown")
            line = f"- {name}: {state}"
            if "source" in attrs:
                line += f" (via {attrs['source']})"
            lines.append(line)

        return "\n".join(lines)

    except httpx.HTTPStatusError as e:
        return format_ha_error(
            "person.*", "person", e
        )
    except Exception as e:
        return f"Error checking presence: {e}"

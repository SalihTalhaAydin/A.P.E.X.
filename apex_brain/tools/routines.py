"""
Routines Tool - Named multi-step sequences.

Stores routine definitions in the dedicated RoutineStore with
lifecycle tracking (use_count, last_used_at) and lets the AI
execute them by chaining tool calls naturally.
"""

import logging

from tools.base import tool

logger = logging.getLogger(__name__)

# Set during server startup
_routine_store = None


def set_routine_store(store):
    """Called during server startup with the RoutineStore instance."""
    global _routine_store
    _routine_store = store


@tool(
    description=(
        "Define a routine: a named sequence of steps "
        "Apex should execute. Steps are natural "
        "language descriptions of actions. Example: "
        "name='good morning', "
        "steps='Turn on kitchen lights to 80%. "
        "Set thermostat to 72. Get the weather. "
        "Read today calendar.'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Routine name, e.g. "
                    "'good morning', 'bedtime', "
                    "'movie mode'."
                ),
            },
            "steps": {
                "type": "string",
                "description": (
                    "Steps to execute, as natural "
                    "language. Separate steps with "
                    "periods or newlines."
                ),
            },
            "trigger": {
                "type": "string",
                "description": (
                    "Optional trigger hint: "
                    "'manual', 'morning', "
                    "'bedtime', 'arrival'."
                ),
            },
        },
        "required": ["name", "steps"],
    },
)
async def define_routine(
    name: str,
    steps: str,
    trigger: str = "",
) -> str:
    """Store a routine definition."""
    if not _routine_store:
        return "Routine system not initialized."

    # Search-before-create: check for existing routine
    existing = await _routine_store.get_routine(name)
    if existing:
        return (
            f"A routine named '{name}' already exists "
            f"(used {existing['use_count']} times). "
            f"Steps: {', '.join(existing['steps'])}. "
            f"Delete it first with delete_routine or use a different name."
        )

    # Split on newlines and ". " (period-space) to avoid splitting numbers
    # like "72.5" or abbreviations. (BUG-154)
    parts: list[str] = []
    for line in steps.split("\n"):
        for p in line.split(". "):
            p = p.strip()
            if p:
                parts.append(p)
    step_list = parts
    await _routine_store.save_routine(
        name, step_list, trigger=trigger
    )
    return f"Got it. Routine '{name}' saved with {len(step_list)} steps."


@tool(
    description="List all defined routines with usage statistics.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def list_routines() -> str:
    """List all stored routines."""
    if not _routine_store:
        return "Routine system not initialized."

    routines = await _routine_store.list_routines()

    if not routines:
        return "No routines defined yet."

    lines = []
    for r in routines:
        steps_str = ", ".join(r["steps"])
        used = f"(used {r['use_count']}x"
        if r.get("last_used_at"):
            used += f", last: {r['last_used_at'][:10]}"
        used += ")"
        lines.append(f"- {r['name']}: {steps_str} {used}")

    return f"{len(lines)} routine(s):\n" + "\n".join(lines)


@tool(
    description=(
        "Run a named routine. Apex retrieves the "
        "steps and executes each one using the "
        "appropriate tools."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Routine name to run, "
                    "e.g. 'good morning'."
                ),
            },
        },
        "required": ["name"],
    },
)
async def run_routine(name: str) -> str:
    """Retrieve routine steps for AI execution."""
    if not _routine_store:
        return "Routine system not initialized."

    routine = await _routine_store.get_routine(name)

    if not routine:
        available = await _routine_store.list_routines()
        names = ", ".join(r["name"] for r in available) or "none"
        return (
            f"No routine named '{name}' found. "
            f"Available: {names}"
        )

    # Track usage
    await _routine_store.record_usage(name)

    steps = routine["steps"]
    use_count = routine["use_count"] + 1
    steps_text = "\n".join(
        f"  {i + 1}. {s}" for i, s in enumerate(steps)
    )
    return (
        f'Routine "{routine["name"]}" (used {use_count} times) steps:\n'
        f"{steps_text}\n\n"
        "Execute each step now using your tools."
    )


@tool(
    description="Delete a routine by name.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Routine name to delete."
                ),
            },
        },
        "required": ["name"],
    },
)
async def delete_routine(name: str) -> str:
    """Delete a routine."""
    if not _routine_store:
        return "Routine system not initialized."

    deleted = await _routine_store.delete_routine(name)
    if deleted:
        return f"Done. Deleted routine '{name}'."
    return f"No routine named '{name}' found."

"""
Routines Tool - Named multi-step sequences.
Stores routine definitions in the knowledge store and
lets the AI execute them by chaining tool calls naturally.
"""

from tools.base import tool

# Set during server startup (same pattern as knowledge.py)
_knowledge_store = None


def set_knowledge_store(store):
    """Called during server startup."""
    global _knowledge_store
    _knowledge_store = store


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
    if not _knowledge_store:
        return "Memory system not initialized."

    value = steps
    if trigger:
        value = f"[trigger: {trigger}] {steps}"

    await _knowledge_store.store_fact(
        category="routine",
        key=name.lower().strip(),
        value=value,
        confidence=1.0,
        source="explicit",
    )
    return f"Got it. Routine '{name}' saved."


@tool(
    description="List all defined routines.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def list_routines() -> str:
    """List all stored routines."""
    if not _knowledge_store:
        return "Memory system not initialized."

    facts = await _knowledge_store.get_all_facts(
        category="routine", limit=50
    )

    if not facts:
        return "No routines defined yet."

    lines = []
    for f in facts:
        lines.append(
            f"- {f['key']}: {f['value']}"
        )

    return (
        f"{len(lines)} routine(s):\n"
        + "\n".join(lines)
    )


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
    if not _knowledge_store:
        return "Memory system not initialized."

    name_lower = name.lower().strip()

    # Try exact match first
    facts = await _knowledge_store.get_all_facts(
        category="routine", limit=50
    )
    match = None
    for f in facts:
        if f["key"] == name_lower:
            match = f
            break

    if not match:
        # Fuzzy: try keyword search
        results = (
            await _knowledge_store.search_keyword(
                query=name_lower, limit=5
            )
        )
        for r in results:
            if r.get("category") == "routine":
                match = r
                break

    if not match:
        available = ", ".join(
            f["key"] for f in facts
        )
        return (
            f"No routine named '{name}' found. "
            f"Available: {available or 'none'}"
        )

    steps = match["value"]
    return (
        f'Routine "{match["key"]}" steps:\n'
        f"{steps}\n\n"
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
    if not _knowledge_store:
        return "Memory system not initialized."

    deleted = await _knowledge_store.delete_fact(
        name.lower().strip()
    )
    if deleted:
        return f"Done. Deleted routine '{name}'."
    return f"No routine named '{name}' found."

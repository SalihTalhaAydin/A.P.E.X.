"""
Knowledge Tools - Explicit memory commands.
For when you DO want to say "remember this" or "what do you know about X".
Backed by Apex's memory system (same store as auto-extracted facts).
"""

from tools.base import tool

# These will be set during server startup (avoids circular imports)
_knowledge_store = None


def set_knowledge_store(store):
    """Called during server startup to inject the knowledge store."""
    global _knowledge_store
    _knowledge_store = store


@tool(
    description=(
            "Store information the user explicitly asks to remember. "
        "Use when the user says 'remember X', 'save this', 'note that', etc. "
        "Apex will store this in its personal knowledge base."
    ),
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Short label (e.g. 'WiFi password', 'dentist appointment', 'Sarah birthday')",
            },
            "value": {
                "type": "string",
                "description": "The information to store",
            },
        },
        "required": ["key", "value"],
    },
)
async def remember(key: str, value: str) -> str:
    """Store a fact the user explicitly asked to remember."""
    if not _knowledge_store:
        return "Memory system not initialized."
    await _knowledge_store.store_fact(
        category="explicit",
        key=key,
        value=value,
        confidence=1.0,
        source="explicit",
    )
    return f"Got it. I'll remember that."


@tool(
    description=(
            "Search Apex's memory for stored information. "
        "Use when the user asks 'do you remember X', 'what do you know about X', "
        "'what was that thing about X', etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for in memory",
            },
        },
        "required": ["query"],
    },
)
async def recall(query: str) -> str:
    """Search memory for information matching the query."""
    if not _knowledge_store:
        return "Memory system not initialized."

    # Try semantic search first
    results = await _knowledge_store.search_semantic(query=query, limit=10)

    if not results:
        return "I don't have anything stored about that."

    lines = []
    for r in results:
        category = r.get("category", "")
        key = r["key"]
        value = r["value"]
        cat_label = f" [{category}]" if category else ""
        lines.append(f"- {key}: {value}{cat_label}")

    return "\n".join(lines)


@tool(
    description=(
        "Remove information from memory. "
        "Use when the user says 'forget about X', 'delete X', 'remove X from memory'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The key/topic to forget",
            },
        },
        "required": ["key"],
    },
)
async def forget(key: str) -> str:
    """Delete a fact from memory."""
    if not _knowledge_store:
        return "Memory system not initialized."
    deleted = await _knowledge_store.delete_fact(key)
    if deleted:
        return f"Done. Forgot about '{key}'."
    return f"I don't have anything stored about '{key}'."

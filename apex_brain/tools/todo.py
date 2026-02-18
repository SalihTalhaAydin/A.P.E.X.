"""
Todo / Shopping list tool for Home Assistant.
Supports view, add, complete, remove, and clear-completed actions.
"""

import logging

import httpx

from tools.base import tool
from tools.ha_helpers import (
    format_ha_error,
    ha_request,
)

logger = logging.getLogger(__name__)


async def _get_items(entity_id: str) -> list[dict]:
    """Fetch todo items for a list entity."""
    resp = await ha_request(
        "POST",
        "/services/todo/get_items",
        json_data={"entity_id": entity_id},
        return_response=True,
    )
    # Response: {entity_id: {"items": [...]}}
    if isinstance(resp, dict):
        return (
            resp.get(entity_id, {})
            .get("items", [])
        )
    return []


def _format_items(items: list[dict]) -> str:
    """Format items as a numbered list."""
    if not items:
        return "(empty list)"
    lines = []
    for i, item in enumerate(items, 1):
        status = item.get("status", "")
        name = item.get("summary", "?")
        mark = "x" if status == "completed" else " "
        lines.append(f"  {i}. [{mark}] {name}")
    return "\n".join(lines)


@tool(
    description=(
        "Manage a todo or shopping list: view items, "
        "add, complete, remove, or clear completed. "
        "Lists: 'todo.shopping_list', "
        "'todo.todo_salih', 'todo.todo_alona'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Todo list entity ID, e.g. "
                    "'todo.shopping_list', "
                    "'todo.todo_salih'."
                ),
            },
            "action": {
                "type": "string",
                "enum": [
                    "view",
                    "add",
                    "complete",
                    "remove",
                    "clear_completed",
                ],
                "description": (
                    "Action: view, add, complete, "
                    "remove, or clear_completed."
                ),
            },
            "item": {
                "type": "string",
                "description": (
                    "Item text. Required for add, "
                    "complete, and remove actions."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def manage_todo(
    entity_id: str,
    action: str,
    item: str | None = None,
) -> str:
    """Manage a todo or shopping list."""
    try:
        list_name = (
            entity_id.split(".")[-1]
            .replace("_", " ")
            .title()
        )

        if action == "view":
            items = await _get_items(entity_id)
            return (
                f"{list_name}:\n"
                f"{_format_items(items)}"
            )

        if action in ("add", "complete", "remove"):
            if not item:
                return (
                    f"Please provide an item to "
                    f"{action}."
                )

        if action == "add":
            await ha_request(
                "POST",
                "/services/todo/add_item",
                json_data={
                    "entity_id": entity_id,
                    "item": item,
                },
            )
        elif action == "complete":
            await ha_request(
                "POST",
                "/services/todo/update_item",
                json_data={
                    "entity_id": entity_id,
                    "item": item,
                    "status": "completed",
                },
            )
        elif action == "remove":
            await ha_request(
                "POST",
                "/services/todo/remove_item",
                json_data={
                    "entity_id": entity_id,
                    "item": item,
                },
            )
        elif action == "clear_completed":
            await ha_request(
                "POST",
                "/services/todo/remove_completed_items",
                json_data={
                    "entity_id": entity_id,
                },
            )
        else:
            return f"Unknown todo action: {action}"

        # Re-fetch and show updated list
        items = await _get_items(entity_id)
        verb = {
            "add": "Added",
            "complete": "Completed",
            "remove": "Removed",
            "clear_completed": "Cleared completed",
        }.get(action, "Done")
        suffix = f" '{item}'" if item else ""
        return (
            f"{verb}{suffix}.\n"
            f"{list_name}:\n"
            f"{_format_items(items)}"
        )

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "todo", e)
    except Exception as e:
        return f"Error managing todo list: {e}"

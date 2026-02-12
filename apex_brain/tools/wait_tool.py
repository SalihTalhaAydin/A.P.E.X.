"""
Wait Tool - Pause for a number of seconds between actions.
Enables timed sequences: e.g. turn light off, wait 10s, turn on, repeat.
"""

import asyncio

from tools.base import tool

_MAX_WAIT_SECONDS = 300  # 5 minutes cap to avoid runaway waits


@tool(
    description=(
        "Wait (pause) for a given number of seconds before the next action. "
        "Use this for timed sequences: e.g. turn a light off, wait 10 seconds, "
        "then turn it on. You can call this between control_light or other "
        "tool calls to create delays. Maximum 300 seconds (5 minutes)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": "How many seconds to wait (e.g. 10 for 10 seconds).",
            },
        },
        "required": ["seconds"],
    },
)
async def wait_seconds(seconds: float) -> str:
    """Pause for the given number of seconds, then return. Enables timed sequences."""
    try:
        sec = max(0.0, min(float(seconds), _MAX_WAIT_SECONDS))
        await asyncio.sleep(sec)
        return f"Done. Waited {sec} seconds."
    except Exception as e:
        return f"Wait failed: {e}"

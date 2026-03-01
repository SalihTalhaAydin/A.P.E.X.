"""
Shell tool — Run any command on the system.
Gives Apex full access to the filesystem, package manager,
and anything else available in the container.
"""

import asyncio
import logging

from tools.base import tool

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Run a shell command on the system. Full access: "
        "edit files, install packages, read logs, manage "
        "services, anything. Working directory is /config "
        "(Home Assistant's configuration directory). "
        "Examples: 'cat configuration.yaml', "
        "'ls custom_components/', "
        "'apk add curl', 'find / -name \"*.yaml\"'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The shell command to execute. "
                    "Can be any valid shell command."
                ),
            },
        },
        "required": ["command"],
    },
)
async def shell(command: str) -> str:
    """Execute a shell command and return output."""
    logger.info("Shell: %s", command[:200])

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/config",
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=60
        )
    except TimeoutError:
        return "Command timed out after 60 seconds."
    except Exception as e:
        return f"Shell error: {e}"

    output = ""
    if stdout:
        output += stdout.decode(errors="replace")
    if stderr:
        output += stderr.decode(errors="replace")

    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"

    # Cap output to prevent token explosion
    if len(output) > 10000:
        output = (
            output[:5000] + "\n\n... (truncated) ...\n\n" + output[-5000:]
        )

    return output.strip() or "(no output)"

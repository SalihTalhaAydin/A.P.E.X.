"""Tests for tools.shell (shell command execution tool)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY
from tools.shell import shell


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


# ── 1. Registration ──────────────────────────────────────────────────────


def test_shell_registered_in_tool_registry():
    """shell is registered in TOOL_REGISTRY with the correct name."""
    assert "shell" in TOOL_REGISTRY
    info = TOOL_REGISTRY["shell"]
    assert info["is_async"] is True
    assert "command" in info["parameters"]["properties"]
    assert "command" in info["parameters"]["required"]


# ── 2. Successful command returns stdout ─────────────────────────────────


@pytest.mark.asyncio
async def test_successful_command_returns_stdout():
    """A command that writes to stdout returns that output."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"hello world", b"")
    mock_proc.returncode = 0

    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        return_value=mock_proc,
    ):
        with patch(
            "tools.shell.asyncio.wait_for",
            return_value=(b"hello world", b""),
        ):
            result = await shell(command="echo hello world")

    assert result == "hello world"


# ── 3. stderr is included in output ──────────────────────────────────────


@pytest.mark.asyncio
async def test_stderr_included_in_output():
    """When the command writes to stderr, that text appears in the result."""
    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        new_callable=AsyncMock,
    ) as mock_sub:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_sub.return_value = mock_proc

        with patch(
            "tools.shell.asyncio.wait_for",
            return_value=(b"", b"some warning"),
        ):
            result = await shell(command="warn")

    assert "some warning" in result


# ── 4. Non-zero exit code appends marker ─────────────────────────────────


@pytest.mark.asyncio
async def test_nonzero_exit_code_appended():
    """Non-zero exit code appends '[exit code: N]' to the output."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 2

    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        return_value=mock_proc,
    ):
        with patch(
            "tools.shell.asyncio.wait_for",
            return_value=(b"fail output", b""),
        ):
            result = await shell(command="false")

    assert "[exit code: 2]" in result
    assert "fail output" in result


# ── 5. Timeout returns timeout message ───────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_returns_message():
    """When the command exceeds the 60-second timeout, a timeout message is returned."""
    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        new_callable=AsyncMock,
    ) as mock_sub:
        mock_proc = AsyncMock()
        mock_sub.return_value = mock_proc

        with patch(
            "tools.shell.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            result = await shell(command="sleep 999")

    assert result == "Command timed out after 60 seconds."


# ── 6. Exception during subprocess creation returns error message ────────


@pytest.mark.asyncio
async def test_exception_returns_error_message():
    """An exception raised during subprocess creation returns a Shell error string."""
    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        side_effect=OSError("no such file"),
    ):
        result = await shell(command="nonexistent_binary")

    assert result.startswith("Shell error:")
    assert "no such file" in result


# ── 7. Large output is truncated ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_large_output_truncated():
    """Output exceeding 10 000 characters is truncated with a marker."""
    large_stdout = b"A" * 15000

    mock_proc = AsyncMock()
    mock_proc.returncode = 0

    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        return_value=mock_proc,
    ):
        with patch(
            "tools.shell.asyncio.wait_for",
            return_value=(large_stdout, b""),
        ):
            result = await shell(command="big")

    assert "... (truncated) ..." in result
    # The total length should be roughly 5000 + marker + 5000, not 15 000
    assert len(result) < 15000


# ── 8. Empty output returns "(no output)" ────────────────────────────────


@pytest.mark.asyncio
async def test_empty_output_returns_no_output():
    """When both stdout and stderr are empty, the result is '(no output)'."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0

    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        return_value=mock_proc,
    ):
        with patch(
            "tools.shell.asyncio.wait_for", return_value=(b"", b"")
        ):
            result = await shell(command="true")

    assert result == "(no output)"


# ── 9. Combined stdout + stderr ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_combined_stdout_and_stderr():
    """Both stdout and stderr are concatenated in the result."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0

    with patch(
        "tools.shell.asyncio.create_subprocess_shell",
        return_value=mock_proc,
    ):
        with patch(
            "tools.shell.asyncio.wait_for",
            return_value=(b"out line", b"err line"),
        ):
            result = await shell(command="combo")

    assert "out line" in result
    assert "err line" in result

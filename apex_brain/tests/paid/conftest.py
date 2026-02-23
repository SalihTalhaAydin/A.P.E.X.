"""Paid tests — require RUN_PAID_TESTS=1 to run. Consumes API."""

import os

import pytest

# Load live fixtures only when user has opted in (avoids loading .env otherwise)
if os.environ.get("RUN_PAID_TESTS", "").lower() in ("1", "true", "yes"):
    from tests.conftest_live import *  # noqa: F401, F403


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Skip all paid tests unless RUN_PAID_TESTS is explicitly set.

    Prevents AI (Cursor, Claude, Copilot), CI, and accidental runs from
    consuming API credits. Only the user running RUN_PAID_TESTS=1 may execute.
    """
    opt_in = os.environ.get("RUN_PAID_TESTS", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if opt_in:
        return
    skip = pytest.mark.skip(
        reason="Set RUN_PAID_TESTS=1 to run (consumes API). Never set in CI or via AI."
    )
    for item in items:
        item.add_marker(skip)

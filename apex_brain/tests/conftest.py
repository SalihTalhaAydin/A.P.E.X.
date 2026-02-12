"""
Pytest fixtures for Apex Brain tests.
Ensures apex_brain is on sys.path when running from repo root.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Set test env before any brain imports (so Settings and server use them)
os.environ.setdefault(
    "DB_PATH", os.path.join(tempfile.gettempdir(), "apex_brain_test.db")
)
os.environ.setdefault("HA_URL", "http://127.0.0.1:99999")

# Allow imports of brain, memory, tools when running from repo root
_apex_brain = Path(__file__).resolve().parent.parent
if str(_apex_brain) not in sys.path:
    sys.path.insert(0, str(_apex_brain))


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporary SQLite database path for tests."""
    return str(tmp_path / "test.db")


@pytest.fixture
def mock_embed():
    """Mock embedding function returning a fixed 4-dim vector."""

    async def _embed(_text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    return _embed

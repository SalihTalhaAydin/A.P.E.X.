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


def _text_to_embedding_vector(text: str) -> list[float]:
    """Deterministic embedding-like vector from text. Same text → same vector.
    Texts sharing topic words get similar vectors; unrelated texts get different vectors.
    Uses semantic clusters so e.g. coffee/espresso/cappuccino map to same direction.
    Fast, no API calls. Used by mock_embed fixture."""
    import hashlib

    # Semantic clusters: words in same cluster → similar vector direction.
    # Enables: dedup (espresso≈espresso shots), contradictions (coffee vs tea),
    # and ranking (weather query matches weather fact > coffee fact).
    CLUSTERS = {
        # Beverage cluster (coffee, tea both beverages for contradiction tests)
        "coffee": [1.0, 0.0, 0.0, 0.0],
        "espresso": [1.0, 0.0, 0.0, 0.0],
        "cappuccino": [1.0, 0.0, 0.0, 0.0],
        "tea": [0.95, 0.0, 0.0, 0.0],
        "green": [0.9, 0.0, 0.0, 0.0],
        "matcha": [0.9, 0.0, 0.0, 0.0],
        # Value/old/refined cluster (for duplicate-adopts test)
        "value": [0.0, 0.0, 1.0, 0.0],
        "old": [0.0, 0.0, 1.0, 0.0],
        "refined": [0.0, 0.0, 1.0, 0.0],
        "specific": [0.0, 0.0, 1.0, 0.0],
        # Weather cluster (for ranking: weather query > coffee fact)
        "weather": [0.0, 1.0, 0.0, 0.0],
        "sunny": [0.0, 1.0, 0.0, 0.0],
        "rain": [0.0, 1.0, 0.0, 0.0],
        # Misc
        "test": [0.0, 0.0, 0.0, 1.0],
        "fallback": [0.0, 0.0, 0.0, 1.0],
    }
    dim = 4
    vec = [0.0] * dim
    words = [
        w.lower()
        for w in text.replace(":", " ")
        .replace(".", " ")
        .replace("_", " ")
        .split()
        if len(w) > 0 and w.isalnum()
    ]
    if not words:
        return [0.1, 0.2, 0.3, 0.4]

    cluster_weight = (
        10.0  # Cluster words dominate so similar topics ≈ high sim
    )
    for w in words:
        if w in CLUSTERS:
            for i in range(dim):
                vec[i] += cluster_weight * CLUSTERS[w][i]
        else:
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            for i in range(dim):
                vec[i] += ((h >> (i * 12)) % 4096) / 2048.0 - 1.0

    norm_sq = sum(x * x for x in vec)
    if norm_sq < 1e-12:
        return [0.1, 0.2, 0.3, 0.4]
    norm = norm_sq**0.5
    return [x / norm for x in vec]


@pytest.fixture
def mock_embed():
    """Mock embedding function returning text-dependent 4-dim vectors.

    Uses _text_to_embedding_vector so that:
    - Same text → identical vector (cos sim = 1.0)
    - Texts sharing cluster words (coffee, espresso, etc.) → similar vectors
    - Unrelated texts → different vectors (lower cos sim)
    This enables semantic search ranking tests to validate relevance."""

    async def _embed(text: str) -> list[float]:
        return _text_to_embedding_vector(text)

    return _embed


# Live-test fixtures are loaded only by model_ha/conftest.py so unit/model
# tests stay fast and avoid loading .env, discover_tools, or HA client setup.

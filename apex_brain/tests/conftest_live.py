"""
Shared fixtures for live Home Assistant integration tests.

These fixtures connect to a REAL HA instance using credentials from .env.
Tests that use these fixtures are marked with @pytest.mark.live and are
skipped automatically when HA is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

# Ensure apex_brain is importable
_apex_brain = Path(__file__).resolve().parent.parent
if str(_apex_brain) not in sys.path:
    sys.path.insert(0, str(_apex_brain))


# ---------------------------------------------------------------------------
# Load real .env for live tests (override the dummy URL in conftest.py)
# ---------------------------------------------------------------------------

def _load_dotenv():
    """Load .env from project root into os.environ for live tests."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip()


_load_dotenv()

# Now import project modules (after env is loaded)
from brain.config import Settings  # noqa: E402
from tools import discover_tools  # noqa: E402
from tools.base import TOOL_REGISTRY  # noqa: E402


def skip_on_llm_error(response: str) -> None:
    """Skip a live test if the LLM returned an API error.

    Live tests depend on a working LLM API.  When the API
    key has exhausted its quota or is unreachable, the
    conversation pipeline returns an error string.  Rather
    than failing the assertion, we skip the test so the
    rest of the suite can continue.
    """
    _error_markers = (
        "Error reaching AI:",
        "RateLimitError",
        "RESOURCE_EXHAUSTED",
        "quota",
        "429",
    )
    if any(m in response for m in _error_markers):
        pytest.skip(
            "LLM API unavailable (rate limit / quota): "
            + response[:120]
        )


# ---------------------------------------------------------------------------
# Session-scoped: check HA connectivity once
# ---------------------------------------------------------------------------

def _ha_reachable() -> bool:
    """Synchronous check whether HA is reachable."""
    # Re-instantiate settings to pick up real .env values
    s = Settings()
    url = f"{s.ha_url}/api/config"
    try:
        r = httpx.get(url, headers=s.ha_headers, timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


_HA_AVAILABLE = _ha_reachable()


def pytest_collection_modifyitems(config, items):
    """Skip tests marked 'live' when HA is not reachable."""
    if _HA_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="Home Assistant not reachable")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_settings():
    """Return a fresh Settings instance loaded from real .env."""
    return Settings()


@pytest.fixture(scope="session")
def ha_url(live_settings):
    """Base HA API URL, e.g. http://homeassistant.local:8123/api"""
    return live_settings.ha_api_url


@pytest.fixture(scope="session")
def ha_headers(live_settings):
    """Auth headers for HA API calls."""
    return live_settings.ha_headers


@pytest.fixture(scope="session", autouse=True)
def register_tools():
    """Ensure all tools are discovered and registered once per session."""
    discover_tools()
    return TOOL_REGISTRY


@pytest.fixture(autouse=True)
def refresh_ha_client():
    """Replace the module-level httpx.AsyncClient in ha_helpers before each test.

    pytest-asyncio creates a new event loop per test function.  The
    module-level ``_ha_client`` in ``ha_helpers.py`` was created on a
    different loop, so subsequent tests get "Event loop is closed".
    This fixture swaps in a fresh client for every test.
    """
    import tools.ha_helpers as hh

    old = hh._ha_client
    hh._ha_client = httpx.AsyncClient(timeout=15.0)
    yield
    # Don't await aclose here — the loop may already be closing.
    # The client will be GC'd safely.
    hh._ha_client = old


class EntityStateGuard:
    """Context manager that saves and restores an entity's state.

    Usage:
        async with guard.protect("light.kitchen"):
            # do something that changes state
            ...
        # state is restored automatically
    """

    def __init__(self, ha_url: str, ha_headers: dict):
        self._ha_url = ha_url
        self._headers = ha_headers

    async def _get_client(self):
        """Create a fresh client (safe on the current event loop)."""
        return httpx.AsyncClient(timeout=15.0, headers=self._headers)

    async def _get_state(self, entity_id: str) -> dict:
        async with await self._get_client() as client:
            r = await client.get(f"{self._ha_url}/states/{entity_id}")
            r.raise_for_status()
            return r.json()

    async def _restore_state(self, entity_id: str, saved: dict):
        """Restore an entity to its saved state via service call."""
        domain = entity_id.split(".")[0]
        original_state = saved.get("state", "")

        async with await self._get_client() as client:
            if domain in ("light", "switch", "fan", "input_boolean"):
                service = "turn_on" if original_state == "on" else "turn_off"
                await client.post(
                    f"{self._ha_url}/services/{domain}/{service}",
                    json={"entity_id": entity_id},
                )
            elif domain == "cover":
                if original_state == "open":
                    await client.post(
                        f"{self._ha_url}/services/cover/open_cover",
                        json={"entity_id": entity_id},
                    )
                else:
                    await client.post(
                        f"{self._ha_url}/services/cover/close_cover",
                        json={"entity_id": entity_id},
                    )

    class _ProtectContext:
        def __init__(self, guard: "EntityStateGuard", entity_id: str):
            self._guard = guard
            self._entity_id = entity_id
            self._saved: dict = {}

        async def __aenter__(self):
            self._saved = await self._guard._get_state(self._entity_id)
            return self._saved

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            try:
                await self._guard._restore_state(self._entity_id, self._saved)
                await asyncio.sleep(0.5)  # let state settle
            except Exception:
                pass  # best-effort restore

    def protect(self, entity_id: str) -> "_ProtectContext":
        return self._ProtectContext(self, entity_id)


@pytest.fixture(scope="session")
def state_guard(ha_url, ha_headers):
    """Provides an EntityStateGuard for safe write tests."""
    return EntityStateGuard(ha_url, ha_headers)


@pytest.fixture
async def any_light_entity(ha_url, ha_headers):
    """Discover a basement light entity for safe write tests.

    Specifically targets lights in the basement area.
    Returns (entity_id, current_state) or skips if no basement lights exist.
    """
    async with httpx.AsyncClient(timeout=10.0, headers=ha_headers) as client:
        r = await client.get(f"{ha_url}/states")
        r.raise_for_status()
        states = r.json()

    # Only use basement lights for safe write tests
    basement_lights = [
        s for s in states
        if s["entity_id"].startswith("light.")
        and "basement" in s["entity_id"].lower()
        and s.get("state") in ("on", "off")
    ]
    if not basement_lights:
        # Fallback: check friendly names for "basement"
        basement_lights = [
            s for s in states
            if s["entity_id"].startswith("light.")
            and "basement" in s.get("attributes", {}).get(
                "friendly_name", ""
            ).lower()
            and s.get("state") in ("on", "off")
        ]
    if not basement_lights:
        pytest.skip("No basement light entities found in HA")
    # Prefer a light that's currently ON (easier to toggle back)
    on_lights = [l for l in basement_lights if l["state"] == "on"]
    chosen = on_lights[0] if on_lights else basement_lights[0]
    return chosen["entity_id"], chosen["state"]


@pytest.fixture
async def any_sensor_entity(ha_url, ha_headers):
    """Dynamically discover one sensor entity with a numeric state."""
    async with httpx.AsyncClient(timeout=10.0, headers=ha_headers) as client:
        r = await client.get(f"{ha_url}/states")
        r.raise_for_status()
        states = r.json()

    sensors = [
        s for s in states
        if s["entity_id"].startswith("sensor.")
        and s.get("state") not in ("unknown", "unavailable", "")
    ]
    if not sensors:
        pytest.skip("No sensor entities found in HA")
    return sensors[0]["entity_id"], sensors[0]["state"]

"""Tests for brain.config Settings."""

from brain.config import Settings


def test_settings_defaults():
    """Settings have expected default values."""
    s = Settings()
    assert s.litellm_model == "gpt-4o"
    assert s.embedding_model == "text-embedding-3-small"
    assert s.recent_turns == 10
    assert s.max_facts_in_context == 20
    assert s.port == 8080


def test_ha_api_url():
    """ha_api_url appends /api to ha_url."""
    s = Settings(ha_url="http://supervisor/core")
    assert s.ha_api_url == "http://supervisor/core/api"


def test_ha_headers_uses_ha_token_when_set():
    """ha_headers uses ha_token when SUPERVISOR_TOKEN is not set."""
    s = Settings(ha_token="test-token-123")
    h = s.ha_headers
    assert "Authorization" in h
    assert h["Authorization"] == "Bearer test-token-123"
    assert h["Content-Type"] == "application/json"


def test_ha_headers_prefers_supervisor_token(monkeypatch):
    """ha_headers prefers SUPERVISOR_TOKEN over ha_token."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    s = Settings(ha_token="fallback-token")
    h = s.ha_headers
    assert h["Authorization"] == "Bearer supervisor-secret"

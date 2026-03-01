"""
Apex Brain - Configuration
All settings loaded from environment variables or HA add-on options.
"""

from __future__ import annotations

import logging

from pydantic import PrivateAttr
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # AI model -- Claude Sonnet for everything
    litellm_model: str = "claude-sonnet-4-20250514"

    # API keys (only need the one matching your model)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # Embedding model for semantic memory search
    embedding_model: str = "text-embedding-3-small"

    # Model for background fact extraction
    fact_extraction_model: str = "claude-sonnet-4-20250514"

    # Home Assistant connection
    ha_url: str = "http://supervisor/core"
    ha_token: str = ""

    # Database path
    db_path: str = "./apex.db"

    # Memory tuning
    recent_turns: int = 10
    max_facts_in_context: int = 20
    conversation_retention_days: int = 90

    # Google Calendar (service account)
    google_calendar_credentials_path: str = ""
    google_calendar_id: str = "primary"

    # Timezone
    timezone: str = "America/Chicago"

    # Webhook / event-driven reactions
    webhook_secret: str = ""
    webhook_cooldown_seconds: int = 60
    webhook_enabled: bool = True

    # Announcements
    announce_on_events: bool = True
    announce_target: str = "alexa_all"
    phone_notify_target: str = "mobile_app_salih_iphone"

    # MCP Server (optional)
    mcp_server_url: str = ""
    mcp_transport: str = "sse"

    # Fact cleanup
    fact_cleanup_interval_hours: int = 24

    # Device summary cache refresh interval
    cache_refresh_seconds: int = 300

    # Server
    port: int = 8080

    _ha_headers_cache: dict | None = PrivateAttr(default=None)

    model_config = {
        "env_file": [".env", "../.env"],
        "extra": "ignore",
    }

    @property
    def ha_headers(self) -> dict:
        """Build auth headers for HA API calls (cached)."""
        if self._ha_headers_cache is not None:
            return self._ha_headers_cache

        import os

        token = os.environ.get("SUPERVISOR_TOKEN", "") or self.ha_token

        if not token:
            for path in [
                "/run/s6/container_environment/SUPERVISOR_TOKEN",
                "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
            ]:
                try:
                    with open(path) as f:
                        token = f.read().strip()
                    if token:
                        break
                except (FileNotFoundError, PermissionError):
                    continue

        if not token:
            logger.warning("HA_TOKEN is not set — API calls will fail.")

        self._ha_headers_cache = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        return self._ha_headers_cache

    @property
    def ha_api_url(self) -> str:
        """Full HA REST API base URL."""
        return f"{self.ha_url}/api"


# Singleton
settings = Settings()

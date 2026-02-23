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
    # AI model -- change this one string to swap providers
    # Examples: gpt-4o, gpt-4o-mini, claude-sonnet-4-20250514, gemini/gemini-2.5-pro
    litellm_model: str = "gpt-4o"

    # API keys (only need the one matching your model)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # Embedding model for semantic memory search
    embedding_model: str = "text-embedding-3-small"

    # Cheaper/faster model for background fact extraction
    fact_extraction_model: str = "gpt-4o-mini"

    # Home Assistant connection
    # Inside add-on: http://supervisor/core (auto-authenticated via SUPERVISOR_TOKEN)
    # Local dev: http://<HA_IP>:8123 + long-lived token
    ha_url: str = "http://supervisor/core"
    ha_token: str = ""

    # Database path (persistent volume in add-on: /data/apex.db)
    db_path: str = "./apex.db"

    # Memory tuning
    recent_turns: int = (
        10  # conversation turns to always include in context
    )
    max_facts_in_context: int = 20  # max relevant facts per AI call
    conversation_retention_days: int = 90  # prune turns older than N days

    # Google Calendar (service account)
    google_calendar_credentials_path: str = ""
    google_calendar_id: str = "primary"

    # Timezone (must match your HA instance)
    timezone: str = "America/Chicago"

    # Webhook / event-driven reactions
    webhook_secret: str = ""
    webhook_cooldown_seconds: int = 60
    webhook_enabled: bool = True

    # Proactive TTS / Alexa announcements on high-priority events
    announce_on_events: bool = True
    announce_target: str = "alexa_all"

    # Phone notification target (mobile_app entity name)
    phone_notify_target: str = "mobile_app_salih_iphone"

    # MCP Server (optional - connect for expanded HA capabilities)
    mcp_server_url: str = ""  # e.g. http://ha-ip:8080/sse
    mcp_transport: str = "sse"  # "sse" or "streamable_http"

    # Autonomous Loop - Scheduler
    scheduler_enabled: bool = True
    morning_briefing_hour: int = 7  # 7 AM in configured timezone
    evening_briefing_hour: int = 21  # 9 PM
    health_check_interval_minutes: int = 60

    # Autonomous Loop - Event Subscription
    event_subscription_enabled: bool = True
    event_significance_threshold: float = 0.3
    event_reconnect_delay: int = 5  # seconds, initial backoff
    event_max_reconnect_delay: int = 300  # 5 minutes max backoff

    # Self-Curation
    curator_enabled: bool = True
    fact_min_confidence_prune: float = 0.35
    automation_stale_days: int = 90
    routine_stale_days: int = 90

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

        # Inside add-on: SUPERVISOR_TOKEN injected by HA Supervisor
        token = (
            os.environ.get("SUPERVISOR_TOKEN", "")
            or self.ha_token
        )

        # Fallback: try reading from S6 container environment file
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
            logger.warning(
                "HA_TOKEN is not set — API calls will fail."
            )

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

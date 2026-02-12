"""
Apex Brain - Configuration
All settings loaded from environment variables or HA add-on options.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI model -- change this one string to swap providers
    # Examples: gpt-4o, gpt-4o-mini, claude-sonnet-4-20250514, gemini/gemini-2.0-flash
    litellm_model: str = "gpt-4o"

    # API keys (only need the one matching your model)
    openai_api_key: str = ""
    anthropic_api_key: str = ""

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

    # Server
    port: int = 8080

    model_config = {"env_file": [".env", "../.env"], "extra": "ignore"}

    @property
    def ha_headers(self) -> dict:
        """Build auth headers for HA API calls."""
        import os

        # Inside add-on: use SUPERVISOR_TOKEN (injected by HA Supervisor via S6)
        token = os.environ.get("SUPERVISOR_TOKEN", "") or self.ha_token

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

        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @property
    def ha_api_url(self) -> str:
        """Full HA REST API base URL."""
        return f"{self.ha_url}/api"


# Singleton
settings = Settings()

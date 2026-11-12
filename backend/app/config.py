"""Application configuration loaded from environment variables / `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTGUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./agentguard.db"
    auth_required: bool = False
    auth_secret: str = "dev-secret-change-me"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    approval_ttl_minutes: int = 240
    retention_days: int = 90
    max_payload_bytes: int = 65536
    redact_secrets: bool = True
    seed_demo_data: bool = True

    # Rate limiting for the agent decision endpoint. Fixed window per agent.
    decision_rate_limit: int = 60
    decision_rate_window_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

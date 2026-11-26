"""Application configuration loaded from environment variables / `.env`."""

from functools import lru_cache

from pydantic import Field
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

    # Local LLM via Ollama. These variables intentionally keep the standard
    # OLLAMA_* names rather than the AGENTGUARD_ prefix so they match the
    # Ollama client convention.
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(default="fixflow-llm", validation_alias="OLLAMA_MODEL")
    ollama_timeout: float = Field(default=120.0, validation_alias="OLLAMA_TIMEOUT")

    approval_ttl_minutes: int = 240
    retention_days: int = 90
    max_payload_bytes: int = 65536
    redact_secrets: bool = True
    seed_demo_data: bool = True

    # Rate limiting for the agent decision endpoint. Fixed window per agent.
    decision_rate_limit: int = 60
    decision_rate_window_seconds: int = 60

    # V2 intelligence defaults. These are policy defaults, not hidden switches:
    # every effective rule is echoed in the decision evidence.
    propagation_max_depth: int = 12
    propagation_repeated_failure_threshold: int = 3
    containment_failure_threshold: int = 3
    circuit_open_seconds: int = 60
    reliability_window_days: int = 30
    reliability_min_observations: int = 5
    reliability_medium_threshold: float = 60.0
    reliability_high_threshold: float = 80.0
    reliability_prior_mean: float = 0.8
    reliability_prior_strength: float = 5.0
    artifact_default_ttl_minutes: int = 1440
    benchmark_timeout_seconds: int = 120
    transaction_compensation_requires_approval: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

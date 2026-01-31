"""Application settings using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required API keys
    openai_api_key: str
    hf_token: str

    # Default model settings
    default_language: str = "ko"
    default_stt_model: str = "gpt-4o-mini-transcribe"
    default_chat_model: str = "gpt-4o-mini"

    # Processing settings
    async_threshold_seconds: int = 30
    max_concurrent_jobs: int = 3
    min_segment_duration: float = 0.6

    # Job TTL (in seconds, default 24 hours)
    job_ttl_seconds: int = 86400


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

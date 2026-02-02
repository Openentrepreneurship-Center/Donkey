from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str
    hf_token: str
    api_key: str = "default-api-key"  # For X-Api-Key header validation

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # S3 Logging
    s3_logs_bucket: str = ""
    s3_logs_prefix: str = "job-logs"
    aws_region: str = "ap-northeast-2"

    # Models
    stt_model: str = "gpt-4o-mini-transcribe"
    chat_model: str = "gpt-4o-mini"

    # Processing defaults
    default_language: str = "ko"
    min_segment_duration: float = 0.6
    default_num_speakers: int | None = None

    # Job expiration (seconds)
    job_ttl: int = 86400  # 24 hours

    model_config = {
        "env_file": Path(__file__).resolve().parent.parent / ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str
    api_key: str = "default-api-key"  # For X-Api-Key header validation

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # S3 Logging
    s3_logs_bucket: str = ""
    s3_logs_prefix: str = "job-logs"
    aws_region: str = "ap-northeast-2"
    # S3에 변환된 오디오(WAV) 업로드 (같은 버킷, 폴더 prefix)
    s3_audio_prefix: str = "audio-data"
    save_audio_to_s3: bool = True

    # Models
    stt_model: str = "gpt-4o-mini-transcribe"
    chat_model: str = "gpt-4o-mini"

    # 화자 분리: Whisper 구간 + 턴/LLM 또는 오디오 특징 클러스터링 (규칙 기반, CPU만 사용)
    whisper_segment_model: str = "whisper-1"
    # True = Resemblyzer 화자 임베딩(가벼움), False = MFCC+피치 기반
    use_resemblyzer_embedding: bool = True
    # True = 오디오 없이 LLM이 구간별 DOCTOR/PATIENT만 붙임 (진료 대화에 유리)
    use_llm_only_speaker_labeling: bool = True

    # Processing defaults
    default_language: str = "ko"
    min_segment_duration: float = 0.6

    # Job expiration (seconds)
    job_ttl: int = 86400  # 24 hours

    # Whisper 전사문을 metrics/eval_data에 hypothesis txt로 저장 (지표 평가용)
    save_whisper_to_eval_data: bool = False

    model_config = {
        "env_file": Path(__file__).resolve().parent.parent / ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()

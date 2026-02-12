from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str
    api_key: str = "default-api-key"  # For X-Api-Key header validation

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # S3 Logging (비우면 Job 로그/오디오 S3 저장 안 함)
    s3_logs_bucket: str = Field(default="", validation_alias="S3_LOGS_BUCKET")
    s3_logs_prefix: str = Field(default="job-logs", validation_alias="S3_LOGS_PREFIX")
    aws_region: str = Field(default="ap-northeast-2", validation_alias="AWS_REGION")
    # S3에 변환된 오디오(WAV) 업로드 (같은 버킷, 폴더 prefix)
    s3_audio_prefix: str = Field(default="audio-data", validation_alias="S3_AUDIO_PREFIX")
    save_audio_to_s3: bool = Field(default=True, validation_alias="SAVE_AUDIO_TO_S3")

    # Models
    stt_model: str = "gpt-4o-mini-transcribe"
    chat_model: str = "gpt-4o-mini"

    # STT 백엔드: whisper | clova (clova 사용 시 아래 CLOVA_* 설정 필요)
    stt_backend: str = Field(default="whisper", validation_alias="STT_BACKEND")
    clova_speech_invoke_url: str = Field(default="", validation_alias="CLOVA_SPEECH_INVOKE_URL")
    clova_speech_api_key: str = Field(default="", validation_alias="CLOVA_SPEECH_API_KEY")

    # 화자 분리: Whisper/Clova 구간 + 턴/LLM 또는 오디오 특징 클러스터링 (규칙 기반, CPU만 사용)
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

    # 멱등성: 같은 요청(file URL)이 N초 안에 다시 오면 기존 job_id 반환
    idempotency_window_seconds: int = Field(
        default=30,
        validation_alias="IDEMPOTENCY_WINDOW_SECONDS",
    )

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

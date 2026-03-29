from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str
    api_key: str = "default-api-key"  # For X-Api-Key header validation

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MySQL (비우면 진료/로그/요약 DB 저장 안 함)
    database_url: str = Field(
        default="",
        validation_alias="DATABASE_URL",
        description="Async MySQL URL, e.g. mysql+asyncmy://user:pass@host:3306/dbname",
    )

    # S3 Logging (비우면 Job 로그/오디오 S3 저장 안 함)
    s3_logs_bucket: str = Field(default="", validation_alias="S3_LOGS_BUCKET")
    s3_logs_prefix: str = Field(default="job-logs", validation_alias="S3_LOGS_PREFIX")
    aws_region: str = Field(default="ap-northeast-2", validation_alias="AWS_REGION")
    # S3에 변환된 오디오(WAV) 업로드 (같은 버킷, 폴더 prefix)
    s3_audio_prefix: str = Field(default="audio-data", validation_alias="S3_AUDIO_PREFIX")
    save_audio_to_s3: bool = Field(default=True, validation_alias="SAVE_AUDIO_TO_S3")
    s3_inquiry_attachments_prefix: str = Field(
        default="inquiry-attachments", validation_alias="S3_INQUIRY_ATTACHMENTS_PREFIX"
    )

    # Models
    stt_model: str = "gpt-4o-mini-transcribe"
    chat_model: str = "gpt-4o-mini"

    # STT 백엔드: whisper | clova | donkey
    stt_backend: str = Field(default="donkey", validation_alias="STT_BACKEND")
    clova_speech_invoke_url: str = Field(default="", validation_alias="CLOVA_SPEECH_INVOKE_URL")
    clova_speech_api_key: str = Field(default="", validation_alias="CLOVA_SPEECH_API_KEY")
    # donkey 백엔드: 온프레미스 Whisper API (IP 직접 + Host 헤더로 iptime 국가 차단 우회)
    # DONKEY_STT_BASE_URL: 레거시/.env 호환
    donkey_stt_api_url: str = Field(
        default="http://163.239.108.20",
        validation_alias=AliasChoices("DONKEY_STT_API_URL", "DONKEY_STT_BASE_URL"),
    )
    donkey_stt_api_host: str = Field(default="api.donkey.ai.kr", validation_alias="DONKEY_STT_API_HOST")

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

    # 테스트용: 설정 시 음성 길이와 무관하게 이 값(초)으로 임계시간 적용 (0이면 미사용)
    processing_timeout_override_seconds: int = Field(
        default=0,
        validation_alias="PROCESSING_TIMEOUT_OVERRIDE_SECONDS",
    )

    # 동시 처리 job 수 (이 수만큼 동시에 전사·요약 처리)
    max_concurrent_jobs: int = Field(
        default=5,
        validation_alias="MAX_CONCURRENT_JOBS",
    )

    # Slack 알림 (비우면 미발송)
    slack_webhook_url: str = Field(default="", validation_alias="SLACK_WEBHOOK_URL")

    # CORS (쉼표 구분, 예: https://admin.donkey.ai.kr,http://localhost:3000)
    cors_origins: str = Field(
        default="https://admin.donkey.ai.kr,http://localhost:3000",
        validation_alias="CORS_ORIGINS",
    )

    # Admin JWT
    admin_jwt_secret: str = Field(
        default="change-me-in-production",
        validation_alias="ADMIN_JWT_SECRET",
    )
    admin_jwt_algorithm: str = "HS256"
    admin_jwt_expire_minutes: int = Field(
        default=60 * 4,
        validation_alias="ADMIN_JWT_EXPIRE_MINUTES",
    )

    model_config = {
        "env_file": Path(__file__).resolve().parent.parent / ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_processing_timeout_seconds(audio_duration_seconds: float) -> int:
    """입력 음성 길이(초)에 따른 처리 임계시간(초). 초과 시 오류 알람."""
    if audio_duration_seconds <= 300:   # 5분 이하 → 1분 30초
        return 90
    if audio_duration_seconds <= 600:   # 10분 이하 → 2분
        return 120
    if audio_duration_seconds < 900:    # 10분 초과 ~ 15분 미만 → 3분
        return 180
    return 240  # 15분 이상 → 4분

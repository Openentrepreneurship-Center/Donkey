import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings


@dataclass
class StageMetrics:
    download_time_ms: int = 0
    conversion_time_ms: int = 0
    diarization_time_ms: int = 0
    transcription_time_ms: int = 0
    validation_time_ms: int = 0
    pii_filter_time_ms: int = 0
    summarization_time_ms: int = 0


@dataclass
class QualityMetrics:
    is_abusing: bool = False
    abusing_reason: str = ""
    speaker_count: int = 0
    segment_count: int = 0


@dataclass
class ModelUsage:
    stt_model: str = ""
    chat_model: str = ""
    total_tokens: int = 0


@dataclass
class JobLog:
    job_id: str
    request_timestamp: str = ""
    completed_at: str = ""
    file_url: str = ""
    status: str = "pending"
    audio_duration: float = 0
    processing_time_ms: int = 0
    stages: StageMetrics = field(default_factory=StageMetrics)
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    model_usage: ModelUsage = field(default_factory=ModelUsage)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


class JobLogger:
    def __init__(self, job_id: str, file_url: str = ""):
        self.log = JobLog(
            job_id=job_id,
            file_url=file_url,
            request_timestamp=datetime.now(KST).isoformat(),
        )
        self._start_time = time.time()
        self._stage_start: float | None = None
        settings = get_settings()
        stt_backend = (settings.stt_backend or "").strip().lower()
        self.log.model_usage.stt_model = "clova-speech" if stt_backend == "clova" else settings.stt_model
        self.log.model_usage.chat_model = settings.chat_model

    def start_stage(self) -> None:
        self._stage_start = time.time()

    def end_stage(self, stage_name: str) -> int:
        if self._stage_start is None:
            return 0
        elapsed_ms = int((time.time() - self._stage_start) * 1000)
        elapsed_sec = elapsed_ms / 1000
        setattr(self.log.stages, stage_name, elapsed_ms)
        self._stage_start = None
        stage_label = stage_name.replace("_time_ms", "") if stage_name.endswith("_time_ms") else stage_name
        print(f"[{self.log.job_id}] {stage_label}: {elapsed_sec:.2f}초", flush=True)
        return elapsed_ms

    def set_audio_duration(self, duration: float) -> None:
        self.log.audio_duration = duration

    def set_quality(
        self,
        is_abusing: bool = False,
        abusing_reason: str = "",
        speaker_count: int = 0,
        segment_count: int = 0,
    ) -> None:
        self.log.quality.is_abusing = is_abusing
        self.log.quality.abusing_reason = abusing_reason
        self.log.quality.speaker_count = speaker_count
        self.log.quality.segment_count = segment_count

    def add_tokens(self, tokens: int) -> None:
        self.log.model_usage.total_tokens += tokens

    def set_error(self, error_type: str, error_message: str, error_stage: str = "") -> None:
        self.log.error = {
            "type": error_type,
            "message": error_message,
            "stage": error_stage,
        }

    def complete(self, status: str = "completed") -> None:
        self.log.status = status
        self.log.completed_at = datetime.now(KST).isoformat()
        self.log.processing_time_ms = int((time.time() - self._start_time) * 1000)

    async def save_to_s3(self) -> bool:
        settings = get_settings()

        if not settings.s3_logs_bucket:
            return False

        try:
            s3_client = boto3.client("s3", region_name=settings.aws_region)

            date_prefix = datetime.now(KST).strftime("%Y/%m/%d")
            key = f"{settings.s3_logs_prefix}/{date_prefix}/{self.log.job_id}.json"

            s3_client.put_object(
                Bucket=settings.s3_logs_bucket,
                Key=key,
                Body=json.dumps(self.log.to_dict(), ensure_ascii=False, indent=2),
                ContentType="application/json",
            )
            return True
        except ClientError as e:
            print(f"Failed to save log to S3: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error saving log to S3: {e}")
            return False

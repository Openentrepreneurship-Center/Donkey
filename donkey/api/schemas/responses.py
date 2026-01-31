"""API response schemas."""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """서버 상태 응답."""
    status: str = "ok"
    version: str


class ReadyResponse(BaseModel):
    """준비 상태 응답."""
    ready: bool
    message: str


class TranscriptionSegmentResponse(BaseModel):
    """단일 텍스트 변환 세그먼트."""
    speaker: str = Field(description="화자 ID")
    start: float = Field(description="시작 시간(초)")
    end: float = Field(description="종료 시간(초)")
    text: str = Field(description="발화 텍스트")


class DiarizeDataResponse(BaseModel):
    """화자 분리 응답 데이터."""
    transcript: str = Field(description="전체 텍스트")
    segments: List[TranscriptionSegmentResponse] = Field(description="세그먼트 목록")
    speaker_count: int = Field(description="화자 수")
    duration_seconds: float = Field(description="오디오 길이(초)")


class DiarizeResponse(BaseModel):
    """동기 화자 분리 응답."""
    status: str = "completed"
    data: DiarizeDataResponse


class SoapDataResponse(BaseModel):
    """SOAP 응답 데이터."""
    soap_summary: str = Field(description="SOAP 형식 요약")
    disclaimer: str = Field(description="면책 조항")


class SoapResponse(BaseModel):
    """SOAP 요약 응답."""
    status: str = "completed"
    data: SoapDataResponse


class FullPipelineDataResponse(BaseModel):
    """전체 파이프라인 응답 데이터."""
    transcript: str = Field(description="전체 텍스트")
    segments: List[TranscriptionSegmentResponse] = Field(description="세그먼트 목록")
    speaker_count: int = Field(description="화자 수")
    duration_seconds: float = Field(description="오디오 길이(초)")
    soap_summary: str = Field(description="SOAP 형식 요약")
    disclaimer: str = Field(description="면책 조항")


class FullPipelineResponse(BaseModel):
    """전체 파이프라인 응답."""
    status: str = "completed"
    data: FullPipelineDataResponse


class AsyncJobResponse(BaseModel):
    """비동기 작업 생성 응답."""
    status: str = "processing"
    job_id: str = Field(description="작업 ID")
    poll_url: str = Field(description="상태 확인 URL")


class JobStatusResponse(BaseModel):
    """작업 상태 응답."""
    job_id: str = Field(description="작업 ID")
    status: str = Field(description="작업 상태")
    progress: int = Field(ge=0, le=100, description="진행률 (%)")
    current_step: str = Field(description="현재 단계")
    error: Optional[str] = Field(default=None, description="에러 메시지")


class JobResultResponse(BaseModel):
    """작업 결과 응답."""
    job_id: str = Field(description="작업 ID")
    status: str = Field(description="작업 상태")
    data: Optional[Any] = Field(default=None, description="결과 데이터")
    error: Optional[str] = Field(default=None, description="에러 메시지")


class ErrorResponse(BaseModel):
    """에러 응답."""
    detail: str = Field(description="에러 상세 내용")

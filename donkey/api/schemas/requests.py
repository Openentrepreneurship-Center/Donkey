"""API request schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class DiarizeRequest(BaseModel):
    """화자 분리 요청 파라미터 (폼 데이터)."""
    # Note: file is handled separately via UploadFile
    language: str = Field(default="ko", description="언어 코드 (ko, en 등)")
    stt_model: str = Field(
        default="gpt-4o-mini-transcribe",
        description="음성인식 모델명",
    )
    num_speakers: Optional[int] = Field(
        default=None,
        description="화자 수 (알고 있으면 지정, 정확도 향상)",
        ge=1,
        le=20,
    )
    min_segment_duration: float = Field(
        default=0.6,
        description="최소 세그먼트 길이(초) - 더 짧은 세그먼트는 건너뜀",
        ge=0.1,
        le=10.0,
    )


class SoapRequest(BaseModel):
    """SOAP 요약 요청."""
    diarized_text: str = Field(
        ...,
        description="화자 라벨과 타임스탬프가 포함된 화자 분리 텍스트",
        min_length=1,
    )
    chat_model: str = Field(
        default="gpt-4o-mini",
        description="SOAP 요약용 채팅 모델",
    )


class FullPipelineRequest(BaseModel):
    """전체 파이프라인 요청 파라미터 (폼 데이터)."""
    # Note: file is handled separately via UploadFile
    language: str = Field(default="ko", description="언어 코드 (ko, en 등)")
    stt_model: str = Field(
        default="gpt-4o-mini-transcribe",
        description="음성인식 모델명",
    )
    chat_model: str = Field(
        default="gpt-4o-mini",
        description="SOAP 요약용 채팅 모델",
    )
    num_speakers: Optional[int] = Field(
        default=None,
        description="화자 수 (알고 있으면 지정)",
        ge=1,
        le=20,
    )
    min_segment_duration: float = Field(
        default=0.6,
        description="최소 세그먼트 길이(초)",
        ge=0.1,
        le=10.0,
    )

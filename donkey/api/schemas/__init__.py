"""API request/response schemas."""

from .requests import DiarizeRequest, SoapRequest, FullPipelineRequest
from .responses import (
    HealthResponse,
    ReadyResponse,
    TranscriptionSegmentResponse,
    DiarizeDataResponse,
    DiarizeResponse,
    SoapDataResponse,
    SoapResponse,
    FullPipelineDataResponse,
    FullPipelineResponse,
    AsyncJobResponse,
    JobStatusResponse,
    JobResultResponse,
    ErrorResponse,
)

__all__ = [
    # Requests
    "DiarizeRequest",
    "SoapRequest",
    "FullPipelineRequest",
    # Responses
    "HealthResponse",
    "ReadyResponse",
    "TranscriptionSegmentResponse",
    "DiarizeDataResponse",
    "DiarizeResponse",
    "SoapDataResponse",
    "SoapResponse",
    "FullPipelineDataResponse",
    "FullPipelineResponse",
    "AsyncJobResponse",
    "JobStatusResponse",
    "JobResultResponse",
    "ErrorResponse",
]

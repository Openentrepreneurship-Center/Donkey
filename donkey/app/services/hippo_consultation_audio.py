"""히포 상담 오디오 조회: GET /consultation/{fileId}/stt/audio-url → Base64 디코딩."""

from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import dataclass

import httpx

from app.config import get_settings, httpx_verify

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConsultationAudioPayload:
    """오디오 조회 API 응답을 디코딩한 결과."""

    raw_bytes: bytes
    content_type: str


def suffix_for_audio_content_type(content_type: str) -> str:
    """contentType으로 로컬 저장용 확장자를 추정 (기본 .bin)."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct:
        return ".bin"
    ext = mimetypes.guess_extension(ct)
    if ext == ".mpga":
        return ".mp3"
    if ext:
        return ext
    if ct == "audio/mp4":
        return ".m4a"
    return ".bin"


class HippoConsultationAudioError(Exception):
    """오디오 조회 실패 (HTTP 오류, 잘못된 본문 등)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def fetch_consultation_audio(file_id: str) -> ConsultationAudioPayload:
    """상담 ID로 오디오 바이너리와 content-type을 조회한다."""
    settings = get_settings()
    base = (settings.hippo_consultation_api_base_url or "").rstrip("/")
    if not base:
        raise HippoConsultationAudioError("HIPPO_CONSULTATION_API_BASE_URL is not configured")
    api_key = (settings.hippo_consultation_api_key or "").strip()
    if not api_key:
        raise HippoConsultationAudioError("HIPPO_CONSULTATION_API_KEY is not configured")

    fid = (file_id or "").strip()
    if not fid:
        raise HippoConsultationAudioError("file_id is empty")

    url = f"{base}/consultation/{fid}/stt/audio-url"
    headers = {"x-api-key": api_key}
    logger.info(
        "Hippo consultation audio request start file_id=%s... url=%s",
        fid[:8],
        url,
    )

    try:
        async with httpx.AsyncClient(timeout=300.0, verify=httpx_verify()) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as e:
        sc = e.response.status_code if e.response is not None else None
        logger.warning(
            "Hippo consultation audio HTTP error status=%s url=%s",
            sc,
            url,
        )
        raise HippoConsultationAudioError(
            f"consultation audio request failed with HTTP {sc}",
            status_code=sc,
        ) from e
    except httpx.RequestError as e:
        logger.warning("Hippo consultation audio request error: %s", e)
        raise HippoConsultationAudioError(f"consultation audio request failed: {e}") from e

    logger.info(
        "Hippo consultation audio request success file_id=%s... status=%s",
        fid[:8],
        getattr(resp, "status_code", "(unknown)"),
    )
    if not isinstance(body, dict):
        raise HippoConsultationAudioError("consultation audio response is not a JSON object")

    data_b64 = body.get("data")
    if not isinstance(data_b64, str) or not data_b64.strip():
        raise HippoConsultationAudioError("consultation audio response missing data")

    content_type = body.get("contentType")
    if not isinstance(content_type, str) or not content_type.strip():
        content_type = "application/octet-stream"
    else:
        content_type = content_type.strip()

    try:
        raw = base64.b64decode(data_b64, validate=False)
    except Exception as e:
        raise HippoConsultationAudioError("invalid base64 in consultation audio data") from e

    logger.info(
        "Fetched consultation audio decoded file_id=%s... bytes=%s content_type=%s",
        fid[:8] + "...",
        len(raw),
        content_type,
    )
    return ConsultationAudioPayload(raw_bytes=raw, content_type=content_type)

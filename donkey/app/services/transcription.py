import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx
from pydub import AudioSegment

from app.config import get_settings, httpx_verify
from app.services.openai_client import get_openai_client

logger = logging.getLogger(__name__)


def _segments_from_donkey_response(body: Any) -> list[dict]:
    """Donkey STT 응답을 내부 구간 리스트로 정규화."""
    out: list[dict] = []

    # 신규 포맷: 응답 본문이 배열이며 항목은 {role, index, content}
    if isinstance(body, list):
        for seg in body:
            if not isinstance(seg, dict):
                continue
            text = (seg.get("content") or "").strip()
            if not text:
                continue
            item: dict = {"text": text}
            if seg.get("role"):
                item["role"] = str(seg["role"])
            if seg.get("index") is not None:
                item["index"] = int(seg["index"])
            out.append(item)
        return out

    # 기존 포맷: { segments: [ {start, end, text, speaker?}, ... ] }
    segments = body.get("segments") if isinstance(body, dict) else []
    for seg in (segments or []):
        text = (seg.get("text") or seg.get("content") or "").strip()
        if not text:
            continue
        item: dict = {
            "start": float(seg.get("start") or 0),
            "end": float(seg.get("end") or 0),
            "text": text,
        }
        if seg.get("speaker"):
            item["speaker"] = str(seg["speaker"])
        out.append(item)
    return out


def _transcribe_with_donkey_url(file_url: str) -> tuple[list[dict], str | None]:
    """온프레미스 STT API: 입력으로 받은 오디오 URL을 그대로 JSON으로 전달.

    POST /transcribe/clova-note, body: {"url": "<클라이언트 file URL>"}
    IP 직접 호출 + Host 헤더로 iptime 국가 차단 우회.

    Returns:
        (segments, evaluation_job_id) 튜플.
        evaluation_job_id는 stt-api가 응답 헤더 X-Evaluation-Job-Id로 전달한 값.
    """
    settings = get_settings()
    api_url = (settings.donkey_stt_api_url or "").rstrip("/") + "/transcribe/clova-note"
    api_host = settings.donkey_stt_api_host or ""

    headers = {"Host": api_host} if api_host else {}
    logger.info(
        "Donkey STT POST %s (Host=%s, client audio url length=%s)",
        api_url,
        api_host or "(default)",
        len(file_url),
    )
    with httpx.Client(timeout=600.0, headers=headers, verify=httpx_verify()) as client:
        resp = client.post(api_url, json={"url": file_url})
    resp.raise_for_status()
    eval_job_id = resp.headers.get("X-Evaluation-Job-Id")
    segments = _segments_from_donkey_response(resp.json())
    logger.info(
        "Donkey STT URL transcription success segments=%s eval_job_id=%s",
        len(segments),
        eval_job_id or "(none)",
    )
    return segments, eval_job_id


def transcribe_with_url(file_url: str, language: str = "ko") -> list[dict]:
    """온프레미스 Whisper STT API로 URL 기반 전사 (worker_temp 전용).

    IP 직접 호출 + Host 헤더로 iptime 국가 차단 우회.
    Returns list of {"start": float, "end": float, "text": str, "speaker": str (optional)}.
    """
    settings = get_settings()
    api_url = (settings.donkey_stt_api_url or "").rstrip("/") + "/transcribe/temp"
    api_host = settings.donkey_stt_api_host or ""

    headers = {"Host": api_host} if api_host else {}
    logger.info(
        "Donkey STT POST %s (temp, Host=%s)",
        api_url,
        api_host or "(default)",
    )
    with httpx.Client(timeout=600.0, headers=headers, verify=httpx_verify()) as client:
        resp = client.post(api_url, json={"url": file_url, "language": language})
        resp.raise_for_status()
        body = resp.json()
    segments = _segments_from_donkey_response(body)
    logger.info("Donkey STT temp transcription success segments=%s", len(segments))
    return segments


def transcribe_with_segments_from_file(
    file_path: str | Path,
    *,
    content_type: str = "application/octet-stream",
    filename: str | None = None,
    language: str = "ko",
    model: str = "whisper-1",
) -> tuple[list[dict], str | None]:
    """
    Donkey STT: 로컬 오디오 파일을 multipart 필드 ``file``로 전송해 전사.

    ``reference_text`` 파트는 보내지 않는다.
    """
    _ = language, model
    path = Path(file_path)
    settings = get_settings()
    api_url = (settings.donkey_stt_api_url or "").rstrip("/") + "/transcribe/clova-note/file"
    api_host = settings.donkey_stt_api_host or ""

    headers = {"Host": api_host} if api_host else {}
    fname = filename or path.name
    ct = (content_type or "").strip() or "application/octet-stream"
    file_body = path.read_bytes()
    logger.info(
        "Donkey STT POST %s (file, Host=%s, bytes=%s, filename=%s, content_type=%s)",
        api_url,
        api_host or "(default)",
        len(file_body),
        fname,
        ct,
    )
    with httpx.Client(timeout=600.0, headers=headers, verify=httpx_verify()) as client:
        resp = client.post(
            api_url,
            files={"file": (fname, file_body, ct)},
        )
    resp.raise_for_status()
    eval_job_id = resp.headers.get("X-Evaluation-Job-Id")
    segments = _segments_from_donkey_response(resp.json())
    logger.info(
        "Donkey STT file transcription success segments=%s eval_job_id=%s",
        len(segments),
        eval_job_id or "(none)",
    )
    return segments, eval_job_id


def transcribe_with_segments(
    file_url: str,
    language: str = "ko",
    model: str = "whisper-1",
) -> tuple[list[dict], str | None]:
    """
    Donkey STT: 클라이언트가 제출한 오디오 URL을 그대로 전달해 전사.
    구간별 타임스탬프(시작/끝)와 텍스트를 반환.
    language/model은 호환용 인자(STT API는 현재 url만 사용).

    Returns:
        (segments, evaluation_job_id) 튜플.
    """
    _ = language, model
    return _transcribe_with_donkey_url(file_url)


def transcribe_segment(
    audio_segment: AudioSegment,
    language: str = "ko",
    model: str = "gpt-4o-mini-transcribe",
) -> str:
    """Transcribe an audio segment using OpenAI STT."""
    client = get_openai_client()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        audio_segment.export(tmp.name, format="wav")
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                model=model,
                file=f,
                language=language,
            )

    return (result.text or "").strip()


def seconds_to_time_str(sec: float) -> str:
    """Convert seconds to human-readable time string."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:04.1f}"
    return f"{m:02d}:{s:04.1f}"

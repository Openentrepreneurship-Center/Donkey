import json
import tempfile
from functools import lru_cache
from pathlib import Path

import httpx
from openai import OpenAI
from pydub import AudioSegment

from app.config import get_settings

# Clova Speech: language code 매핑 (내부 ko -> API ko-KR 등)
_CLOVA_LANG_MAP = {
    "ko": "ko-KR",
    "en": "en-US",
    "enko": "enko",
    "ja": "ja",
    "zh": "zh-cn",
    "zh-cn": "zh-cn",
    "zh-tw": "zh-tw",
}


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    """Get OpenAI client (cached)."""
    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key)


def _transcribe_with_clova(
    wav_path: str | Path,
    language: str = "ko",
) -> list[dict]:
    """
    CLOVA Speech 장문 인식 API로 전사. 구간별 start/end(초), text 반환.
    Returns list of {"start": float, "end": float, "text": str}.
    """
    settings = get_settings()
    invoke_url = (settings.clova_speech_invoke_url or "").rstrip("/")
    api_key = settings.clova_speech_api_key or ""
    if not invoke_url or not api_key:
        raise ValueError("CLOVA_SPEECH_INVOKE_URL and CLOVA_SPEECH_API_KEY must be set when STT_BACKEND=clova")

    path = Path(wav_path)
    clova_lang = _CLOVA_LANG_MAP.get(language, "ko-KR")
    params = {
        "language": clova_lang,
        "completion": "sync",
        "fullText": True,
        "wordAlignment": True,
        "diarization": {"enable": True},
    }

    url = f"{invoke_url}/recognizer/upload"
    headers = {"X-CLOVASPEECH-API-KEY": api_key}
    with path.open("rb") as f:
        media_bytes = f.read()
    files = {"media": (path.name, media_bytes, "audio/wav")}
    data = {"params": json.dumps(params), "type": "application/json"}

    with httpx.Client(timeout=300.0) as client:
        resp = client.post(url, headers=headers, files=files, data=data)
    resp.raise_for_status()
    body = resp.json()

    if body.get("result") != "COMPLETED":
        raise RuntimeError(f"CLOVA Speech failed: {body.get('message', body)}")

    segments_raw = body.get("segments") or []
    out: list[dict] = []
    for seg in segments_raw:
        start_ms = int(seg.get("start") or 0)
        end_ms = int(seg.get("end") or 0)
        text = (seg.get("text") or "").strip()
        # Clova 화자 라벨 (diarization.label 또는 speaker.label, 문자열 "1","2" 등)
        raw_label = seg.get("diarization") or seg.get("speaker") or {}
        speaker = raw_label.get("label") if isinstance(raw_label, dict) else None
        if speaker is not None:
            speaker = str(speaker)
        if text:
            item: dict = {
                "start": start_ms / 1000.0,
                "end": end_ms / 1000.0,
                "text": text,
            }
            if speaker is not None:
                item["speaker"] = speaker
            out.append(item)
    return out


def _transcribe_with_donkey_file(
    wav_path: str | Path,
    language: str = "ko",
) -> list[dict]:
    """온프레미스 Whisper STT API(/transcribe/file)로 파일 업로드 방식 전사.

    IP 직접 호출 + Host 헤더로 iptime 국가 차단 우회.
    Returns list of {"start": float, "end": float, "text": str, "speaker": str (optional)}.
    """
    settings = get_settings()
    api_url = (settings.donkey_stt_api_url or "").rstrip("/") + "/transcribe/file"
    api_host = settings.donkey_stt_api_host or ""

    path = Path(wav_path)
    headers = {"Host": api_host} if api_host else {}
    with path.open("rb") as f:
        with httpx.Client(timeout=600.0, headers=headers) as client:
            resp = client.post(
                api_url,
                files={"file": (path.name, f, "audio/wav")},
                data={"language": language},
            )
    resp.raise_for_status()
    body = resp.json()

    out: list[dict] = []
    for seg in (body.get("segments") or []):
        text = (seg.get("text") or "").strip()
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


def transcribe_with_url(file_url: str, language: str = "ko") -> list[dict]:
    """온프레미스 Whisper STT API로 URL 기반 전사 (worker_temp 전용).

    IP 직접 호출 + Host 헤더로 iptime 국가 차단 우회.
    Returns list of {"start": float, "end": float, "text": str, "speaker": str (optional)}.
    """
    settings = get_settings()
    api_url = (settings.donkey_stt_api_url or "").rstrip("/") + "/transcribe"
    api_host = settings.donkey_stt_api_host or ""

    headers = {"Host": api_host} if api_host else {}
    with httpx.Client(timeout=600.0, headers=headers) as client:
        resp = client.post(api_url, json={"url": file_url, "language": language})
        resp.raise_for_status()
        body = resp.json()

    out: list[dict] = []
    for seg in (body.get("segments") or []):
        text = (seg.get("text") or "").strip()
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


def transcribe_with_segments(
    wav_path: str | Path,
    language: str = "ko",
    model: str = "whisper-1",
) -> list[dict]:
    """
    설정(stt_backend)에 따라 Whisper 또는 CLOVA Speech로 전사.
    구간별 타임스탬프(시작/끝)와 텍스트를 반환.
    Returns list of {"start": float, "end": float, "text": str}.
    """
    settings = get_settings()
    return _transcribe_with_donkey_file(wav_path, language=language)

    # 아래는 레거시 (clova/whisper) — 현재 미사용
    backend = (settings.stt_backend or "").strip().lower()
    if backend == "clova":
        return _transcribe_with_clova(wav_path, language=language)

    # Whisper
    client = get_openai_client()
    path = Path(wav_path)

    with path.open("rb") as f:
        result = client.audio.transcriptions.create(
            model=model,
            file=f,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = getattr(result, "segments", None) or []
    out: list[dict] = []
    for seg in segments:
        start = float(getattr(seg, "start", 0) or 0)
        end = float(getattr(seg, "end", 0) or 0)
        text = (getattr(seg, "text", None) or "").strip()
        if text:
            out.append({"start": start, "end": end, "text": text})
    return out


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

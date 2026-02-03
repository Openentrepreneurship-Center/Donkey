import tempfile
from functools import lru_cache
from pathlib import Path

from openai import OpenAI
from pydub import AudioSegment

from app.config import get_settings


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    """Get OpenAI client (cached)."""
    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key)


def transcribe_with_segments(
    wav_path: str | Path,
    language: str = "ko",
    model: str = "whisper-1",
) -> list[dict]:
    """
    전체 오디오를 Whisper로 한 번 전사하고, 구간별 타임스탬프(시작/끝)와 텍스트를 반환.
    Returns list of {"start": float, "end": float, "text": str}.
    """
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

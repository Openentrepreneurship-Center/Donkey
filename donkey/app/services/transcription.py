from pathlib import Path

import httpx

from app.config import get_settings

def _transcribe_with_donkey_api(
    wav_path: str | Path,
    language: str = "ko",
) -> list[dict]:
    """
    Donkey STT API(/transcribe/file)로 전사.
    Returns list of {"start": float, "end": float, "text": str, "speaker"?: str | None}.
    """
    settings = get_settings()
    base_url = (settings.donkey_stt_base_url or "").rstrip("/")
    if not base_url:
        raise ValueError("DONKEY_STT_BASE_URL must be set")

    path = Path(wav_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    url = f"{base_url}/transcribe/file"
    with path.open("rb") as f:
        files = {"file": (path.name, f, "audio/wav")}
        data = {"language": language}
        with httpx.Client(timeout=float(settings.donkey_stt_timeout_seconds)) as client:
            resp = client.post(url, files=files, data=data)
    resp.raise_for_status()
    body = resp.json()

    segments_raw = body.get("segments") or []
    out: list[dict] = []
    for seg in segments_raw:
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or 0)
        text = (seg.get("text") or "").strip()
        speaker = seg.get("speaker")
        if speaker is not None:
            speaker = str(speaker)
        if text:
            item: dict = {
                "start": start,
                "end": end,
                "text": text,
            }
            item["speaker"] = speaker
            out.append(item)
    return out


def transcribe_with_segments(
    wav_path: str | Path,
    language: str = "ko",
) -> list[dict]:
    """
    Donkey STT API로 전사.
    구간별 타임스탬프(시작/끝)와 텍스트를 반환.
    Returns list of {"start": float, "end": float, "text": str, "speaker"?: str | None}.
    """
    return _transcribe_with_donkey_api(wav_path, language=language)


def seconds_to_time_str(sec: float) -> str:
    """Convert seconds to human-readable time string."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:04.1f}"
    return f"{m:02d}:{s:04.1f}"

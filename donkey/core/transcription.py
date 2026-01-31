"""Audio transcription module using OpenAI STT."""

import tempfile
from typing import Optional

from openai import OpenAI
from pydub import AudioSegment


def transcribe_segment_with_whisper(
    audio_segment: AudioSegment,
    client: OpenAI,
    language: str = "ko",
    model: str = "gpt-4o-mini-transcribe",
) -> str:
    """
    Transcribe an audio segment using OpenAI's STT API.

    Args:
        audio_segment: pydub AudioSegment to transcribe
        client: OpenAI client instance
        language: Language code (e.g., "ko" for Korean)
        model: STT model name (e.g., "gpt-4o-mini-transcribe", "whisper-1")

    Returns:
        Transcribed text
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        audio_segment.export(tmp.name, format="wav")
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                model=model,
                file=f,
                language=language,
            )
    return (result.text or "").strip()


def transcribe_file(
    file_path: str,
    client: OpenAI,
    language: str = "ko",
    model: str = "gpt-4o-mini-transcribe",
) -> str:
    """
    Transcribe an entire audio file using OpenAI's STT API.

    Args:
        file_path: Path to audio file
        client: OpenAI client instance
        language: Language code (e.g., "ko" for Korean)
        model: STT model name

    Returns:
        Transcribed text
    """
    with open(file_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=model,
            file=f,
            language=language,
        )
    return (result.text or "").strip()

from pathlib import Path
from functools import lru_cache

from pyannote.audio import Pipeline

from app.config import get_settings


@lru_cache(maxsize=1)
def get_diarization_pipeline() -> Pipeline:
    """Load pyannote diarization pipeline (cached)."""
    settings = get_settings()
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=settings.hf_token,
    )
    return pipeline


def diarize_audio(
    file_path: str | Path,
    num_speakers: int | None = None,
) -> list[tuple[float, float, str]]:
    """
    Run speaker diarization on audio file.

    Returns list of (start_sec, end_sec, speaker_label) tuples.
    """
    pipeline = get_diarization_pipeline()

    if num_speakers is not None:
        diarization = pipeline(str(file_path), num_speakers=num_speakers)
    else:
        diarization = pipeline(str(file_path))

    segments: list[tuple[float, float, str]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append((float(turn.start), float(turn.end), str(speaker)))

    segments.sort(key=lambda x: x[0])
    return segments

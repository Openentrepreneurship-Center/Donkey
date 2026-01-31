"""Speaker diarization module."""

from typing import List, Tuple, Optional

from pyannote.audio import Pipeline


def diarize_audio(
    file_path: str,
    pipeline: Pipeline,
    num_speakers: Optional[int] = None,
) -> List[Tuple[float, float, str]]:
    """
    Perform speaker diarization on an audio file.

    Args:
        file_path: Path to audio file (should be WAV 16kHz mono for best results)
        pipeline: Loaded pyannote diarization pipeline
        num_speakers: Optional fixed number of speakers (improves accuracy if known)

    Returns:
        List of (start_time, end_time, speaker_label) tuples, sorted by start time
    """
    if num_speakers is not None:
        diarization = pipeline(file_path, num_speakers=num_speakers)
    else:
        diarization = pipeline(file_path)

    segments: List[Tuple[float, float, str]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append((float(turn.start), float(turn.end), str(speaker)))

    segments.sort(key=lambda x: x[0])
    return segments

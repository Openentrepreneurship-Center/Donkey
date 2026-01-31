"""Speaker diarization module."""

from typing import List, Tuple, Optional

import torchaudio
from pyannote.audio import Pipeline
from pyannote.core import Annotation


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

    # 🔹 1. pyannote 안정성을 위한 torchaudio 로딩
    waveform, sample_rate = torchaudio.load(file_path)
    audio_dict = {"waveform": waveform, "sample_rate": sample_rate}

    # 🔹 2. diarization 실행
    if num_speakers is not None:
        diarization_out = pipeline(audio_dict, num_speakers=num_speakers)
    else:
        diarization_out = pipeline(audio_dict)

    # 🔹 3. pyannote 3.x 출력 타입 대응
    if isinstance(diarization_out, Annotation):
        diarization = diarization_out
    elif hasattr(diarization_out, "speaker_diarization"):
        diarization = diarization_out.speaker_diarization
    elif hasattr(diarization_out, "exclusive_speaker_diarization"):
        diarization = diarization_out.exclusive_speaker_diarization
    else:
        diarization = diarization_out

    # 🔹 4. 세그먼트 추출
    segments: List[Tuple[float, float, str]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append((float(turn.start), float(turn.end), str(speaker)))

    segments.sort(key=lambda x: x[0])
    return segments

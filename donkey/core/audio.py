"""Audio processing utilities."""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from pydub import AudioSegment


def ensure_wav_16k_mono(input_path: str, output_path: Optional[str] = None) -> str:
    """
    Convert audio to WAV format (16kHz mono) for pyannote/torchaudio compatibility.

    Args:
        input_path: Path to input audio file (m4a, mp3, mp4, aac, wav)
        output_path: Optional output path. If None, replaces extension with .wav

    Returns:
        Path to the converted WAV file

    Raises:
        RuntimeError: If ffmpeg is not installed or conversion fails
    """
    p = Path(input_path)

    # If already wav, return as-is
    if p.suffix.lower() == ".wav" and output_path is None:
        return input_path

    out_path = output_path or str(p.with_suffix(".wav"))
    cmd = ["ffmpeg", "-y", "-i", input_path, "-ac", "1", "-ar", "16000", out_path]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg is not installed. Install with: brew install ffmpeg")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg conversion failed:\n{e.stderr.decode(errors='ignore')}")

    return out_path


def seconds_to_time_str(sec: float) -> str:
    """
    Convert seconds to human-readable time string.

    Args:
        sec: Time in seconds

    Returns:
        Formatted time string (MM:SS.s or HH:MM:SS.s)
    """
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:04.1f}"
    return f"{m:02d}:{s:04.1f}"


def get_audio_duration(file_path: str) -> float:
    """
    Get audio file duration in seconds.

    Args:
        file_path: Path to audio file

    Returns:
        Duration in seconds
    """
    audio = AudioSegment.from_file(file_path)
    return len(audio) / 1000.0  # pydub uses milliseconds


def export_segment_to_temp_wav(audio_segment: AudioSegment) -> str:
    """
    Export an AudioSegment to a temporary WAV file.

    Args:
        audio_segment: pydub AudioSegment

    Returns:
        Path to temporary WAV file (caller must clean up)
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    audio_segment.export(tmp.name, format="wav")
    tmp.close()
    return tmp.name

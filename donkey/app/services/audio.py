import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydub import AudioSegment

from app.config import get_settings


async def download_audio(url: str, dest_path: Path) -> None:
    """Download audio file from URL."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        dest_path.write_bytes(response.content)


def ensure_wav_16k_mono(input_path: str | Path) -> Path:
    """Convert audio to 16kHz mono WAV format for Whisper and downstream processing."""
    input_path = Path(input_path)

    if input_path.suffix.lower() == ".wav":
        # Still convert to ensure 16k mono
        pass

    out_path = input_path.with_suffix(".converted.wav")
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-ac", "1", "-ar", "16000", str(out_path)
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found. Install with: brew install ffmpeg")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg conversion failed: {e.stderr.decode(errors='ignore')}")

    return out_path


def get_audio_duration(file_path: str | Path) -> float:
    """Get audio duration in seconds."""
    audio = AudioSegment.from_file(str(file_path))
    return len(audio) / 1000.0  # pydub returns milliseconds


def extract_segment(audio: AudioSegment, start_sec: float, end_sec: float) -> AudioSegment:
    """Extract a segment from audio."""
    return audio[int(start_sec * 1000):int(end_sec * 1000)]


def upload_audio_to_s3(wav_path: str | Path, job_id: str) -> bool:
    """
    변환된 WAV 파일을 S3 버킷의 audio-data(또는 s3_audio_prefix) 폴더에 업로드.
    s3_logs_bucket이 없거나 save_audio_to_s3=False면 스킵.
    """
    settings = get_settings()
    if not settings.s3_logs_bucket or not settings.save_audio_to_s3:
        return False
    try:
        import boto3
        from botocore.exceptions import ClientError

        path = Path(wav_path)
        if not path.exists():
            return False
        client = boto3.client("s3", region_name=settings.aws_region)
        date_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        key = f"{settings.s3_audio_prefix.rstrip('/')}/{date_prefix}/{job_id}.wav"
        with path.open("rb") as f:
            client.put_object(
                Bucket=settings.s3_logs_bucket,
                Key=key,
                Body=f,
                ContentType="audio/wav",
            )
        return True
    except (ClientError, Exception):
        return False

"""Pipeline orchestration module."""

from dataclasses import dataclass
from typing import List, Optional, Callable

from openai import OpenAI
from pyannote.audio import Pipeline
from pydub import AudioSegment

from .audio import seconds_to_time_str
from .diarization import diarize_audio
from .transcription import transcribe_segment_with_whisper
from .soap import soap_summarize_with_disclaimer


@dataclass
class TranscriptionSegment:
    """A single transcribed segment with speaker info."""
    speaker: str
    start: float
    end: float
    text: str


@dataclass
class DiarizationResult:
    """Result of diarization and transcription."""
    transcript: str
    segments: List[TranscriptionSegment]
    speaker_count: int
    duration_seconds: float


@dataclass
class FullPipelineResult:
    """Result of the full pipeline (diarization + SOAP)."""
    diarization: DiarizationResult
    soap_summary: str
    disclaimer: str


def diarize_and_transcribe(
    file_path: str,
    pipeline: Pipeline,
    client: OpenAI,
    language: str = "ko",
    model: str = "gpt-4o-mini-transcribe",
    num_speakers: Optional[int] = None,
    min_segment_duration: float = 0.6,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> DiarizationResult:
    """
    Perform diarization and transcription on an audio file.

    Args:
        file_path: Path to audio file (WAV 16kHz mono recommended)
        pipeline: Loaded pyannote diarization pipeline
        client: OpenAI client instance
        language: Language code for transcription
        model: STT model name
        num_speakers: Optional fixed number of speakers
        min_segment_duration: Minimum segment duration in seconds (skip shorter)
        progress_callback: Optional callback(current, total, message) for progress updates

    Returns:
        DiarizationResult with transcript, segments, speaker count, and duration
    """
    # Step 1: Run diarization
    if progress_callback:
        progress_callback(0, 100, "Running speaker diarization...")

    segments = diarize_audio(file_path, pipeline, num_speakers=num_speakers)

    if not segments:
        audio = AudioSegment.from_file(file_path)
        return DiarizationResult(
            transcript="",
            segments=[],
            speaker_count=0,
            duration_seconds=len(audio) / 1000.0,
        )

    audio = AudioSegment.from_file(file_path)
    duration_seconds = len(audio) / 1000.0

    # Count unique speakers
    speakers = set(seg[2] for seg in segments)

    # Step 2: Transcribe each segment
    lines: List[str] = []
    transcription_segments: List[TranscriptionSegment] = []

    # Filter segments by duration
    valid_segments = [(s, e, spk) for s, e, spk in segments if (e - s) >= min_segment_duration]
    total_segments = len(valid_segments)

    for idx, (start, end, speaker) in enumerate(valid_segments):
        if progress_callback:
            progress = int(10 + (idx / total_segments) * 85)  # 10-95%
            progress_callback(progress, 100, f"Transcribing segment {idx + 1}/{total_segments}")

        seg_audio = audio[int(start * 1000): int(end * 1000)]

        try:
            text = transcribe_segment_with_whisper(seg_audio, client, language=language, model=model)
        except Exception:
            text = ""

        if not text:
            continue

        lines.append(f"[{speaker}] {seconds_to_time_str(start)}–{seconds_to_time_str(end)}: {text}")
        transcription_segments.append(TranscriptionSegment(
            speaker=speaker,
            start=start,
            end=end,
            text=text,
        ))

    if progress_callback:
        progress_callback(100, 100, "Transcription complete")

    return DiarizationResult(
        transcript="\n".join(lines),
        segments=transcription_segments,
        speaker_count=len(speakers),
        duration_seconds=duration_seconds,
    )


def process_full_pipeline(
    file_path: str,
    pipeline: Pipeline,
    client: OpenAI,
    language: str = "ko",
    stt_model: str = "gpt-4o-mini-transcribe",
    chat_model: str = "gpt-4o-mini",
    num_speakers: Optional[int] = None,
    min_segment_duration: float = 0.6,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> FullPipelineResult:
    """
    Run the full pipeline: diarization + transcription + SOAP summary.

    Args:
        file_path: Path to audio file (WAV 16kHz mono recommended)
        pipeline: Loaded pyannote diarization pipeline
        client: OpenAI client instance
        language: Language code for transcription
        stt_model: STT model name
        chat_model: Chat model for SOAP summarization
        num_speakers: Optional fixed number of speakers
        min_segment_duration: Minimum segment duration in seconds
        progress_callback: Optional callback(current, total, message) for progress updates

    Returns:
        FullPipelineResult with diarization result and SOAP summary
    """
    # Step 1: Diarization and transcription (0-80%)
    def diarization_progress(current: int, total: int, message: str) -> None:
        if progress_callback:
            scaled = int(current * 0.8)  # Scale to 0-80%
            progress_callback(scaled, 100, message)

    diarization_result = diarize_and_transcribe(
        file_path=file_path,
        pipeline=pipeline,
        client=client,
        language=language,
        model=stt_model,
        num_speakers=num_speakers,
        min_segment_duration=min_segment_duration,
        progress_callback=diarization_progress,
    )

    if not diarization_result.transcript:
        return FullPipelineResult(
            diarization=diarization_result,
            soap_summary="",
            disclaimer="전사 결과가 비어 있어 SOAP 요약을 생성할 수 없습니다.",
        )

    # Step 2: SOAP summarization (80-100%)
    if progress_callback:
        progress_callback(85, 100, "Generating SOAP summary...")

    soap_text = soap_summarize_with_disclaimer(
        diarization_result.transcript,
        client,
        chat_model,
    )

    # Split soap text and disclaimer
    if "\n\n---\n" in soap_text:
        summary, disclaimer = soap_text.rsplit("\n\n---\n", 1)
    else:
        summary = soap_text
        disclaimer = ""

    if progress_callback:
        progress_callback(100, 100, "Pipeline complete")

    return FullPipelineResult(
        diarization=diarization_result,
        soap_summary=summary,
        disclaimer=disclaimer.strip(),
    )

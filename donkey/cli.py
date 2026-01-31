"""Command-line interface for Donkey."""

import argparse
import os
from pathlib import Path

from openai import OpenAI
from pyannote.audio import Pipeline

from donkey.config import get_settings
from donkey.core.audio import ensure_wav_16k_mono
from donkey.core.pipeline import diarize_and_transcribe
from donkey.core.soap import soap_summarize_with_disclaimer


def find_recording_file(recording_num: int, base_dir: str = ".") -> str | None:
    """
    Find a recording file by number (supports various formats).

    Args:
        recording_num: Recording number to find
        base_dir: Base directory to search in

    Returns:
        File path if found, None otherwise
    """
    possible_names = [
        f"Recording {recording_num}",
        f"Recording{recording_num}",
        f"recording {recording_num}",
        f"recording{recording_num}",
    ]
    possible_extensions = [".m4a", ".wav", ".mp3", ".mp4", ".aac"]

    for name in possible_names:
        for ext in possible_extensions:
            full_path = os.path.join(base_dir, name + ext)
            if os.path.exists(full_path):
                return full_path

    return None


def process_single_file(
    audio_path: str,
    pipeline: Pipeline,
    client: OpenAI,
    language: str = "ko",
    stt_model: str = "gpt-4o-mini-transcribe",
    chat_model: str = "gpt-4o-mini",
    num_speakers: int | None = None,
    min_seg: float = 0.6,
) -> None:
    """
    Process a single audio file: diarization + transcription + SOAP.

    Args:
        audio_path: Path to audio file
        pipeline: Loaded pyannote pipeline
        client: OpenAI client
        language: Language code
        stt_model: STT model name
        chat_model: Chat model name
        num_speakers: Optional fixed number of speakers
        min_seg: Minimum segment duration
    """
    audio_path_processed = ensure_wav_16k_mono(audio_path)
    if not os.path.exists(audio_path_processed):
        raise FileNotFoundError(f"파일이 없습니다: {audio_path_processed}")

    # Output file paths based on original filename
    original_base = os.path.splitext(audio_path)[0]
    diarized_path = original_base + "_diarized.txt"
    soap_path = original_base + "_SOAP.txt"

    # Step 1: Diarization and transcription
    print(f"\n{'='*60}")
    print(f"📁 Processing: {audio_path}")
    print(f"{'='*60}")

    def progress_callback(current: int, total: int, message: str) -> None:
        print(f"  [{current:3d}%] {message}")

    result = diarize_and_transcribe(
        file_path=audio_path_processed,
        pipeline=pipeline,
        client=client,
        language=language,
        model=stt_model,
        num_speakers=num_speakers,
        min_segment_duration=min_seg,
        progress_callback=progress_callback,
    )

    if not result.transcript:
        print(f"⚠️ {audio_path}: diarized 전사 결과가 비어 있습니다(무음/너무 짧은 발화일 수 있음).")
        return

    with open(diarized_path, "w", encoding="utf-8") as f:
        f.write(result.transcript)
    print(f"✅ Saved diarized transcript: {diarized_path}")

    # Step 2: SOAP summarization
    print(f"🧾 Generating SOAP summary for {audio_path}...")
    soap_text = soap_summarize_with_disclaimer(result.transcript, client, chat_model)

    with open(soap_path, "w", encoding="utf-8") as f:
        f.write(soap_text)
    print(f"✅ Saved SOAP summary: {soap_path}")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Donkey - pyannote(3.1) + OpenAI STT + SOAP summarization"
    )
    parser.add_argument(
        "audio",
        type=str,
        nargs="*",
        help="Input audio file paths (multiple allowed) or use --numbers",
    )
    parser.add_argument(
        "--numbers",
        type=int,
        nargs="+",
        help="Recording numbers to process (e.g., --numbers 7 8 9 10 11)",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=None,
        help="Number of speakers (optional, improves accuracy if known)",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="ko",
        help="Language code (default: ko)",
    )
    parser.add_argument(
        "--stt_model",
        type=str,
        default="gpt-4o-mini-transcribe",
        help='STT model (default: "gpt-4o-mini-transcribe")',
    )
    parser.add_argument(
        "--chat_model",
        type=str,
        default="gpt-4o-mini",
        help='Chat model for SOAP (default: "gpt-4o-mini")',
    )
    parser.add_argument(
        "--min_seg",
        type=float,
        default=0.6,
        help="Minimum segment duration in seconds (default: 0.6)",
    )
    args = parser.parse_args()

    # Build file list
    audio_files = []

    # Find files by recording numbers
    if args.numbers:
        base_dir = os.path.dirname(os.path.abspath(__file__)) if __file__ else "."
        for num in args.numbers:
            found = find_recording_file(num, base_dir)
            if found:
                audio_files.append(found)
                print(f"✅ Found: Recording {num} -> {found}")
            else:
                print(f"⚠️ Warning: Recording {num} 파일을 찾을 수 없습니다.")

    # Add directly specified files
    if args.audio:
        audio_files.extend(args.audio)

    if not audio_files:
        parser.error("파일을 지정해주세요. (예: donkey Recording.wav 또는 --numbers 7 8 9)")

    print(f"\n🎯 총 {len(audio_files)}개 파일 처리 예정:")
    for f in audio_files:
        print(f"   - {f}")
    print()

    # Initialize models
    settings = get_settings()

    print("⏳ Loading pyannote pipeline (3.1)...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=settings.hf_token,
    )
    print("✅ Diarization pipeline loaded.")

    client = OpenAI(api_key=settings.openai_api_key)

    # Process each file
    success_count = 0
    for idx, audio_file in enumerate(audio_files, start=1):
        try:
            print(f"\n[{idx}/{len(audio_files)}] 처리 중...")
            process_single_file(
                audio_path=audio_file,
                pipeline=pipeline,
                client=client,
                language=args.language,
                stt_model=args.stt_model,
                chat_model=args.chat_model,
                num_speakers=args.speakers,
                min_seg=args.min_seg,
            )
            success_count += 1
        except Exception as e:
            print(f"❌ {audio_file} 처리 실패: {e}")
            continue

    print(f"\n{'='*60}")
    print(f"🎉 완료! {success_count}/{len(audio_files)}개 파일 처리 완료.")
    print(f"   총 {success_count * 2}개 파일 생성됨 (diarized + SOAP 각 {success_count}개)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

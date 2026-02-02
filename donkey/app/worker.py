import tempfile
import traceback
from pathlib import Path

from pydub import AudioSegment

from app.config import get_settings
from app.store.redis import get_job_store
from app.services.audio import download_audio, ensure_wav_16k_mono, get_audio_duration
from app.services.diarization import diarize_audio
from app.services.transcription import transcribe_segment, seconds_to_time_str
from app.services.summarization import (
    generate_soap_summary,
    generate_title,
    generate_simple_summary,
    parse_soap_to_consultation_summary,
)
from app.services.pii_filter import filter_pii
from app.services.validation import validate_medical_conversation
from app.services.job_logger import JobLogger


async def process_audio_job(job_id: str, file_url: str) -> None:
    """
    Process audio file and update job status in Redis.

    Pipeline:
    1. Download audio from URL
    2. Convert to WAV 16kHz mono
    3. Run speaker diarization
    4. Transcribe each segment
    5. Validate as medical conversation
    6. Filter PII
    7. Generate SOAP summary, title, simpleSummary
    8. Update Redis with results
    9. Save job log to S3
    """
    store = await get_job_store()
    settings = get_settings()
    logger = JobLogger(job_id=job_id, file_url=file_url)
    current_stage = ""

    try:
        await store.update_job(job_id, {"status": "processing"})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # 1. Download audio
            current_stage = "download"
            logger.start_stage()
            url_path = file_url.split("?")[0]
            ext = Path(url_path).suffix or ".wav"
            audio_path = tmpdir_path / f"input{ext}"
            await download_audio(file_url, audio_path)
            logger.end_stage("download_time_ms")

            # 2. Convert to WAV
            current_stage = "conversion"
            logger.start_stage()
            wav_path = ensure_wav_16k_mono(audio_path)
            logger.end_stage("conversion_time_ms")

            # Get duration
            duration = get_audio_duration(wav_path)
            logger.set_audio_duration(duration)

            # 3. Diarization
            current_stage = "diarization"
            logger.start_stage()
            segments = diarize_audio(
                wav_path,
                num_speakers=settings.default_num_speakers,
            )
            logger.end_stage("diarization_time_ms")

            if not segments:
                logger.set_quality(
                    is_abusing=True,
                    abusing_reason="음성이 감지되지 않았습니다",
                    speaker_count=0,
                    segment_count=0,
                )
                await store.update_job(job_id, {
                    "status": "completed",
                    "isGenerated": True,
                    "isAbusing": True,
                    "abusingReason": "음성이 감지되지 않았습니다",
                    "duration": duration,
                    "title": "",
                    "simpleSummary": "",
                    "consultationSummary": None,
                })
                logger.complete("completed")
                await logger.save_to_s3()
                return

            # Count unique speakers
            unique_speakers = set(seg[2] for seg in segments)
            logger.set_quality(speaker_count=len(unique_speakers))

            # 4. Transcribe
            current_stage = "transcription"
            logger.start_stage()
            audio = AudioSegment.from_file(str(wav_path))
            diarized_lines: list[str] = []

            for start, end, speaker in segments:
                seg_duration = end - start
                if seg_duration < settings.min_segment_duration:
                    continue

                seg_audio = audio[int(start * 1000):int(end * 1000)]

                try:
                    text = transcribe_segment(
                        seg_audio,
                        language=settings.default_language,
                        model=settings.stt_model,
                    )
                except Exception:
                    text = ""

                if text:
                    line = f"[{speaker}] {seconds_to_time_str(start)}–{seconds_to_time_str(end)}: {text}"
                    diarized_lines.append(line)

            logger.end_stage("transcription_time_ms")
            logger.set_quality(segment_count=len(diarized_lines))

            if not diarized_lines:
                logger.set_quality(
                    is_abusing=True,
                    abusing_reason="전사할 수 있는 음성이 없습니다",
                )
                await store.update_job(job_id, {
                    "status": "completed",
                    "isGenerated": True,
                    "isAbusing": True,
                    "abusingReason": "전사할 수 있는 음성이 없습니다",
                    "duration": duration,
                    "title": "",
                    "simpleSummary": "",
                    "consultationSummary": None,
                })
                logger.complete("completed")
                await logger.save_to_s3()
                return

            diarized_text = "\n".join(diarized_lines)

            # 5. Validate as medical conversation
            current_stage = "validation"
            logger.start_stage()
            is_valid, abuse_reason = validate_medical_conversation(
                diarized_text,
                chat_model=settings.chat_model,
            )
            logger.end_stage("validation_time_ms")

            if not is_valid:
                logger.set_quality(
                    is_abusing=True,
                    abusing_reason=abuse_reason or "진료 대화가 아님",
                )
                await store.update_job(job_id, {
                    "status": "completed",
                    "isGenerated": True,
                    "isAbusing": True,
                    "abusingReason": abuse_reason or "진료 대화가 아님",
                    "duration": duration,
                    "title": "",
                    "simpleSummary": "",
                    "consultationSummary": None,
                })
                logger.complete("completed")
                await logger.save_to_s3()
                return

            # 6. Filter PII
            current_stage = "pii_filter"
            logger.start_stage()
            filtered_text = filter_pii(diarized_text)
            filtered_lines = [filter_pii(line) for line in diarized_lines]
            logger.end_stage("pii_filter_time_ms")

            # 7. Generate summaries
            current_stage = "summarization"
            logger.start_stage()
            soap_text = generate_soap_summary(filtered_text, settings.chat_model)
            title = generate_title(filtered_text, settings.chat_model)
            simple_summary = generate_simple_summary(filtered_text, settings.chat_model)
            logger.end_stage("summarization_time_ms")

            # Parse SOAP into structured format
            consultation_summary = parse_soap_to_consultation_summary(
                soap_text,
                filtered_lines,
            )

            # Set final quality metrics
            logger.set_quality(
                is_abusing=False,
                abusing_reason="",
                speaker_count=len(unique_speakers),
                segment_count=len(diarized_lines),
            )

            # 8. Update job with results
            await store.update_job(job_id, {
                "status": "completed",
                "isGenerated": True,
                "isAbusing": False,
                "abusingReason": "",
                "duration": duration,
                "title": title,
                "simpleSummary": simple_summary,
                "consultationSummary": consultation_summary.model_dump(),
            })

            logger.complete("completed")

    except Exception as e:
        error_msg = f"처리 중 오류 발생: {str(e)}"
        traceback.print_exc()

        logger.set_error(
            error_type=type(e).__name__,
            error_message=str(e),
            error_stage=current_stage,
        )
        logger.complete("error")

        await store.update_job(job_id, {
            "status": "error",
            "error": error_msg,
            "isGenerated": False,
            "isAbusing": False,
            "abusingReason": "",
        })

    finally:
        # 9. Save log to S3
        await logger.save_to_s3()

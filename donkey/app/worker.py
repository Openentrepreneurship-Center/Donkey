import asyncio
import logging
import tempfile
import time
import traceback
from pathlib import Path

from app.config import get_settings, get_processing_timeout_seconds
from app.store.redis import get_job_store

logger = logging.getLogger(__name__)

_DB_RETRY_COUNT = 3
_DB_RETRY_DELAY = 2  # seconds
from app.services.audio import (
    download_audio,
    ensure_wav_16k_mono,
    get_audio_duration,
    upload_audio_to_s3,
)
from app.services.rule_based_diarization import (
    diarize_from_whisper_segments,
    map_clova_speakers_to_roles,
)
from app.services.transcription import transcribe_with_segments, seconds_to_time_str
from app.services.summarization import (
    generate_soap_summary,
    generate_title,
    generate_simple_summary,
    parse_soap_to_consultation_summary,
)
from app.services.pii_filter import filter_pii, filter_pii_with_screening
from app.services.validation import validate_medical_conversation
from app.services.job_logger import JobLogger
from app.services.slack import notify_slack

# 음성 길이 기준 처리 임계 초과 시 오류 메시지
TIMEOUT_ERROR_MESSAGE = "처리 시간이 제한을 초과했습니다. (오디오 길이 기준 임계시간)"

# 클라이언트에 노출할 공통 메시지 (세부 예외는 로그/DB에만)
CLIENT_ERROR_MESSAGE = "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


async def _persist_consultation_if_configured(
    store,
    job_id: str,
    logger_instance: JobLogger,
    *,
    stored_audio_url: str | None = None,
) -> None:
    """DATABASE_URL 있으면 Redis job + JobLog 기준으로 consultation/log/summary 테이블 갱신. 실패 시 재시도."""
    from app.db import is_db_configured
    if not is_db_configured():
        return
    from app.db.session import get_session
    from app.db.repository import persist_request_from_job
    for attempt in range(1, _DB_RETRY_COUNT + 1):
        try:
            job = await store.get_job(job_id)
            if not job:
                return
            async with get_session() as session:
                await persist_request_from_job(
                    session, job_id, job, logger_instance.log.to_dict(),
                    stored_audio_url=stored_audio_url,
                )
            return
        except Exception as e:
            logger.warning(
                "DB persist failed (job_id=%s, attempt %d/%d): %s",
                job_id, attempt, _DB_RETRY_COUNT, e,
            )
            if attempt < _DB_RETRY_COUNT:
                await asyncio.sleep(_DB_RETRY_DELAY * attempt)
    logger.error("DB persist exhausted retries (job_id=%s)", job_id)


async def _check_timeout_and_abort(
    store, job_id: str, start_time: float, timeout_sec: int, logger: JobLogger
) -> bool:
    """처리 시간이 임계시간을 초과했으면 job을 error로 갱신하고 True 반환. 아니면 False."""
    if (time.time() - start_time) <= timeout_sec:
        return False
    logger.set_error(
        error_type="ProcessingTimeout",
        error_message=TIMEOUT_ERROR_MESSAGE,
        error_stage="timeout",
    )
    logger.complete("error")
    await store.update_job(job_id, {
        "status": "error",
        "error": TIMEOUT_ERROR_MESSAGE,
        "isGenerated": False,
        "isAbusing": False,
        "abusingReason": "",
        "isScreening": False,
        "screeningReason": "해당되는 내용 없음.",
        "screening": {"names": [], "phones": []},
    })
    notify_slack(
        get_settings().slack_webhook_url,
        f"🚨 [Donkey] AI 처리 오류\njob_id: {job_id}\n원인: {TIMEOUT_ERROR_MESSAGE}\nstage: timeout",
    )
    await _persist_consultation_if_configured(store, job_id, logger)
    return True


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
        start_time = time.time()
        await store.update_job(job_id, {"status": "processing"})

        # DB 저장은 마지막 _persist_consultation_if_configured에서 한 번에 (없으면 생성 + 데이터 채움)

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

            # Get duration → 음성 길이 기준 임계시간 설정 (테스트 시 override 사용)
            duration = get_audio_duration(wav_path)
            logger.set_audio_duration(duration)
            if settings.processing_timeout_override_seconds > 0:
                timeout_sec = settings.processing_timeout_override_seconds
            else:
                timeout_sec = get_processing_timeout_seconds(duration)
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            # 변환된 오디오를 S3 audio-data 폴더에 업로드 (설정 시). DB 반영은 persist 이후에.
            s3_audio_url = None
            try:
                s3_audio_url = upload_audio_to_s3(wav_path, job_id)
            except Exception:
                pass

            diarized_lines: list[str]
            unique_speakers: set[str]

            # 3. Whisper 1회 전사(구간 타임스탬프 포함)
            current_stage = "transcription"
            logger.start_stage()
            try:
                whisper_segments = transcribe_with_segments(
                    file_url,
                    language=settings.default_language,
                    model=settings.whisper_segment_model,
                )
            except Exception:
                whisper_segments = []
            logger.end_stage("transcription_time_ms")
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            # Whisper 전사문을 eval_data에 hypothesis txt로 저장 (설정 시)
            if whisper_segments and settings.save_whisper_to_eval_data:
                try:
                    eval_data_dir = Path(__file__).resolve().parent / "metrics" / "eval_data"
                    eval_data_dir.mkdir(parents=True, exist_ok=True)
                    hyp_path = eval_data_dir / f"{job_id}_hyp.txt"
                    full_text = "\n".join((s.get("text") or "").strip() for s in whisper_segments)
                    hyp_path.write_text(full_text.strip(), encoding="utf-8")
                except Exception:
                    pass  # 저장 실패 시 파이프라인은 계속 진행

            if not whisper_segments:
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
                    "isScreening": False,
                    "screeningReason": "해당되는 내용 없음.",
                    "screening": {"names": [], "phones": []},
                    "duration": duration,
                    "title": "",
                    "simpleSummary": "",
                    "consultationSummary": None,
                })
                logger.complete("completed")
                await _persist_consultation_if_configured(store, job_id, logger, stored_audio_url=s3_audio_url)
                await logger.save_to_s3()
                return

            # 4. 화자 처리
            # - 신규 STT 포맷(role/index/content): STT 라벨을 그대로 사용 (별도 diarization 생략)
            # - 기존 포맷(start/end/text): 기존 diarization 로직 유지
            current_stage = "diarization"
            logger.start_stage()
            use_role_labeled_segments = bool(whisper_segments and whisper_segments[0].get("role"))
            if use_role_labeled_segments:
                role_segments = [
                    s for s in whisper_segments
                    if (s.get("text") or "").strip()
                ]
                role_segments.sort(key=lambda s: int(s.get("index") or 0))
                diarized_lines = []
                for seg in role_segments:
                    role = str(seg.get("role") or "UNKNOWN")
                    text = (seg.get("text") or "").strip()
                    if text:
                        diarized_lines.append(f"[{role}] {text}")
                unique_speakers = {str(s.get("role") or "UNKNOWN") for s in role_segments}
            else:
                valid_segments = [
                    s
                    for s in whisper_segments
                    if (s["end"] - s["start"]) >= settings.min_segment_duration
                    and (s.get("text") or "").strip()
                ]
                use_clova_speakers = (
                    (settings.stt_backend or "").strip().lower() == "clova"
                    and valid_segments
                    and valid_segments[0].get("speaker") is not None
                )
                if use_clova_speakers:
                    diarized_segments = map_clova_speakers_to_roles(valid_segments)
                else:
                    diarized_segments = diarize_from_whisper_segments(
                        wav_path,
                        whisper_segments,
                        min_segment_duration=settings.min_segment_duration,
                    )
                unique_speakers = set(seg[2] for seg in diarized_segments)
                # 구간과 화자 라벨 매칭 (같은 순서)
                diarized_lines = []
                for seg, (start, end, speaker) in zip(valid_segments, diarized_segments):
                    text = (seg.get("text") or "").strip()
                    if text:
                        line = f"[{speaker}] {seconds_to_time_str(start)}–{seconds_to_time_str(end)}: {text}"
                        diarized_lines.append(line)
            logger.end_stage("diarization_time_ms")
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            logger.set_quality(speaker_count=len(unique_speakers))
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
                    "isScreening": False,
                    "screeningReason": "해당되는 내용 없음.",
                    "screening": {"names": [], "phones": []},
                    "duration": duration,
                    "title": "",
                    "simpleSummary": "",
                    "consultationSummary": None,
                })
                logger.complete("completed")
                await _persist_consultation_if_configured(store, job_id, logger, stored_audio_url=s3_audio_url)
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
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            is_abusing = not is_valid
            abusing_reason = (abuse_reason or "진료 대화가 아님") if is_abusing else ""

            # 6. Filter PII
            current_stage = "pii_filter"
            logger.start_stage()
            filtered_text, screening_data = filter_pii_with_screening(diarized_text)
            filtered_lines = [filter_pii(line) for line in diarized_lines]
            is_screening = bool(screening_data["names"] or screening_data["phones"])
            screening_reason = "해당되는 내용 발견." if is_screening else "해당되는 내용 없음."
            screening = {"names": screening_data["names"], "phones": screening_data["phones"]}
            logger.end_stage("pii_filter_time_ms")
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            # 7. Generate summaries
            current_stage = "summarization"
            logger.start_stage()
            soap_text = generate_soap_summary(filtered_text, settings.chat_model)
            title = generate_title(filtered_text, settings.chat_model)
            simple_summary = generate_simple_summary(filtered_text, settings.chat_model)
            logger.end_stage("summarization_time_ms")
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            # Parse SOAP into consultationSummary (S→symptomRecord, O→testResults, A→doctorNotes, P→prescriptionAndCare)
            consultation_summary = parse_soap_to_consultation_summary(soap_text, filtered_lines)

            # Set final quality metrics
            logger.set_quality(
                is_abusing=is_abusing,
                abusing_reason=abusing_reason,
                speaker_count=len(unique_speakers),
                segment_count=len(diarized_lines),
            )

            # 8. Update job with results
            await store.update_job(job_id, {
                "status": "completed",
                "isGenerated": True,
                "isAbusing": is_abusing,
                "abusingReason": abusing_reason,
                "isScreening": is_screening,
                "screeningReason": screening_reason,
                "screening": screening,
                "duration": duration,
                "title": title,
                "simpleSummary": simple_summary,
                "consultationSummary": consultation_summary.model_dump(),
            })
            logger.complete("completed")
            await _persist_consultation_if_configured(store, job_id, logger, stored_audio_url=s3_audio_url)

    except Exception as e:
        traceback.print_exc()

        logger.set_error(
            error_type=type(e).__name__,
            error_message=str(e),
            error_stage=current_stage,
        )
        logger.complete("error")

        await store.update_job(job_id, {
            "status": "error",
            "error": CLIENT_ERROR_MESSAGE,
            "isGenerated": False,
            "isAbusing": False,
            "abusingReason": "",
            "isScreening": False,
            "screeningReason": "해당되는 내용 없음.",
            "screening": {"names": [], "phones": []},
        })
        notify_slack(
            get_settings().slack_webhook_url,
            f"🚨 [Donkey] AI 처리 오류\njob_id: {job_id}\n원인: {type(e).__name__}: {e}\nstage: {current_stage}",
        )
        await _persist_consultation_if_configured(
            store, job_id, logger,
            stored_audio_url=locals().get("s3_audio_url"),
        )

    finally:
        # 9. Save log to S3
        await logger.save_to_s3()

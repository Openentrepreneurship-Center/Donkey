import asyncio
import logging
import tempfile
import time
import traceback
from pathlib import Path

from app.config import get_settings, get_processing_timeout_seconds
from app.schemas.response import ConsultationSummary
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
from app.services.hippo_consultation_audio import (
    fetch_consultation_audio,
    suffix_for_audio_content_type,
)
from app.services.transcription import (
    transcribe_with_segments,
    transcribe_with_segments_from_file,
    seconds_to_time_str,
)
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


async def process_audio_job(
    job_id: str,
    *,
    file_url: str | None = None,
    file_id: str | None = None,
) -> None:
    """
    Process audio file and update job status in Redis.

    ``file_url`` 또는 ``file_id`` 중 하나만 지정한다.

    Pipeline:
    1. Download audio from URL (또는 상담 file_id로 히포 조회)
    2. Convert to WAV 16kHz mono
    3. Run speaker diarization
    4. Transcribe each segment
    5. Validate as medical conversation
    6. Filter PII
    7. Generate SOAP summary, title, simpleSummary
    8. Update Redis with results
    9. Save job log to S3
    """
    if (file_url is None) == (file_id is None):
        raise ValueError("Specify exactly one of file_url or file_id")
    if file_url is not None and not str(file_url).strip():
        raise ValueError("file_url must be non-empty")
    if file_id is not None and not str(file_id).strip():
        raise ValueError("file_id must be non-empty")

    store = await get_job_store()
    settings = get_settings()
    log_file_ref = str(file_url).strip() if file_url else f"consultation:{str(file_id).strip()}"
    run_logger = logging.getLogger(__name__)
    logger = JobLogger(job_id=job_id, file_url=log_file_ref)
    current_stage = ""

    try:
        start_time = time.time()
        run_logger.info(
            "AI pipeline start job_id=%s source=%s ref=%s",
            job_id,
            "file_url" if file_url is not None else "file_id",
            log_file_ref,
        )
        await store.update_job(job_id, {"status": "processing"})

        # DB 저장은 마지막 _persist_consultation_if_configured에서 한 번에 (없으면 생성 + 데이터 채움)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # 1. Download audio (URL) or fetch from Hippo (file_id)
            current_stage = "download"
            logger.start_stage()
            stt_content_type = "application/octet-stream"
            if file_url is not None:
                fu = str(file_url).strip()
                run_logger.info("Stage[download] start job_id=%s source=url", job_id)
                url_path = fu.split("?")[0]
                ext = Path(url_path).suffix or ".wav"
                audio_path = tmpdir_path / f"input{ext}"
                await download_audio(fu, audio_path)
                run_logger.info(
                    "Stage[download] done job_id=%s source=url path=%s bytes=%s",
                    job_id,
                    audio_path.name,
                    audio_path.stat().st_size if audio_path.exists() else 0,
                )
            else:
                fid = str(file_id).strip()
                run_logger.info("Stage[download] start job_id=%s source=file_id id=%s", job_id, fid)
                payload = await fetch_consultation_audio(fid)
                stt_content_type = payload.content_type
                ext = suffix_for_audio_content_type(payload.content_type)
                audio_path = tmpdir_path / f"input{ext}"
                audio_path.write_bytes(payload.raw_bytes)
                run_logger.info(
                    "Stage[download] done job_id=%s source=file_id id=%s path=%s bytes=%s content_type=%s",
                    job_id,
                    fid,
                    audio_path.name,
                    len(payload.raw_bytes),
                    payload.content_type,
                )
            logger.end_stage("download_time_ms")

            # 2. Convert to WAV
            current_stage = "conversion"
            logger.start_stage()
            run_logger.info("Stage[conversion] start job_id=%s input=%s", job_id, audio_path.name)
            wav_path = ensure_wav_16k_mono(audio_path)
            logger.end_stage("conversion_time_ms")
            run_logger.info("Stage[conversion] done job_id=%s output=%s", job_id, wav_path.name)

            # Get duration → 음성 길이 기준 임계시간 설정 (테스트 시 override 사용)
            duration = get_audio_duration(wav_path)
            logger.set_audio_duration(duration)
            if settings.processing_timeout_override_seconds > 0:
                timeout_sec = settings.processing_timeout_override_seconds
            else:
                timeout_sec = get_processing_timeout_seconds(duration)
            run_logger.info(
                "Stage[conversion] metrics job_id=%s duration_sec=%.2f timeout_sec=%s",
                job_id,
                duration,
                timeout_sec,
            )
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
            eval_job_id: str | None = None
            run_logger.info("Stage[transcription] start job_id=%s", job_id)
            try:
                if file_url is not None:
                    whisper_segments, eval_job_id = await asyncio.to_thread(
                        transcribe_with_segments,
                        str(file_url).strip(),
                        settings.default_language,
                        settings.whisper_segment_model,
                    )
                else:
                    whisper_segments, eval_job_id = await asyncio.to_thread(
                        transcribe_with_segments_from_file,
                        audio_path,
                        content_type=stt_content_type,
                        filename=audio_path.name,
                        language=settings.default_language,
                        model=settings.whisper_segment_model,
                    )
            except Exception:
                whisper_segments = []
                eval_job_id = None
            logger.end_stage("transcription_time_ms")
            run_logger.info(
                "Stage[transcription] done job_id=%s segments=%s eval_job_id=%s",
                job_id,
                len(whisper_segments),
                eval_job_id or "(none)",
            )
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
                run_logger.warning("Stage[transcription] empty result job_id=%s", job_id)
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
                    "consultationSummary": ConsultationSummary().model_dump(),
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
            run_logger.info("Stage[diarization] start job_id=%s", job_id)
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
            run_logger.info(
                "Stage[diarization] done job_id=%s speakers=%s lines=%s mode=%s",
                job_id,
                len(unique_speakers),
                len(diarized_lines),
                "role_labeled" if use_role_labeled_segments else "rule_based",
            )
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            logger.set_quality(speaker_count=len(unique_speakers))
            logger.set_quality(segment_count=len(diarized_lines))

            if not diarized_lines:
                run_logger.warning("Stage[diarization] no usable lines job_id=%s", job_id)
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
                    "consultationSummary": ConsultationSummary().model_dump(),
                })
                logger.complete("completed")
                await _persist_consultation_if_configured(store, job_id, logger, stored_audio_url=s3_audio_url)
                await logger.save_to_s3()
                return

            diarized_text = "\n".join(diarized_lines)
            validation_abuse_reason: str | None = None

            # 5. Validate as medical conversation
            current_stage = "validation"
            logger.start_stage()
            run_logger.info("Stage[validation] start job_id=%s", job_id)
            is_valid, abuse_reason = validate_medical_conversation(
                diarized_text,
                chat_model=settings.chat_model,
                job_logger=logger,
            )
            logger.end_stage("validation_time_ms")
            run_logger.info(
                "Stage[validation] done job_id=%s is_valid=%s",
                job_id,
                is_valid,
            )
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            if not is_valid:
                validation_abuse_reason = abuse_reason or "진료 대화가 아님"
                logger.set_quality(
                    is_abusing=True,
                    abusing_reason=validation_abuse_reason,
                )

            # 6. Filter PII
            current_stage = "pii_filter"
            logger.start_stage()
            run_logger.info("Stage[pii_filter] start job_id=%s", job_id)
            filtered_text, screening_data = filter_pii_with_screening(diarized_text)
            filtered_lines = [filter_pii(line) for line in diarized_lines]
            is_screening = bool(screening_data["names"] or screening_data["phones"])
            screening_reason = "해당되는 내용 발견." if is_screening else "해당되는 내용 없음."
            screening = {"names": screening_data["names"], "phones": screening_data["phones"]}
            logger.end_stage("pii_filter_time_ms")
            run_logger.info(
                "Stage[pii_filter] done job_id=%s names=%s phones=%s",
                job_id,
                len(screening_data["names"]),
                len(screening_data["phones"]),
            )
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            # 7. Generate summaries
            current_stage = "summarization"
            logger.start_stage()
            run_logger.info("Stage[summarization] start job_id=%s", job_id)
            soap_text = generate_soap_summary(filtered_text, settings.chat_model, logger)
            title = generate_title(filtered_text, settings.chat_model, logger)
            simple_summary = generate_simple_summary(filtered_text, settings.chat_model, logger)
            logger.end_stage("summarization_time_ms")
            run_logger.info(
                "Stage[summarization] done job_id=%s title_len=%s simple_len=%s",
                job_id,
                len(title),
                len(simple_summary),
            )
            if await _check_timeout_and_abort(store, job_id, start_time, timeout_sec, logger):
                return

            # Parse SOAP into consultationSummary (S→symptomRecord, O→testResults, A→doctorNotes, P→prescriptionAndCare)
            consultation_summary = parse_soap_to_consultation_summary(soap_text, filtered_lines)

            # 8-1. 요약 채점 → hippo PATCH (stt-api가 만든 레코드에 요약 지표 추가)
            if eval_job_id and settings.enable_summary_evaluation:
                try:
                    from app.services.evaluation.summary_evaluator import evaluate_summary_result
                    from app.services.evaluation.hippo_client import patch_summary_evaluation

                    summarization_ms = getattr(logger.log.stages, "summarization_time_ms", 0)
                    transcript_for_eval = " ".join(
                        seg.content for seg in (consultation_summary.conversationContent or [])
                        if seg.content
                    ).strip()

                    patch_payload = evaluate_summary_result(
                        consultation_summary=consultation_summary.model_dump(),
                        transcript_text=transcript_for_eval,
                        audio_duration_sec=duration,
                        summarization_time_ms=summarization_ms,
                    )
                    await patch_summary_evaluation(eval_job_id, patch_payload)
                except Exception as eval_exc:
                    logging.getLogger(__name__).warning(
                        "요약 채점 실패 (파이프라인 계속): %s", eval_exc
                    )

            is_abusing_final = validation_abuse_reason is not None
            abusing_reason_final = validation_abuse_reason or ""

            logger.set_quality(
                is_abusing=is_abusing_final,
                abusing_reason=abusing_reason_final,
                speaker_count=len(unique_speakers),
                segment_count=len(diarized_lines),
            )

            # 8. Update job with results
            await store.update_job(job_id, {
                "status": "completed",
                "isGenerated": True,
                "isAbusing": is_abusing_final,
                "abusingReason": abusing_reason_final,
                "isScreening": is_screening,
                "screeningReason": screening_reason,
                "screening": screening,
                "duration": duration,
                "title": title,
                "simpleSummary": simple_summary,
                "consultationSummary": consultation_summary.model_dump(),
            })
            logger.complete("completed")
            run_logger.info("AI pipeline completed job_id=%s", job_id)
            await _persist_consultation_if_configured(store, job_id, logger, stored_audio_url=s3_audio_url)

    except Exception as e:
        traceback.print_exc()
        run_logger.exception("AI pipeline failed job_id=%s stage=%s", job_id, current_stage)

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

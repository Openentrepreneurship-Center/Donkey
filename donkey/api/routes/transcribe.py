"""Transcription API endpoints."""

import os
import tempfile
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from donkey.config import get_settings
from donkey.core.audio import ensure_wav_16k_mono, get_audio_duration
from donkey.core.pipeline import diarize_and_transcribe, process_full_pipeline
from donkey.core.soap import soap_summarize, SOAP_DISCLAIMER
from donkey.api.schemas import (
    SoapRequest,
    DiarizeResponse,
    DiarizeDataResponse,
    SoapResponse,
    SoapDataResponse,
    FullPipelineResponse,
    FullPipelineDataResponse,
    AsyncJobResponse,
    TranscriptionSegmentResponse,
)
from donkey.services import get_pipeline_manager, get_job_manager, JobStatus

router = APIRouter(prefix="/api/v1/transcribe", tags=["음성 변환"])

ALLOWED_EXTENSIONS = {".m4a", ".wav", ".mp3", ".mp4", ".aac"}


def validate_audio_file(file: UploadFile) -> None:
    """Validate uploaded audio file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )


async def save_upload_file(file: UploadFile) -> str:
    """Save uploaded file to temporary location."""
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".wav"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.close()
        return tmp.name
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise


def run_diarization_job(
    job_id: str,
    file_path: str,
    wav_path: str,
    language: str,
    stt_model: str,
    num_speakers: Optional[int],
    min_segment_duration: float,
) -> None:
    """Background task for diarization."""
    job_manager = get_job_manager()
    pipeline_manager = get_pipeline_manager()

    try:
        job_manager.set_processing(job_id, "Starting diarization...")

        def progress_callback(current: int, total: int, message: str) -> None:
            job_manager.update_progress(job_id, current, message)

        # Acquire lock for thread-safe diarization
        with pipeline_manager.diarization_lock:
            result = diarize_and_transcribe(
                file_path=wav_path,
                pipeline=pipeline_manager.pipeline,
                client=pipeline_manager.openai_client,
                language=language,
                model=stt_model,
                num_speakers=num_speakers,
                min_segment_duration=min_segment_duration,
                progress_callback=progress_callback,
            )

        # Convert result to response format
        response_data = {
            "transcript": result.transcript,
            "segments": [
                {
                    "speaker": seg.speaker,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                }
                for seg in result.segments
            ],
            "speaker_count": result.speaker_count,
            "duration_seconds": result.duration_seconds,
        }

        job_manager.set_completed(job_id, response_data)

    except Exception as e:
        job_manager.set_failed(job_id, str(e))

    finally:
        # Cleanup temp files
        if os.path.exists(file_path):
            os.unlink(file_path)
        if wav_path != file_path and os.path.exists(wav_path):
            os.unlink(wav_path)


def run_full_pipeline_job(
    job_id: str,
    file_path: str,
    wav_path: str,
    language: str,
    stt_model: str,
    chat_model: str,
    num_speakers: Optional[int],
    min_segment_duration: float,
) -> None:
    """Background task for full pipeline."""
    job_manager = get_job_manager()
    pipeline_manager = get_pipeline_manager()

    try:
        job_manager.set_processing(job_id, "Starting full pipeline...")

        def progress_callback(current: int, total: int, message: str) -> None:
            job_manager.update_progress(job_id, current, message)

        # Acquire lock for thread-safe diarization
        with pipeline_manager.diarization_lock:
            result = process_full_pipeline(
                file_path=wav_path,
                pipeline=pipeline_manager.pipeline,
                client=pipeline_manager.openai_client,
                language=language,
                stt_model=stt_model,
                chat_model=chat_model,
                num_speakers=num_speakers,
                min_segment_duration=min_segment_duration,
                progress_callback=progress_callback,
            )

        # Convert result to response format
        response_data = {
            "transcript": result.diarization.transcript,
            "segments": [
                {
                    "speaker": seg.speaker,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                }
                for seg in result.diarization.segments
            ],
            "speaker_count": result.diarization.speaker_count,
            "duration_seconds": result.diarization.duration_seconds,
            "soap_summary": result.soap_summary,
            "disclaimer": result.disclaimer,
        }

        job_manager.set_completed(job_id, response_data)

    except Exception as e:
        job_manager.set_failed(job_id, str(e))

    finally:
        # Cleanup temp files
        if os.path.exists(file_path):
            os.unlink(file_path)
        if wav_path != file_path and os.path.exists(wav_path):
            os.unlink(wav_path)


@router.post(
    "/diarize",
    response_model=DiarizeResponse | AsyncJobResponse,
    summary="화자 분리 및 텍스트 변환",
    responses={
        200: {"description": "동기 처리 결과 (짧은 파일)"},
        202: {"description": "비동기 작업 생성됨 (긴 파일)", "model": AsyncJobResponse},
    },
)
async def diarize(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="변환할 오디오 파일"),
    language: str = Form(default="ko", description="언어 코드 (ko, en 등)"),
    stt_model: str = Form(default="gpt-4o-mini-transcribe", description="음성인식 모델"),
    num_speakers: Optional[int] = Form(default=None, description="화자 수 (알고 있으면 지정)"),
    min_segment_duration: float = Form(default=0.6, description="최소 세그먼트 길이(초)"),
):
    """
    오디오 파일을 화자 분리하여 텍스트로 변환합니다.

    - **짧은 파일 (< 30초)**: 결과를 즉시 반환
    - **긴 파일 (≥ 30초)**: 비동기 작업 ID 반환, 폴링으로 결과 확인
    """
    validate_audio_file(file)

    pipeline_manager = get_pipeline_manager()
    if not pipeline_manager.is_ready:
        raise HTTPException(status_code=503, detail="Pipeline not ready. Please wait.")

    settings = get_settings()
    job_manager = get_job_manager()

    # Check concurrent job limit
    if job_manager.get_active_job_count() >= settings.max_concurrent_jobs:
        raise HTTPException(
            status_code=429,
            detail=f"Too many concurrent jobs. Max: {settings.max_concurrent_jobs}",
        )

    # Save uploaded file
    file_path = await save_upload_file(file)

    try:
        # Convert to WAV
        wav_path = ensure_wav_16k_mono(file_path)

        # Check duration for sync/async decision
        duration = get_audio_duration(wav_path)

        if duration < settings.async_threshold_seconds:
            # Synchronous processing for short files
            with pipeline_manager.diarization_lock:
                result = diarize_and_transcribe(
                    file_path=wav_path,
                    pipeline=pipeline_manager.pipeline,
                    client=pipeline_manager.openai_client,
                    language=language,
                    model=stt_model,
                    num_speakers=num_speakers,
                    min_segment_duration=min_segment_duration,
                )

            # Cleanup temp files
            if os.path.exists(file_path):
                os.unlink(file_path)
            if wav_path != file_path and os.path.exists(wav_path):
                os.unlink(wav_path)

            return DiarizeResponse(
                status="completed",
                data=DiarizeDataResponse(
                    transcript=result.transcript,
                    segments=[
                        TranscriptionSegmentResponse(
                            speaker=seg.speaker,
                            start=seg.start,
                            end=seg.end,
                            text=seg.text,
                        )
                        for seg in result.segments
                    ],
                    speaker_count=result.speaker_count,
                    duration_seconds=result.duration_seconds,
                ),
            )

        else:
            # Async processing for long files
            job = job_manager.create_job(metadata={"type": "diarize", "filename": file.filename})

            background_tasks.add_task(
                run_diarization_job,
                job.id,
                file_path,
                wav_path,
                language,
                stt_model,
                num_speakers,
                min_segment_duration,
            )

            return AsyncJobResponse(
                status="processing",
                job_id=job.id,
                poll_url=f"/api/v1/jobs/{job.id}/status",
            )

    except Exception as e:
        # Cleanup on error
        if os.path.exists(file_path):
            os.unlink(file_path)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/soap", response_model=SoapResponse, summary="SOAP 요약 생성")
async def soap(request: SoapRequest):
    """
    화자 분리된 텍스트를 SOAP 형식으로 요약합니다.

    LLM 텍스트 처리만 수행하므로 항상 동기 처리됩니다.
    """
    pipeline_manager = get_pipeline_manager()
    if not pipeline_manager.is_ready:
        raise HTTPException(status_code=503, detail="Pipeline not ready. Please wait.")

    try:
        soap_text = soap_summarize(
            diarized_text=request.diarized_text,
            client=pipeline_manager.openai_client,
            chat_model=request.chat_model,
        )

        return SoapResponse(
            status="completed",
            data=SoapDataResponse(
                soap_summary=soap_text,
                disclaimer=SOAP_DISCLAIMER,
            ),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/full-pipeline",
    response_model=AsyncJobResponse,
    status_code=202,
    summary="전체 파이프라인 실행",
)
async def full_pipeline(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="처리할 오디오 파일"),
    language: str = Form(default="ko", description="언어 코드 (ko, en 등)"),
    stt_model: str = Form(default="gpt-4o-mini-transcribe", description="음성인식 모델"),
    chat_model: str = Form(default="gpt-4o-mini", description="SOAP 요약용 채팅 모델"),
    num_speakers: Optional[int] = Form(default=None, description="화자 수 (알고 있으면 지정)"),
    min_segment_duration: float = Form(default=0.6, description="최소 세그먼트 길이(초)"),
):
    """
    전체 파이프라인을 실행합니다: 화자 분리 → 텍스트 변환 → SOAP 요약

    여러 처리 단계가 포함되므로 항상 비동기로 처리됩니다.
    """
    validate_audio_file(file)

    pipeline_manager = get_pipeline_manager()
    if not pipeline_manager.is_ready:
        raise HTTPException(status_code=503, detail="Pipeline not ready. Please wait.")

    settings = get_settings()
    job_manager = get_job_manager()

    # Check concurrent job limit
    if job_manager.get_active_job_count() >= settings.max_concurrent_jobs:
        raise HTTPException(
            status_code=429,
            detail=f"Too many concurrent jobs. Max: {settings.max_concurrent_jobs}",
        )

    # Save uploaded file
    file_path = await save_upload_file(file)

    try:
        # Convert to WAV
        wav_path = ensure_wav_16k_mono(file_path)

        # Create job and run in background
        job = job_manager.create_job(metadata={"type": "full-pipeline", "filename": file.filename})

        background_tasks.add_task(
            run_full_pipeline_job,
            job.id,
            file_path,
            wav_path,
            language,
            stt_model,
            chat_model,
            num_speakers,
            min_segment_duration,
        )

        return AsyncJobResponse(
            status="processing",
            job_id=job.id,
            poll_url=f"/api/v1/jobs/{job.id}/status",
        )

    except Exception as e:
        # Cleanup on error
        if os.path.exists(file_path):
            os.unlink(file_path)
        raise HTTPException(status_code=500, detail=str(e))

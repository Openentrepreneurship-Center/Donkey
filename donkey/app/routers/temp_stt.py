"""임시 STT 라우터 (나중에 제거 예정)

엔드포인트:
- POST /temp/stt   : STT 작업 생성 (Donkey STT API + 자유 형식 요약)
- GET  /temp/stt/{job_id} : 작업 결과 조회

동작은 /ai, /ai/{job_id}와 동일하나 STT 및 요약 방식이 다릅니다.
"""

import asyncio
import hashlib
import logging
import uuid
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import get_settings
from app.schemas.request import AIRequest
from app.schemas.response import AICreateResponse, AICreateBody
from app.schemas.error import ERROR_404, ERROR_500, ERROR_503, error_response
from app.store.redis import (
    get_job_store,
    get_idempotency_job_id,
    set_idempotency_mapping_nx,
)
from app.worker_temp import process_audio_job_temp

logger = logging.getLogger(__name__)


class TempSttResultBody(BaseModel):
    id: str
    title: str
    duration: float
    simpleSummary: str


class TempSttResponse(BaseModel):
    status: str
    statusCode: int
    body: TempSttResultBody | None = None
    message: str | None = None


def _run_worker_sync(job_id: str, file_url: str) -> None:
    """스레드에서 별도 이벤트 루프로 임시 STT 워커 실행."""
    asyncio.run(process_audio_job_temp(job_id, file_url))


async def _schedule_worker_with_limit(app, job_id: str, file_url: str) -> None:
    """동시 실행 수 제한(세마포어) 안에서 워커를 스레드에 맡기고 즉시 반환."""
    semaphore: asyncio.Semaphore = app.state.job_semaphore
    await semaphore.acquire()
    task = asyncio.create_task(asyncio.to_thread(_run_worker_sync, job_id, file_url))

    def _release(_: asyncio.Task) -> None:
        semaphore.release()

    task.add_done_callback(_release)


async def _enqueue_or_schedule_temp_stt(
    req: Request,
    background_tasks: BackgroundTasks,
    job_id: str,
    file_url: str,
) -> None:
    settings = get_settings()
    if settings.use_arq_queue:
        from app.arq_worker import enqueue_temp_stt_job

        pool = getattr(req.app.state, "arq_pool", None)
        if pool is None:
            logger.error("arq_pool missing; check API lifespan / USE_ARQ_QUEUE / deployment version")
            raise HTTPException(status_code=503, detail=error_response(*ERROR_503))
        await enqueue_temp_stt_job(pool, job_id, file_url)
    else:
        background_tasks.add_task(_schedule_worker_with_limit, req.app, job_id, file_url)


router = APIRouter(prefix="/temp/stt", tags=["임시 STT"])


@router.post(
    "",
    response_model=AICreateResponse,
    summary="임시 STT 작업 생성",
    description="Donkey STT API(자체 Whisper)를 이용한 전사 및 자유 형식 요약 작업을 생성합니다. (임시 엔드포인트)",
)
async def create_temp_stt_job(
    req: Request,
    request: AIRequest,
    background_tasks: BackgroundTasks,
):
    """
    오디오 URL을 받아 임시 STT 처리 작업을 생성합니다.

    GET /temp/stt/{id} 로 결과를 확인할 수 있는 작업 ID를 반환합니다.
    """
    file_url = str(request.file)
    parsed = urlparse(file_url)
    url_for_fingerprint = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    # 기존 /ai fingerprint와 충돌하지 않도록 "temp:" prefix 추가
    fingerprint = "temp:" + hashlib.sha256(url_for_fingerprint.encode()).hexdigest()
    settings = get_settings()
    window = settings.idempotency_window_seconds

    job_id = str(uuid.uuid4())
    set_ok = await set_idempotency_mapping_nx(fingerprint, job_id, window)
    if not set_ok:
        existing_job_id = await get_idempotency_job_id(fingerprint)
        if existing_job_id:
            logger.info(
                "Idempotency (temp/stt): duplicate request within window, returning existing job_id=%s",
                existing_job_id,
            )
            return AICreateResponse(
                status="ok",
                statusCode=200,
                body=AICreateBody(id=existing_job_id),
            )

    store = await get_job_store()

    await store.create_job(job_id, {
        "id": job_id,
        "status": "pending",
        "file_url": file_url,
        "isGenerated": False,
        "isAbusing": False,
        "abusingReason": "",
        "isScreening": False,
        "screeningReason": "해당되는 내용 없음.",
        "screening": {"names": [], "phones": []},
        "title": "",
        "duration": 0,
        "simpleSummary": "",
        "consultationSummary": None,
    })

    await _enqueue_or_schedule_temp_stt(req, background_tasks, job_id, file_url)

    return AICreateResponse(
        status="ok",
        statusCode=200,
        body=AICreateBody(id=job_id),
    )


@router.get(
    "/{job_id}",
    response_model=TempSttResponse,
    response_model_exclude_none=True,
    summary="임시 STT 작업 결과 조회",
    description="임시 STT 처리 작업의 결과를 조회합니다.",
)
async def get_temp_stt_result(
    job_id: str,
):
    """
    임시 STT 처리 작업의 결과를 조회합니다.

    처리 중이면 202, 완료되면 200과 함께 결과를 반환합니다.
    """
    job_id = job_id.strip().strip('"\'')
    store = await get_job_store()
    job = await store.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=error_response(*ERROR_404))

    status = job.get("status", "pending")

    if status == "pending" or status == "processing":
        payload = TempSttResponse(
            status="ok",
            statusCode=202,
            message="AI 실행 결과가 진행 중",
        ).model_dump(exclude_none=True)
        return JSONResponse(content=payload, status_code=202)
    elif status == "error":
        code, default_message = ERROR_500
        message = job.get("error") or default_message
        return JSONResponse(
            status_code=500,
            content=error_response(code, message),
        )
    else:  # completed
        result_body = TempSttResultBody(
            id=job_id,
            title=job.get("title", ""),
            duration=job.get("duration", 0),
            simpleSummary=job.get("simpleSummary", ""),
        )
        return TempSttResponse(
            status="ok",
            statusCode=200,
            body=result_body,
        )

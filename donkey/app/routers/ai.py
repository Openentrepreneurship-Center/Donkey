import asyncio
import hashlib
import logging
import uuid
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.dependencies import verify_api_key
from app.schemas.request import AIRequest
from app.schemas.response import (
    AICreateResponse,
    AICreateBody,
    AIResponse,
    AIResultBody,
    ConsultationSummary,
)
from app.schemas.error import ERROR_404, ERROR_500, error_response
from app.store.redis import (
    get_job_store,
    get_idempotency_job_id,
    set_idempotency_mapping_nx,
)
from app.worker import process_audio_job


def _run_worker_sync(job_id: str, file_url: str) -> None:
    """스레드에서 별도 이벤트 루프로 워커 실행 → 메인 루프가 조회 API 등 즉시 처리 가능."""
    asyncio.run(process_audio_job(job_id, file_url))


async def _schedule_worker_with_limit(app, job_id: str, file_url: str) -> None:
    """동시 실행 수 제한(세마포어) 안에서 워커를 스레드에 맡기고 즉시 반환. 완료 시 세마포어 해제."""
    semaphore: asyncio.Semaphore = app.state.job_semaphore
    await semaphore.acquire()
    task = asyncio.create_task(asyncio.to_thread(_run_worker_sync, job_id, file_url))

    def _release(_: asyncio.Task) -> None:
        semaphore.release()

    task.add_done_callback(_release)


router = APIRouter(prefix="/ai", tags=["AI 처리"])


@router.post(
    "",
    response_model=AICreateResponse,
    summary="AI 작업 생성",
    description="오디오 전사 및 SOAP 요약을 위한 새 AI 처리 작업을 생성합니다.",
)
async def create_ai_job(
    req: Request,
    request: AIRequest,
    background_tasks: BackgroundTasks,
    api_key_ctx: tuple[int, int] = Depends(verify_api_key),
):
    """
    오디오 전사 및 SOAP 요약을 위한 새 AI 처리 작업을 생성합니다.

    GET /ai/{id}로 상태를 확인할 수 있는 작업 ID를 반환합니다.
    """
    file_url = str(request.file)
    # 쿼리/프래그 제거해 같은 파일이면 같은 fingerprint (pre-signed URL 등 대응)
    parsed = urlparse(file_url)
    url_for_fingerprint = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    fingerprint = hashlib.sha256(url_for_fingerprint.encode()).hexdigest()
    settings = get_settings()
    window = settings.idempotency_window_seconds

    job_id = str(uuid.uuid4())
    set_ok = await set_idempotency_mapping_nx(fingerprint, job_id, window)
    if not set_ok:
        existing_job_id = await get_idempotency_job_id(fingerprint)
        if existing_job_id:
            logger.info(
                "Idempotency: duplicate request within window, returning existing job_id=%s",
                existing_job_id,
            )
            return AICreateResponse(
                status="ok",
                statusCode=200,
                body=AICreateBody(id=existing_job_id),
            )

    store = await get_job_store()
    client_id, project_id = api_key_ctx

    # DB 저장은 워커에서 수행(응답 지연 없음, 이벤트 루프 분리 이슈 없음)
    # Initialize job in Redis
    await store.create_job(job_id, {
        "id": job_id,
        "status": "pending",
        "client_id": client_id,
        "project_id": project_id,
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

    # Start background processing (스레드 풀에서 실행해 메인 루프 블로킹 방지 → 조회 API 즉시 202/200 응답)
    background_tasks.add_task(_schedule_worker_with_limit, req.app, job_id, file_url)

    return AICreateResponse(
        status="ok",
        statusCode=200,
        body=AICreateBody(id=job_id),
    )


@router.get(
    "/{job_id}",
    response_model=AIResponse,
    response_model_exclude_none=True,
    summary="AI 작업 결과 조회",
    description="AI 처리 작업의 결과를 조회합니다.",
)
async def get_ai_result(
    job_id: str,
    _api_key_ctx: tuple[int, int] = Depends(verify_api_key),
):
    """
    AI 처리 작업의 결과를 조회합니다.

    처리 중이면 202, 완료되면 200과 함께 결과를 반환합니다.
    """
    job_id = job_id.strip().strip('"\'')
    store = await get_job_store()
    job = await store.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=error_response(*ERROR_404))

    status = job.get("status", "pending")
    is_generated = job.get("isGenerated", False)

    # Build consultation summary if available
    consultation_summary = None
    if job.get("consultationSummary"):
        consultation_summary = ConsultationSummary(**job["consultationSummary"])

    result_body = AIResultBody(
        id=job_id,
        title=job.get("title", ""),
        duration=job.get("duration", 0),
        isGenerated=is_generated,
        isAbusing=job.get("isAbusing", False),
        abusingReason=job.get("abusingReason", ""),
        simpleSummary=job.get("simpleSummary", ""),
        consultationSummary=consultation_summary,
    )

    if status == "pending" or status == "processing":
        payload = AIResponse(
            status="ok",
            statusCode=202,
            body=None,
            message="AI 실행 결과가 진행 중",
        ).model_dump(exclude_none=True)
        return JSONResponse(content=payload, status_code=202)
    elif status == "error":
        # 500: 규격 오류 형식 { code, message }, job에 저장된 error 메시지 사용
        code, default_message = ERROR_500
        message = job.get("error") or default_message
        return JSONResponse(
            status_code=500,
            content=error_response(code, message),
        )
    else:  # completed
        return AIResponse(
            status="ok",
            statusCode=200,
            body=result_body,
        )

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.dependencies import verify_api_key
from app.schemas.request import AIRequest
from app.schemas.response import (
    AICreateResponse,
    AICreateBody,
    AIResponse,
    AIResultBody,
    ConsultationSummary,
    Screening,
)
from app.store.redis import get_job_store
from app.worker import process_audio_job


router = APIRouter(prefix="/ai", tags=["AI 처리"])


@router.post(
    "",
    response_model=AICreateResponse,
    summary="AI 작업 생성",
    description="오디오 전사 및 SOAP 요약을 위한 새 AI 처리 작업을 생성합니다.",
)
async def create_ai_job(
    request: AIRequest,
    background_tasks: BackgroundTasks,
    _api_key: str = Depends(verify_api_key),
):
    """
    오디오 전사 및 SOAP 요약을 위한 새 AI 처리 작업을 생성합니다.

    GET /ai/{id}로 상태를 확인할 수 있는 작업 ID를 반환합니다.
    """
    job_id = str(uuid.uuid4())
    store = await get_job_store()

    # Initialize job in Redis
    await store.create_job(job_id, {
        "id": job_id,
        "status": "pending",
        "file_url": str(request.file),
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

    # Start background processing
    background_tasks.add_task(process_audio_job, job_id, str(request.file))

    return AICreateResponse(
        status="ok",
        statusCode=200,
        body=AICreateBody(id=job_id),
    )


@router.get(
    "/{job_id}",
    response_model=AIResponse,
    summary="AI 작업 결과 조회",
    description="AI 처리 작업의 결과를 조회합니다.",
)
async def get_ai_result(
    job_id: str,
    _api_key: str = Depends(verify_api_key),
):
    """
    AI 처리 작업의 결과를 조회합니다.

    처리 중이면 202, 완료되면 200과 함께 결과를 반환합니다.
    """
    job_id = job_id.strip().strip('"\'')
    store = await get_job_store()
    job = await store.get_job(job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "message": "Job not found"},
        )

    status = job.get("status", "pending")
    is_generated = job.get("isGenerated", False)

    # Build consultation summary if available
    consultation_summary = None
    if job.get("consultationSummary"):
        consultation_summary = ConsultationSummary(**job["consultationSummary"])

    # Build screening (default when not yet set)
    screening_data = job.get("screening") or {"names": [], "phones": []}
    screening = Screening(**screening_data)

    result_body = AIResultBody(
        id=job_id,
        title=job.get("title", ""),
        duration=job.get("duration", 0),
        isGenerated=is_generated,
        isAbusing=job.get("isAbusing", False),
        abusingReason=job.get("abusingReason", ""),
        isScreening=job.get("isScreening", False),
        screeningReason=job.get("screeningReason", "해당되는 내용 없음."),
        screening=screening,
        simpleSummary=job.get("simpleSummary", ""),
        consultationSummary=consultation_summary,
    )

    if status == "pending" or status == "processing":
        return AIResponse(
            status="ok",
            statusCode=202,
            body=result_body,
        )
    elif status == "error":
        return AIResponse(
            status="error",
            statusCode=500,
            body=result_body,
        )
    else:  # completed
        return AIResponse(
            status="ok",
            statusCode=200,
            body=result_body,
        )

"""Job management endpoints."""

from fastapi import APIRouter, HTTPException

from donkey.api.schemas import JobStatusResponse, JobResultResponse
from donkey.services import get_job_manager, JobStatus

router = APIRouter(prefix="/api/v1/jobs", tags=["작업 관리"])


@router.get("/{job_id}/status", response_model=JobStatusResponse, summary="작업 상태 조회")
async def get_job_status(job_id: str):
    """
    비동기 작업의 상태와 진행률을 조회합니다.

    작업 완료 여부를 확인하려면 이 엔드포인트를 폴링하세요.
    """
    job_manager = get_job_manager()
    job = job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        current_step=job.current_step,
        error=job.error,
    )


@router.get("/{job_id}/result", response_model=JobResultResponse, summary="작업 결과 조회")
async def get_job_result(job_id: str):
    """
    완료된 작업의 결과를 조회합니다.

    - 작업을 찾을 수 없으면 404 반환
    - 작업이 아직 완료되지 않았으면 400 반환
    """
    job_manager = get_job_manager()
    job = job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job.status == JobStatus.PENDING:
        raise HTTPException(status_code=400, detail="Job is pending, not started yet")

    if job.status == JobStatus.PROCESSING:
        raise HTTPException(status_code=400, detail="Job is still processing")

    if job.status == JobStatus.FAILED:
        return JobResultResponse(
            job_id=job.id,
            status=job.status.value,
            data=None,
            error=job.error,
        )

    # Job is completed
    return JobResultResponse(
        job_id=job.id,
        status=job.status.value,
        data=job.result,
        error=None,
    )

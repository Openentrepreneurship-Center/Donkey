"""Health check endpoints."""

from fastapi import APIRouter

from donkey import __version__
from donkey.api.schemas import HealthResponse, ReadyResponse
from donkey.services import get_pipeline_manager

router = APIRouter(tags=["상태 확인"])


@router.get("/health", response_model=HealthResponse, summary="서버 상태 확인")
async def health_check() -> HealthResponse:
    """
    서버 기본 상태 확인.

    서버가 실행 중이면 OK를 반환합니다.
    """
    return HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyResponse, summary="준비 상태 확인")
async def ready_check() -> ReadyResponse:
    """
    파이프라인 준비 상태 확인.

    화자 분리 파이프라인이 완전히 로드되면 ready=true를 반환합니다.
    """
    manager = get_pipeline_manager()

    if manager.is_ready:
        return ReadyResponse(ready=True, message="Pipeline loaded and ready")
    else:
        return ReadyResponse(ready=False, message="Pipeline still loading...")

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

# app 하위 logger가 INFO 이상 출력되도록 (uvicorn 콘솔에 보이게)
_app_logger = logging.getLogger("app")
_app_logger.setLevel(logging.INFO)
if not _app_logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    _app_logger.addHandler(_h)
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.routers import ai
from app.schemas.error import (
    error_response,
    ERROR_400,
    ERROR_401,
    ERROR_404,
    ERROR_422,
    ERROR_429,
    ERROR_500,
)
from app.config import get_settings
from app.store.redis import close_all_redis_clients
from app.db import init_db, is_db_configured


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.job_semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
    if is_db_configured():
        try:
            await init_db()
        except Exception as e:
            _app_logger.warning("DB init (create tables) skipped: %s", e)
    yield
    try:
        await close_all_redis_clients()
    except Exception:
        pass


app = FastAPI(
    title="Donkey API",
    description="화자 분리 및 SOAP 요약 기능을 제공하는 의료 오디오 처리 API",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(ai.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422: Schema 검증 실패."""
    code, message = ERROR_422
    return JSONResponse(status_code=422, content=error_response(code, message))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTPException 시 규격 오류 본문 { code, message } 로 반환."""
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    status_to_error = {
        400: ERROR_400,
        401: ERROR_401,
        404: ERROR_404,
        429: ERROR_429,
    }
    code, message = status_to_error.get(
        exc.status_code, ("COMMON_500_000", str(exc.detail) if exc.detail else "Unknown error")
    )
    return JSONResponse(status_code=exc.status_code, content=error_response(code, message))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """500: 미처리 예외."""
    code, message = ERROR_500
    return JSONResponse(status_code=500, content=error_response(code, message))


@app.get("/health", summary="헬스 체크", description="서버 상태를 확인합니다.")
async def health_check():
    """서버 상태 확인 엔드포인트"""
    return {"status": "ok"}

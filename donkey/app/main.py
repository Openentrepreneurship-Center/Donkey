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
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.routers import ai
from app.store.redis import get_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Shutdown: close Redis connection
    try:
        client = await get_redis_client()
        await client.close()
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
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "statusCode": 422,
            "message": "Validation error",
            "details": exc.errors(),
        },
    )


@app.get("/health", summary="헬스 체크", description="서버 상태를 확인합니다.")
async def health_check():
    """서버 상태 확인 엔드포인트"""
    return {"status": "ok"}

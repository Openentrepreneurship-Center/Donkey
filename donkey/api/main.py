"""FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from donkey import __version__
from donkey.api.routes import health_router, transcribe_router, jobs_router
from donkey.services import get_pipeline_manager, get_job_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup: Initialize pipeline in background thread to not block
    print("🚀 Starting Donkey API server...")
    print("⏳ Loading pyannote pipeline (this may take a moment)...")

    # Initialize pipeline manager (loads the heavy model)
    loop = asyncio.get_event_loop()
    pipeline_manager = get_pipeline_manager()

    try:
        await loop.run_in_executor(None, pipeline_manager.initialize)
        print("✅ Pipeline loaded and ready!")
    except Exception as e:
        print(f"⚠️ Pipeline initialization failed: {e}")
        print("   Server will start but transcription endpoints won't work.")
        print("   Please check your HF_TOKEN and accept model licenses at:")
        print("   - https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("   - https://huggingface.co/pyannote/speaker-diarization-community-1")

    yield

    # Shutdown: Cleanup
    print("👋 Shutting down Donkey API server...")
    # Cleanup old jobs
    job_manager = get_job_manager()
    removed = job_manager.cleanup_old_jobs()
    if removed > 0:
        print(f"🧹 Cleaned up {removed} old jobs")


# Create FastAPI app
app = FastAPI(
    title="Donkey API",
    description="의료 음성 녹음을 화자 분리하여 텍스트로 변환하고 SOAP 형식으로 요약하는 API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(transcribe_router)
app.include_router(jobs_router)


def run_server() -> None:
    """Run the server using uvicorn (for CLI entry point)."""
    import uvicorn
    uvicorn.run(
        "donkey.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    run_server()

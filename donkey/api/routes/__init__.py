"""API routes."""

from .health import router as health_router
from .transcribe import router as transcribe_router
from .jobs import router as jobs_router

__all__ = ["health_router", "transcribe_router", "jobs_router"]

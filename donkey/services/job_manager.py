"""Job management for background tasks."""

import time
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from donkey.config import get_settings


class JobStatus(str, Enum):
    """Job status enum."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """Represents a background job."""
    id: str
    status: JobStatus
    created_at: float
    updated_at: float
    progress: int = 0  # 0-100
    current_step: str = ""
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for API response."""
        return {
            "id": self.id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": self.progress,
            "current_step": self.current_step,
            "error": self.error,
        }


class JobManager:
    """
    Manages background jobs with in-memory storage.

    Features:
    - UUID-based job IDs
    - Progress tracking
    - Automatic cleanup of old jobs (TTL-based)
    - Thread-safe operations
    """

    _instance: Optional["JobManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "JobManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._settings = get_settings()
        self._jobs: Dict[str, Job] = {}
        self._jobs_lock = threading.Lock()
        self._initialized = True

    def create_job(self, metadata: Optional[Dict[str, Any]] = None) -> Job:
        """Create a new job with pending status."""
        job_id = str(uuid.uuid4())
        now = time.time()

        job = Job(
            id=job_id,
            status=JobStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        with self._jobs_lock:
            self._jobs[job_id] = job

        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        with self._jobs_lock:
            return self._jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: Optional[JobStatus] = None,
        progress: Optional[int] = None,
        current_step: Optional[str] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> Optional[Job]:
        """Update job status and progress."""
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            job.updated_at = time.time()

            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if current_step is not None:
                job.current_step = current_step
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

            return job

    def set_processing(self, job_id: str, current_step: str = "") -> Optional[Job]:
        """Mark job as processing."""
        return self.update_job(
            job_id,
            status=JobStatus.PROCESSING,
            current_step=current_step,
        )

    def set_completed(self, job_id: str, result: Any) -> Optional[Job]:
        """Mark job as completed with result."""
        return self.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            current_step="Complete",
            result=result,
        )

    def set_failed(self, job_id: str, error: str) -> Optional[Job]:
        """Mark job as failed with error message."""
        return self.update_job(
            job_id,
            status=JobStatus.FAILED,
            error=error,
        )

    def update_progress(self, job_id: str, progress: int, current_step: str) -> Optional[Job]:
        """Update job progress."""
        return self.update_job(
            job_id,
            progress=progress,
            current_step=current_step,
        )

    def cleanup_old_jobs(self) -> int:
        """
        Remove jobs older than TTL.
        Returns the number of jobs removed.
        """
        now = time.time()
        ttl = self._settings.job_ttl_seconds
        removed = 0

        with self._jobs_lock:
            expired_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if (now - job.created_at) > ttl
            ]
            for job_id in expired_ids:
                del self._jobs[job_id]
                removed += 1

        return removed

    def get_active_job_count(self) -> int:
        """Get count of pending or processing jobs."""
        with self._jobs_lock:
            return sum(
                1
                for job in self._jobs.values()
                if job.status in (JobStatus.PENDING, JobStatus.PROCESSING)
            )


def get_job_manager() -> JobManager:
    """Get the singleton JobManager instance."""
    return JobManager()

from abc import ABC, abstractmethod
from typing import Any


class JobStore(ABC):
    @abstractmethod
    async def create_job(self, job_id: str, data: dict[str, Any]) -> None:
        """Create a new job with initial data."""
        pass

    @abstractmethod
    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Get job data by ID."""
        pass

    @abstractmethod
    async def update_job(self, job_id: str, data: dict[str, Any]) -> None:
        """Update job data."""
        pass

    @abstractmethod
    async def delete_job(self, job_id: str) -> None:
        """Delete a job."""
        pass

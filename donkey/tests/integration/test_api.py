"""AI API: Redis·워커 mock, 인증 bypass."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.store.base import JobStore
from typing import Any


class InMemoryJobStore(JobStore):
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    async def create_job(self, job_id: str, data: dict[str, Any]) -> None:
        self._jobs[job_id] = dict(data)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    async def update_job(self, job_id: str, data: dict[str, Any]) -> None:
        if job_id not in self._jobs:
            self._jobs[job_id] = {}
        self._jobs[job_id].update(data)

    async def delete_job(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)


@pytest.fixture
def memory_store():
    return InMemoryJobStore()


@pytest.fixture
def app(memory_store, monkeypatch, clean_settings_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("USE_ARQ_QUEUE", "false")
    with patch("app.db.is_db_configured", return_value=False), \
         patch("app.db.session.is_db_configured", return_value=False), \
         patch("app.store.redis.close_all_redis_clients", new_callable=AsyncMock), \
         patch("app.routers.ai.get_job_store", new_callable=AsyncMock, return_value=memory_store), \
         patch("app.routers.ai.set_idempotency_mapping_nx", new_callable=AsyncMock, return_value=True), \
         patch("app.routers.ai.get_idempotency_job_id", new_callable=AsyncMock, return_value=None), \
         patch("app.routers.ai.process_audio_job", new_callable=AsyncMock):
        from app.main import app
        from app.dependencies import verify_api_key

        app.state.job_semaphore = asyncio.Semaphore(5)

        async def _fake_api_key():
            return (1, 1)

        app.dependency_overrides[verify_api_key] = _fake_api_key
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCreateAIJob:
    @pytest.mark.asyncio
    async def test_create_job_returns_200(self, client):
        resp = await client.post(
            "/ai",
            json={"file": "https://example.com/audio.wav"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data["body"]

    @pytest.mark.asyncio
    async def test_create_job_invalid_url_returns_422(self, client):
        resp = await client.post(
            "/ai",
            json={"file": "not-a-valid-url"},
        )
        assert resp.status_code == 422


class TestGetAIResult:
    @pytest.mark.asyncio
    async def test_pending_job_returns_202(self, client, memory_store):
        await memory_store.create_job("test-job-1", {
            "id": "test-job-1",
            "status": "pending",
            "isGenerated": False,
        })
        resp = await client.get("/ai/test-job-1")
        assert resp.status_code == 202

    @pytest.mark.asyncio
    async def test_completed_job_returns_200(self, client, memory_store):
        await memory_store.create_job("test-job-2", {
            "id": "test-job-2",
            "status": "completed",
            "isGenerated": True,
            "isAbusing": False,
            "abusingReason": "",
            "title": "테스트",
            "duration": 60.0,
            "simpleSummary": "요약",
            "consultationSummary": {
                "doctorNotes": ["소견"],
                "testResults": [],
                "symptomRecord": [],
                "prescriptionAndCare": [],
                "conversationContent": [],
            },
        })
        resp = await client.get("/ai/test-job-2")
        assert resp.status_code == 200
        body = resp.json()["body"]
        assert body["title"] == "테스트"

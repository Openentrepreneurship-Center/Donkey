"""Redis + ARQ 워커가 있는 환경에서 POST /ai → 워커 처리 → GET 완료 스모크."""

from __future__ import annotations

import asyncio
import threading
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import redis as redis_sync
from arq.worker import create_worker
from starlette.testclient import TestClient


def _ping_redis_sync(url: str) -> bool:
    r = redis_sync.Redis.from_url(url, decode_responses=True)
    try:
        return bool(r.ping())
    except Exception:
        return False
    finally:
        r.close()


def test_post_ai_arq_worker_marks_job_completed(monkeypatch, clean_settings_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("USE_ARQ_QUEUE", "true")

    from app.config import get_settings

    redis_url = get_settings().redis_url
    if not _ping_redis_sync(redis_url):
        pytest.skip("Redis unavailable (need running Redis for ARQ e2e)")

    file_url = f"https://example.com/smoke-arq-{uuid.uuid4()}.wav"

    def _run_burst_worker_sync(settings_cls: type) -> None:
        async def _burst() -> None:
            worker = create_worker(
                settings_cls,
                burst=True,
                max_burst_jobs=3,
                handle_signals=False,
            )
            await worker.async_run()
            await worker.close()

        asyncio.run(_burst())

    async def fake_pipeline(job_id: str, file_url_: str) -> None:
        from app.store.redis import get_job_store

        store = await get_job_store()
        await store.update_job(
            job_id,
            {
                "status": "completed",
                "isGenerated": True,
                "isAbusing": False,
                "abusingReason": "",
                "title": "smoke",
                "duration": 1.0,
                "simpleSummary": "ok",
                "consultationSummary": {
                    "doctorNotes": [],
                    "testResults": [],
                    "symptomRecord": [],
                    "prescriptionAndCare": [],
                    "conversationContent": [],
                },
            },
        )

    with patch("app.db.is_db_configured", return_value=False), \
         patch("app.db.session.is_db_configured", return_value=False), \
         patch("app.store.redis.close_all_redis_clients", new_callable=AsyncMock), \
         patch("app.arq_worker.process_audio_job", side_effect=fake_pipeline):
        from app.arq_worker import WorkerSettings
        from app.dependencies import verify_api_key
        from app.main import app

        async def fake_key() -> tuple[int, int]:
            return (1, 1)

        app.dependency_overrides[verify_api_key] = fake_key
        try:
            with TestClient(app) as client:
                r = client.post(
                    "/ai",
                    json={"file": file_url},
                    headers={"X-Api-Key": "dummy"},
                )
            assert r.status_code == 200, r.text
            job_id = r.json()["body"]["id"]
        finally:
            app.dependency_overrides.clear()

        th = threading.Thread(
            target=lambda: _run_burst_worker_sync(WorkerSettings),
            daemon=True,
        )
        th.start()
        th.join(timeout=60)
        assert not th.is_alive(), "ARQ worker did not finish burst in time"

    from app.dependencies import verify_api_key
    from app.main import app

    async def fake_key_get() -> tuple[int, int]:
        return (1, 1)

    app.dependency_overrides[verify_api_key] = fake_key_get
    try:
        with TestClient(app) as client:
            r2 = client.get(f"/ai/{job_id}", headers={"X-Api-Key": "dummy"})
    finally:
        app.dependency_overrides.clear()

    assert r2.status_code == 200, r2.text
    assert r2.json()["body"]["title"] == "smoke"

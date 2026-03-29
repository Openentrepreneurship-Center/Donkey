"""헬스 엔드포인트 (ASGI)."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_ok(monkeypatch, clean_settings_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("USE_ARQ_QUEUE", "false")
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

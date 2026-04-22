"""히포 상담 오디오 조회 클라이언트."""

from __future__ import annotations

import base64

import pytest

from app.config import get_settings


@pytest.mark.asyncio
async def test_fetch_consultation_audio_ok(monkeypatch, clean_settings_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("HIPPO_CONSULTATION_API_BASE_URL", "https://hippo.example")
    monkeypatch.setenv("HIPPO_CONSULTATION_API_KEY", "secret-key")
    get_settings.cache_clear()

    raw = b"hello-audio"
    body = {"data": base64.b64encode(raw).decode("ascii"), "contentType": "audio/mpeg"}

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str, headers: dict | None = None):
            assert url == "https://hippo.example/consultation/uid-1/stt/audio-url"
            assert headers is not None and headers.get("x-api-key") == "secret-key"
            return FakeResp()

    import app.services.hippo_consultation_audio as hippo_mod

    monkeypatch.setattr(hippo_mod.httpx, "AsyncClient", lambda *a, **kw: FakeClient())

    from app.services.hippo_consultation_audio import fetch_consultation_audio

    result = await fetch_consultation_audio("uid-1")
    assert result.raw_bytes == raw
    assert result.content_type == "audio/mpeg"


def test_suffix_for_audio_content_type():
    from app.services.hippo_consultation_audio import suffix_for_audio_content_type

    assert suffix_for_audio_content_type("audio/mp4") == ".m4a"
    assert suffix_for_audio_content_type("audio/mpeg") in (".mp3", ".mpga")

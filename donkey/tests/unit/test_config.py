"""config: 타임아웃 계산, STT URL 별칭."""

import pytest

from app.config import Settings, get_processing_timeout_seconds


@pytest.fixture
def clean_env(monkeypatch, clean_settings_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    yield


class TestGetProcessingTimeout:
    def test_short_audio_90s(self):
        assert get_processing_timeout_seconds(60) == 90
        assert get_processing_timeout_seconds(300) == 90

    def test_medium_audio_120s(self):
        assert get_processing_timeout_seconds(301) == 120
        assert get_processing_timeout_seconds(600) == 120

    def test_long_audio_180s(self):
        assert get_processing_timeout_seconds(601) == 180
        assert get_processing_timeout_seconds(899) == 180

    def test_very_long_audio_240s(self):
        assert get_processing_timeout_seconds(900) == 240
        assert get_processing_timeout_seconds(3600) == 240


class TestSettings:
    def test_donkey_stt_base_url_alias(self, monkeypatch, clean_settings_cache):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.delenv("DONKEY_STT_API_URL", raising=False)
        monkeypatch.setenv("DONKEY_STT_BASE_URL", "http://stt.example.test")
        s = Settings()
        assert s.donkey_stt_api_url == "http://stt.example.test"

    def test_stt_backend_from_env(self, monkeypatch, clean_settings_cache):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("STT_BACKEND", "clova")
        s = Settings()
        assert s.stt_backend == "clova"

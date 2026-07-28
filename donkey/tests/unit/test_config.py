"""config: 타임아웃 계산, STT URL 별칭."""

import pytest

from app.config import Settings, get_processing_timeout_seconds


@pytest.fixture
def clean_env(monkeypatch, clean_settings_cache):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    yield


class TestGetProcessingTimeout:
    def test_short_audio_120s(self):
        assert get_processing_timeout_seconds(60) == 120
        assert get_processing_timeout_seconds(300) == 120

    def test_medium_audio_150s(self):
        assert get_processing_timeout_seconds(301) == 150
        assert get_processing_timeout_seconds(600) == 150

    def test_long_audio_210s(self):
        assert get_processing_timeout_seconds(601) == 210
        assert get_processing_timeout_seconds(899) == 210

    def test_very_long_audio_300s(self):
        assert get_processing_timeout_seconds(900) == 300
        assert get_processing_timeout_seconds(3600) == 300


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

    def test_arq_job_timeout_default_900(self, monkeypatch, clean_settings_cache):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.delenv("ARQ_JOB_TIMEOUT_SECONDS", raising=False)
        s = Settings()
        assert s.arq_job_timeout_seconds == 900

    def test_arq_job_timeout_from_env(self, monkeypatch, clean_settings_cache):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("ARQ_JOB_TIMEOUT_SECONDS", "1200")
        s = Settings()
        assert s.arq_job_timeout_seconds == 1200

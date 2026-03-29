"""
pytest 공통: 외부 유료 API·Redis 실연결 없이 단위/통합 테스트.

OPENAI_API_KEY 등은 더미 값으로 두며, LLM/STT 호출은 mock 한다.
"""

import pytest

from app.config import get_settings


@pytest.fixture
def clean_settings_cache():
    """Settings 싱글톤 캐시 초기화."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

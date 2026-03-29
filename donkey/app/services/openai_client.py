"""스레드별 OpenAI 클라이언트 (워커 스레드에서 httpx 기반 클라이언트 공유 방지)."""

import threading

from openai import OpenAI

from app.config import get_settings

_tls = threading.local()


def get_openai_client() -> OpenAI:
    client = getattr(_tls, "openai_client", None)
    if client is None:
        _tls.openai_client = OpenAI(api_key=get_settings().openai_api_key)
        client = _tls.openai_client
    return client

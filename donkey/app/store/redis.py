import asyncio
import json
from typing import Any

import redis.asyncio as redis

from app.store.base import JobStore
from app.config import get_settings


class RedisJobStore(JobStore):
    def __init__(self, redis_client: redis.Redis, ttl: int = 86400):
        self._redis = redis_client
        self._ttl = ttl
        self._prefix = "donkey:job:"

    def _key(self, job_id: str) -> str:
        return f"{self._prefix}{job_id}"

    async def create_job(self, job_id: str, data: dict[str, Any]) -> None:
        key = self._key(job_id)
        await self._redis.set(key, json.dumps(data), ex=self._ttl)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        key = self._key(job_id)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def update_job(self, job_id: str, data: dict[str, Any]) -> None:
        key = self._key(job_id)
        existing = await self.get_job(job_id)
        if existing is None:
            existing = {}
        existing.update(data)
        await self._redis.set(key, json.dumps(existing), ex=self._ttl)

    async def delete_job(self, job_id: str) -> None:
        key = self._key(job_id)
        await self._redis.delete(key)


# 루프별 클라이언트/스토어 (워커가 별도 스레드의 이벤트 루프에서 돌 때 각자 연결 사용)
_redis_by_loop: dict[int, redis.Redis] = {}
_job_store_by_loop: dict[int, RedisJobStore] = {}


async def get_redis_client() -> redis.Redis:
    loop = asyncio.get_running_loop()
    key = id(loop)
    if key not in _redis_by_loop:
        settings = get_settings()
        _redis_by_loop[key] = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_by_loop[key]


async def get_job_store() -> RedisJobStore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    if key not in _job_store_by_loop:
        client = await get_redis_client()
        settings = get_settings()
        _job_store_by_loop[key] = RedisJobStore(client, ttl=settings.job_ttl)
    return _job_store_by_loop[key]


async def close_all_redis_clients() -> None:
    """종료 시 루프별 Redis 연결 모두 닫기."""
    for key, client in list(_redis_by_loop.items()):
        try:
            await client.close()
        except Exception:
            pass
        _redis_by_loop.pop(key, None)


_IDEMPOTENCY_PREFIX = "donkey:idempotency:"


async def get_idempotency_job_id(fingerprint: str) -> str | None:
    """같은 요청( fingerprint )이 최근에 처리된 경우 기존 job_id 반환."""
    client = await get_redis_client()
    key = f"{_IDEMPOTENCY_PREFIX}{fingerprint}"
    return await client.get(key)


async def set_idempotency_mapping_nx(
    fingerprint: str, job_id: str, ttl_seconds: int
) -> bool:
    """요청 fingerprint → job_id 매핑 저장 (키가 없을 때만). 있으면 덮지 않음.
    TTL은 ttl_seconds 초로 확실히 적용 (EXPIRE 별도 호출).
    Returns True if we set the key, False if key already existed (중복 요청).
    """
    client = await get_redis_client()
    key = f"{_IDEMPOTENCY_PREFIX}{fingerprint}"
    set_ok = await client.set(key, job_id, nx=True)
    if set_ok:
        await client.expire(key, ttl_seconds)
    return bool(set_ok)

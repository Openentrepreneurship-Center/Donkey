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


_redis_client: redis.Redis | None = None
_job_store: RedisJobStore | None = None


async def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def get_job_store() -> RedisJobStore:
    global _job_store
    if _job_store is None:
        client = await get_redis_client()
        settings = get_settings()
        _job_store = RedisJobStore(client, ttl=settings.job_ttl)
    return _job_store


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

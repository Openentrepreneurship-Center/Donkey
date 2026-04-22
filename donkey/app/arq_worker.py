"""ARQ 작업 큐: API는 job을 enqueue하고, 별도 워커 프로세스가 전사 파이프라인을 실행합니다.

로컬에서 API만 띄우고 in-process 처리를 쓰려면 ``USE_ARQ_QUEUE=false``.

워커 실행: ``uv run arq app.arq_worker.WorkerSettings``
"""

from __future__ import annotations

import logging
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings
from app.store.redis import close_all_redis_clients
from app.worker import process_audio_job
from app.worker_temp import process_audio_job_temp

logger = logging.getLogger(__name__)


def _configure_arq_process_logging() -> None:
    """API(uvicorn)와 별도 프로세스인 ARQ 워커에서도 app.* INFO가 보이도록 설정."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s"),
        )
        root.addHandler(handler)
    root.setLevel(logging.INFO)


AI_JOB_FN = "process_ai_job_task"
TEMP_STT_JOB_FN = "process_temp_stt_job_task"


async def process_ai_job_task(ctx: dict[str, Any], job_id: str, file_url: str) -> None:
    await process_audio_job(job_id, file_url=file_url)


async def process_ai_job_from_file_id_task(ctx: dict[str, Any], job_id: str, file_id: str) -> None:
    await process_audio_job(job_id, file_id=file_id)


async def process_temp_stt_job_task(ctx: dict[str, Any], job_id: str, file_url: str) -> None:
    await process_audio_job_temp(job_id, file_url)


async def arq_on_startup(ctx: dict[str, Any]) -> None:
    _configure_arq_process_logging()
    logger.info(
        "ARQ worker startup (max concurrent jobs=%s)",
        get_settings().max_concurrent_jobs,
    )


async def arq_on_shutdown(ctx: dict[str, Any]) -> None:
    await close_all_redis_clients()


def redis_settings_for_arq() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def create_arq_pool() -> ArqRedis:
    return await create_pool(redis_settings_for_arq())


async def enqueue_ai_job(pool: ArqRedis, job_id: str, file_url: str) -> None:
    job = await pool.enqueue_job(AI_JOB_FN, job_id, file_url, _job_id=job_id)
    if job is None:
        logger.warning("ARQ enqueue skipped (duplicate job_id?): %s", job_id)


AI_JOB_FROM_FILE_ID_FN = "process_ai_job_from_file_id_task"


async def enqueue_ai_job_from_file_id(pool: ArqRedis, job_id: str, file_id: str) -> None:
    job = await pool.enqueue_job(
        AI_JOB_FROM_FILE_ID_FN,
        job_id,
        file_id,
        _job_id=job_id,
    )
    if job is None:
        logger.warning("ARQ enqueue skipped (duplicate job_id?): %s", job_id)


async def enqueue_temp_stt_job(pool: ArqRedis, job_id: str, file_url: str) -> None:
    job = await pool.enqueue_job(TEMP_STT_JOB_FN, job_id, file_url, _job_id=job_id)
    if job is None:
        logger.warning("ARQ enqueue skipped (duplicate job_id?): %s", job_id)


_cfg = get_settings()


class WorkerSettings:
    functions = [process_ai_job_task, process_ai_job_from_file_id_task, process_temp_stt_job_task]
    on_startup = arq_on_startup
    on_shutdown = arq_on_shutdown
    redis_settings = RedisSettings.from_dsn(_cfg.redis_url)
    max_jobs = _cfg.max_concurrent_jobs
    job_timeout = _cfg.arq_job_timeout_seconds  # 15분 기본 (config)

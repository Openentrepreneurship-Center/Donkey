"""hippo(채점 저장 서비스)에 요약 채점 결과를 PATCH하는 HTTP 클라이언트.

stt-api가 POST로 만든 레코드를, Donkey-백엔드가 PATCH로 요약 지표를 추가한다.

흐름:
1. stt-api가 전사 시 hippo에 POST /evaluations (STT 지표만)
2. stt-api 응답 헤더 X-Evaluation-Job-Id 로 job_id 전달
3. Donkey-백엔드가 요약 완료 후 job_id로 hippo 레코드 조회
4. PATCH /evaluations/:id 로 요약 지표 추가
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def patch_summary_evaluation(
    evaluation_job_id: str,
    patch_payload: dict,
) -> None:
    """hippo의 기존 레코드에 요약 채점 결과를 PATCH.

    실패해도 예외를 발생시키지 않는다 (요약 파이프라인에 영향 없음).
    """
    settings = get_settings()
    base_url = (settings.evaluation_storage_url or "").rstrip("/")
    api_key = settings.evaluation_storage_api_key or ""

    if not base_url or not api_key:
        logger.debug("hippo 설정 없음 — 요약 채점 PATCH 생략")
        return

    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(10.0)

    try:
        # 1. job_id로 hippo 레코드 조회
        record_id = await _find_record_id(base_url, headers, timeout, evaluation_job_id)
        if record_id is None:
            logger.warning(
                "hippo에서 레코드 못 찾음 (job_id=%s) — 요약 채점 PATCH 생략",
                evaluation_job_id,
            )
            return

        # 2. PATCH
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.patch(
                f"{base_url}/evaluations/{record_id}",
                headers=headers,
                json=patch_payload,
            )

        if 200 <= resp.status_code < 300:
            logger.info(
                "요약 채점 PATCH 성공: job_id=%s record_id=%s",
                evaluation_job_id,
                record_id,
            )
        else:
            logger.warning(
                "요약 채점 PATCH 실패: job_id=%s status=%d body=%s",
                evaluation_job_id,
                resp.status_code,
                resp.text[:200],
            )

    except Exception as exc:
        logger.error(
            "요약 채점 PATCH 오류: job_id=%s err=%s",
            evaluation_job_id,
            exc,
        )


async def _find_record_id(
    base_url: str,
    headers: dict,
    timeout: httpx.Timeout,
    job_id: str,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> int | None:
    """job_id로 hippo 레코드의 PK(id)를 조회. stt-api BackgroundTask 타이밍에 따라 재시도."""
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    f"{base_url}/evaluations",
                    headers=headers,
                    params={"job_id": job_id, "size": 1},
                )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    return items[0]["id"]
        except Exception as exc:
            logger.debug("hippo 조회 시도 %d 실패: %s", attempt + 1, exc)

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)

    return None

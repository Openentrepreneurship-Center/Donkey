"""Consultation / log / summary CRUD. DATABASE_URL 없으면 호출하지 않음."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Consultation, ConsultationLog, ConsultationSummary


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def create_consultation(session: AsyncSession, job_id: str, file_url: str) -> int:
    """consultation 1건 생성. 반환: consultation.id."""
    c = Consultation(
        job_id=job_id,
        file_url=file_url,
        status="pending",
    )
    session.add(c)
    await session.flush()
    return c.id


async def update_consultation_status(session: AsyncSession, consultation_id: int, status: str) -> None:
    now = datetime.now(timezone.utc)
    await session.execute(
        update(Consultation).where(Consultation.id == consultation_id).values(status=status, updated_at=now)
    )


async def get_consultation_id_by_job_id(session: AsyncSession, job_id: str) -> int | None:
    r = await session.execute(select(Consultation.id).where(Consultation.job_id == job_id))
    row = r.scalar_one_or_none()
    return int(row) if row is not None else None


async def create_consultation_log(
    session: AsyncSession,
    consultation_id: int,
    request_timestamp: datetime,
) -> None:
    log = ConsultationLog(
        consultation_id=consultation_id,
        request_timestamp=request_timestamp,
    )
    session.add(log)
    await session.flush()


async def update_consultation_log(
    session: AsyncSession,
    consultation_id: int,
    *,
    completed_at: datetime | None = None,
    processing_time_ms: int | None = None,
    audio_duration_sec: float | None = None,
    stages: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    model_usage: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    values: dict[str, Any] = {}
    if completed_at is not None:
        values["completed_at"] = completed_at
    if processing_time_ms is not None:
        values["processing_time_ms"] = processing_time_ms
    if audio_duration_sec is not None:
        values["audio_duration_sec"] = audio_duration_sec
    if stages is not None:
        values["stages"] = stages
    if quality is not None:
        values["quality"] = quality
    if model_usage is not None:
        values["model_usage"] = model_usage
    if error is not None:
        values["error"] = error
    if not values:
        return
    await session.execute(
        update(ConsultationLog).where(ConsultationLog.consultation_id == consultation_id).values(**values)
    )


async def create_consultation_summary(session: AsyncSession, consultation_id: int) -> None:
    summary = ConsultationSummary(consultation_id=consultation_id)
    session.add(summary)
    await session.flush()


async def update_consultation_summary(
    session: AsyncSession,
    consultation_id: int,
    *,
    title: str | None = None,
    simple_summary: str | None = None,
    doctor_notes: list | None = None,
    test_results: list | None = None,
    symptom_record: list | None = None,
    prescription_and_care: list | None = None,
    conversation_content: list | None = None,
) -> None:
    values: dict[str, Any] = {}
    if title is not None:
        values["title"] = title
    if simple_summary is not None:
        values["simple_summary"] = simple_summary
    if doctor_notes is not None:
        values["doctor_notes"] = doctor_notes
    if test_results is not None:
        values["test_results"] = test_results
    if symptom_record is not None:
        values["symptom_record"] = symptom_record
    if prescription_and_care is not None:
        values["prescription_and_care"] = prescription_and_care
    if conversation_content is not None:
        values["conversation_content"] = conversation_content
    if not values:
        return
    await session.execute(
        update(ConsultationSummary).where(ConsultationSummary.consultation_id == consultation_id).values(**values)
    )


def _job_log_to_log_update(job_log_dict: dict[str, Any]) -> dict[str, Any]:
    """JobLogger.log.to_dict() 결과에서 consultation_log 업데이트용 값 추출."""
    completed_at = _parse_iso(job_log_dict.get("completed_at"))
    processing_time_ms = job_log_dict.get("processing_time_ms")
    audio_duration = job_log_dict.get("audio_duration")
    stages = job_log_dict.get("stages")
    quality = job_log_dict.get("quality")
    model_usage = job_log_dict.get("model_usage")
    error = job_log_dict.get("error")
    return {
        "completed_at": completed_at,
        "processing_time_ms": processing_time_ms if processing_time_ms is not None else None,
        "audio_duration_sec": float(audio_duration) if audio_duration is not None else None,
        "stages": stages,
        "quality": quality,
        "model_usage": model_usage,
        "error": error,
    }


def _job_to_summary_update(job: dict[str, Any]) -> dict[str, Any]:
    """Redis job dict에서 consultation_summary 업데이트용 값 추출."""
    out = {
        "title": job.get("title") or None,
        "simple_summary": job.get("simpleSummary") or None,
    }
    cs = job.get("consultationSummary")
    if not cs:
        return out
    out["doctor_notes"] = cs.get("doctorNotes")
    out["test_results"] = cs.get("testResults")
    out["symptom_record"] = cs.get("symptomRecord")
    out["prescription_and_care"] = cs.get("prescriptionAndCare")
    out["conversation_content"] = cs.get("conversationContent")
    return out


async def persist_consultation_from_job(
    session: AsyncSession,
    job_id: str,
    job: dict[str, Any],
    job_log_dict: dict[str, Any],
) -> None:
    """
    Redis job + JobLog dict 기준으로 consultation / log / summary 테이블 갱신.
    consultation_id가 없으면(해당 job_id로 생성된 적 없으면) no-op.
    """
    consultation_id = await get_consultation_id_by_job_id(session, job_id)
    if consultation_id is None:
        return
    status = job.get("status", "pending")
    await update_consultation_status(session, consultation_id, status)
    log_vals = _job_log_to_log_update(job_log_dict)
    await update_consultation_log(session, consultation_id, **log_vals)
    if status == "completed" and job.get("consultationSummary"):
        summary_vals = _job_to_summary_update(job)
        await update_consultation_summary(session, consultation_id, **summary_vals)

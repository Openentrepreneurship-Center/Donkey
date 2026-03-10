"""Request / log / summary CRUD + admin queries. DATABASE_URL 없으면 호출하지 않음."""

from datetime import date, datetime, timezone, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdminUser,
    ApiKey,
    Client,
    Inquiry,
    InquiryReply,
    Project,
    Request,
    RequestLog,
    RequestSummary,
)

KST = timezone(timedelta(hours=9))

# job에 client_id, project_id 없을 때 사용할 기본값 (마이그레이션/레거시 호환)
DEFAULT_CLIENT_ID = 1
DEFAULT_PROJECT_ID = 1


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def create_request(
    session: AsyncSession,
    job_id: str,
    file_url: str,
    client_id: int,
    project_id: int,
) -> int:
    """request 1건 생성. 반환: request.id."""
    r = Request(
        job_id=job_id,
        file_url=file_url,
        status="pending",
        client_id=client_id,
        project_id=project_id,
    )
    session.add(r)
    await session.flush()
    return r.id


async def update_request_status(session: AsyncSession, request_id: int, status: str) -> None:
    now = datetime.now(KST)
    await session.execute(
        update(Request).where(Request.id == request_id).values(status=status, updated_at=now)
    )


async def update_request_stored_audio_url(
    session: AsyncSession, job_id: str, stored_audio_url: str
) -> None:
    """S3에 저장한 오디오 파일 URL을 request에 반영."""
    request_id = await get_request_id_by_job_id(session, job_id)
    if request_id is None:
        return
    now = datetime.now(KST)
    await session.execute(
        update(Request)
        .where(Request.id == request_id)
        .values(stored_audio_url=stored_audio_url, updated_at=now)
    )


async def get_request_id_by_job_id(session: AsyncSession, job_id: str) -> int | None:
    r = await session.execute(select(Request.id).where(Request.job_id == job_id))
    row = r.scalar_one_or_none()
    return int(row) if row is not None else None


async def create_request_log(
    session: AsyncSession,
    request_id: int,
    request_timestamp: datetime,
) -> None:
    log = RequestLog(
        request_id=request_id,
        request_timestamp=request_timestamp,
    )
    session.add(log)
    await session.flush()


async def update_request_log(
    session: AsyncSession,
    request_id: int,
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
        update(RequestLog).where(RequestLog.request_id == request_id).values(**values)
    )


async def create_request_summary(session: AsyncSession, request_id: int) -> None:
    summary = RequestSummary(request_id=request_id)
    session.add(summary)
    await session.flush()


async def update_request_summary(
    session: AsyncSession,
    request_id: int,
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
        update(RequestSummary).where(RequestSummary.request_id == request_id).values(**values)
    )


def _job_log_to_log_update(job_log_dict: dict[str, Any]) -> dict[str, Any]:
    """JobLogger.log.to_dict() 결과에서 request_log 업데이트용 값 추출."""
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
    """Redis job dict에서 request_summary 업데이트용 값 추출."""
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


async def persist_request_from_job(
    session: AsyncSession,
    job_id: str,
    job: dict[str, Any],
    job_log_dict: dict[str, Any],
    *,
    client_id: int | None = None,
    project_id: int | None = None,
    stored_audio_url: str | None = None,
) -> None:
    """
    Redis job + JobLog dict 기준으로 request / log / summary 저장.
    request가 없으면 생성 후 데이터 채움, 있으면 갱신만.
    client_id, project_id는 job에서 추출; 없으면 기본값(1,1) 사용.
    """
    cid = client_id if client_id is not None else job.get("client_id", DEFAULT_CLIENT_ID)
    pid = project_id if project_id is not None else job.get("project_id", DEFAULT_PROJECT_ID)

    request_id = await get_request_id_by_job_id(session, job_id)
    file_url = job.get("file_url", "")

    if request_id is None:
        request_id = await create_request(session, job_id, file_url, cid, pid)
        await create_request_log(
            session, request_id, _parse_iso(job_log_dict.get("request_timestamp")) or datetime.now(KST),
        )
        await create_request_summary(session, request_id)

    status = job.get("status", "pending")
    await update_request_status(session, request_id, status)
    log_vals = _job_log_to_log_update(job_log_dict)
    await update_request_log(session, request_id, **log_vals)
    if status == "completed" and job.get("consultationSummary"):
        summary_vals = _job_to_summary_update(job)
        await update_request_summary(session, request_id, **summary_vals)
    if stored_audio_url:
        now = datetime.now(KST)
        await session.execute(
            update(Request)
            .where(Request.id == request_id)
            .values(stored_audio_url=stored_audio_url, updated_at=now)
        )


# ---------------------------------------------------------------------------
# API Key
# ---------------------------------------------------------------------------


async def get_api_key_context_by_hash(
    session: AsyncSession, key_hash: str
) -> tuple[int, int] | None:
    """key_hash로 api_key 조회. 있으면 (client_id, project_id), 없으면 None."""
    r = await session.execute(
        select(ApiKey.client_id, ApiKey.project_id).where(ApiKey.key_hash == key_hash)
    )
    row = r.first()
    return (row[0], row[1]) if row else None


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

async def get_distinct_projects(
    session: AsyncSession, client_id: int | None = None
) -> list[dict]:
    """request 테이블에서 고유 project 목록 조회 (id, name). client_id 있으면 해당 클라이언트로 필터."""
    q = (
        select(Project.id, Project.name)
        .join(Request, Request.project_id == Project.id)
        .distinct()
    )
    if client_id is not None:
        q = q.where(Request.client_id == client_id)
    rows = (await session.execute(q.order_by(Project.id))).all()
    return [{"id": r[0], "name": r[1]} for r in rows]


async def get_admin_user_by_user_id(session: AsyncSession, user_id: str) -> AdminUser | None:
    r = await session.execute(select(AdminUser).where(AdminUser.user_id == user_id))
    return r.scalar_one_or_none()


async def get_dashboard_stats(
    session: AsyncSession,
    client_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """대시보드 통계. API_SPEC 준수."""
    now = datetime.now(KST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    base_filter: list = []
    if client_id is not None:
        base_filter.append(Request.client_id == client_id)
    if project_id is not None:
        base_filter.append(Request.project_id == project_id)

    async def _count_since(since: datetime) -> int:
        q = select(func.count()).select_from(Request).where(Request.created_at >= since)
        for f in base_filter:
            q = q.where(f)
        return (await session.execute(q)).scalar() or 0

    today_count = await _count_since(today_start)
    week_count = await _count_since(week_start)
    month_count = await _count_since(month_start)
    year_count = await _count_since(year_start)

    async def _status_count(since: datetime, status: str) -> int:
        q = select(func.count()).select_from(Request).where(
            Request.created_at >= since, Request.status == status
        )
        for f in base_filter:
            q = q.where(f)
        return (await session.execute(q)).scalar() or 0

    completed_week = await _status_count(week_start, "completed")
    error_week = await _status_count(week_start, "error")
    completed_month = await _status_count(month_start, "completed")
    error_month = await _status_count(month_start, "error")
    completed_year = await _status_count(year_start, "completed")
    error_year = await _status_count(year_start, "error")

    avg_q = (
        select(func.avg(RequestLog.processing_time_ms))
        .join(Request, Request.id == RequestLog.request_id)
        .where(RequestLog.processing_time_ms.is_not(None))
    )
    for f in base_filter:
        avg_q = avg_q.where(f)
    avg_ms = (await session.execute(avg_q)).scalar()
    avg_processing_sec = round(avg_ms / 1000, 2) if avg_ms else None

    daily_counts: list[dict] = []
    for i in range(6, -1, -1):
        day = (today_start - timedelta(days=i)).date()
        day_start = datetime.combine(day, datetime.min.time()).replace(tzinfo=KST)
        day_end = day_start + timedelta(days=1)
        dq = select(func.count()).select_from(Request).where(
            Request.created_at >= day_start, Request.created_at < day_end
        )
        for f in base_filter:
            dq = dq.where(f)
        cnt = (await session.execute(dq)).scalar() or 0
        daily_counts.append({"date": day.isoformat(), "count": cnt})

    summary_eval_trend: list[dict] = []
    summary_eval_result = {"avg_hr": None, "avg_ssr": None, "avg_icr": None, "eval_count": 0}

    return {
        "today_count": today_count,
        "week_count": week_count,
        "month_count": month_count,
        "year_count": year_count,
        "rate": {
            "week": {"total": week_count, "completed": completed_week, "error": error_week},
            "month": {"total": month_count, "completed": completed_month, "error": error_month},
            "year": {"total": year_count, "completed": completed_year, "error": error_year},
        },
        "avg_processing_sec": avg_processing_sec,
        "daily_counts": daily_counts,
        "summary_eval": summary_eval_result,
        "summary_eval_trend": summary_eval_trend,
    }


async def get_usage_by_period(
    session: AsyncSession,
    from_d: date,
    to_d: date,
    client_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    from_dt = datetime.combine(from_d, datetime.min.time()).replace(tzinfo=KST)
    to_dt = datetime.combine(to_d + timedelta(days=1), datetime.min.time()).replace(tzinfo=KST)
    base_where = [Request.created_at >= from_dt, Request.created_at < to_dt]
    if client_id is not None:
        base_where.append(Request.client_id == client_id)
    if project_id is not None:
        base_where.append(Request.project_id == project_id)

    total = (await session.execute(select(func.count()).select_from(Request).where(*base_where))).scalar() or 0
    completed = (await session.execute(
        select(func.count()).select_from(Request).where(*base_where, Request.status == "completed")
    )).scalar() or 0
    errors = (await session.execute(
        select(func.count()).select_from(Request).where(*base_where, Request.status == "error")
    )).scalar() or 0

    avg_q = (
        select(func.avg(RequestLog.processing_time_ms))
        .join(Request, Request.id == RequestLog.request_id)
        .where(*base_where, RequestLog.processing_time_ms.is_not(None))
    )
    avg_ms = (await session.execute(avg_q)).scalar()
    avg_processing_sec = round(avg_ms / 1000, 2) if avg_ms else None

    daily_counts: list[dict] = []
    cursor = from_d
    while cursor <= to_d:
        day_start = datetime.combine(cursor, datetime.min.time()).replace(tzinfo=KST)
        day_end = day_start + timedelta(days=1)
        dq = select(func.count()).select_from(Request).where(
            Request.created_at >= day_start, Request.created_at < day_end
        )
        if client_id is not None:
            dq = dq.where(Request.client_id == client_id)
        if project_id is not None:
            dq = dq.where(Request.project_id == project_id)
        cnt = (await session.execute(dq)).scalar() or 0
        daily_counts.append({"date": cursor.isoformat(), "count": cnt})
        cursor += timedelta(days=1)

    return {
        "daily_counts": daily_counts,
        "total_count": total,
        "completed_count": completed,
        "error_count": errors,
        "avg_processing_sec": avg_processing_sec,
    }


async def get_errors_by_period(
    session: AsyncSession,
    period: str,
    client_id: int | None = None,
    project_id: int | None = None,
) -> list[dict]:
    now = datetime.now(KST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)
    since_map = {"week": week_start, "month": month_start, "year": year_start}
    since = since_map.get(period, week_start)

    q = (
        select(Request.job_id, Request.created_at, RequestLog.error)
        .join(RequestLog, Request.id == RequestLog.request_id)
        .where(Request.status == "error", Request.created_at >= since)
        .order_by(Request.created_at.desc())
    )
    if client_id is not None:
        q = q.where(Request.client_id == client_id)
    if project_id is not None:
        q = q.where(Request.project_id == project_id)
    rows = (await session.execute(q)).all()

    def _normalize_error(e: dict | None) -> dict:
        if not e or not isinstance(e, dict):
            return {"code": "", "type": "", "message": "", "stage": "", "detail": ""}
        return {
            "code": e.get("type", e.get("code", "")),
            "type": e.get("type", ""),
            "message": e.get("message", e.get("error_message", "")),
            "stage": e.get("stage", e.get("error_stage", "")),
            "detail": str(e.get("detail", e)) if e.get("detail") else "",
        }

    return [
        {
            "job_id": r.job_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "error": _normalize_error(r.error),
        }
        for r in rows
    ]


async def get_requests_list(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    title_query: str | None = None,
    status_filter: str | None = None,
    client_id: int | None = None,
    project_id: int | None = None,
) -> tuple[list[dict], int]:
    base = (
        select(
            Request.job_id,
            Request.status,
            Request.created_at,
            RequestSummary.title,
            RequestLog.processing_time_ms,
        )
        .outerjoin(RequestSummary, RequestSummary.request_id == Request.id)
        .outerjoin(RequestLog, RequestLog.request_id == Request.id)
    )
    count_q = select(func.count()).select_from(Request)
    if client_id is not None:
        base = base.where(Request.client_id == client_id)
        count_q = count_q.where(Request.client_id == client_id)
    if project_id is not None:
        base = base.where(Request.project_id == project_id)
        count_q = count_q.where(Request.project_id == project_id)
    if status_filter:
        base = base.where(Request.status == status_filter)
        count_q = count_q.where(Request.status == status_filter)
    if title_query:
        base = base.where(RequestSummary.title.contains(title_query))
        count_q = (
            select(func.count())
            .select_from(Request)
            .outerjoin(RequestSummary, RequestSummary.request_id == Request.id)
            .where(RequestSummary.title.contains(title_query))
        )
        if client_id is not None:
            count_q = count_q.where(Request.client_id == client_id)
        if project_id is not None:
            count_q = count_q.where(Request.project_id == project_id)
        if status_filter:
            count_q = count_q.where(Request.status == status_filter)

    total = (await session.execute(count_q)).scalar() or 0
    rows = (await session.execute(
        base.order_by(Request.created_at.desc()).limit(limit).offset(offset)
    )).all()

    items = [
        {
            "job_id": r.job_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "status": r.status,
            "processing_sec": round(r.processing_time_ms / 1000, 2) if r.processing_time_ms else None,
            "title": r.title,
        }
        for r in rows
    ]
    return items, total


async def get_request_detail_by_job_id(
    session: AsyncSession, job_id: str, client_id: int | None = None
) -> dict | None:
    q = select(Request, Client).join(Client, Request.client_id == Client.id).where(Request.job_id == job_id)
    if client_id is not None:
        q = q.where(Request.client_id == client_id)
    row = (await session.execute(q)).first()
    if not row:
        return None
    req, client = row
    log = (await session.execute(select(RequestLog).where(RequestLog.request_id == req.id))).scalar_one_or_none()
    summary = (await session.execute(select(RequestSummary).where(RequestSummary.request_id == req.id))).scalar_one_or_none()

    processing_sec = round(log.processing_time_ms / 1000, 2) if log and log.processing_time_ms else None
    result: dict[str, Any] = {
        "job_id": req.job_id,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "status": req.status,
        "request_type": getattr(req, "request_type", "consultation"),
        "file_url": req.file_url,
        "stored_audio_url": req.stored_audio_url,
        "client_name": client.name if client else "",
        "request_timestamp": log.request_timestamp.isoformat() if log and log.request_timestamp else None,
        "completed_at": log.completed_at.isoformat() if log and log.completed_at else None,
        "processing_time_ms": log.processing_time_ms if log else None,
        "processing_sec": processing_sec,
        "audio_duration_sec": log.audio_duration_sec if log else None,
        "stages": log.stages if log else None,
        "quality": log.quality if log else None,
        "model_usage": log.model_usage if log else None,
        "error": log.error if log else None,
        "title": summary.title if summary else None,
        "simple_summary": summary.simple_summary if summary else None,
        "doctor_notes": summary.doctor_notes if summary else None,
        "test_results": summary.test_results if summary else None,
        "symptom_record": summary.symptom_record if summary else None,
        "prescription_and_care": summary.prescription_and_care if summary else None,
        "conversation_content": summary.conversation_content if summary else None,
        "summary_eval": getattr(log, "summary_eval", None) if log else None,
    }
    return result


# ---------------------------------------------------------------------------
# Inquiry (CS)
# ---------------------------------------------------------------------------


async def create_inquiry(
    session: AsyncSession,
    title: str,
    body: str,
    author_id: int,
    project_id: int | None = None,
    attachment_urls: list[str] | None = None,
) -> dict:
    """문의 등록. 반환: 생성된 문의 dict."""
    inv = Inquiry(
        title=title,
        body=body,
        status="pending",
        author_id=author_id,
        project_id=project_id,
        attachment_urls=attachment_urls or [],
    )
    session.add(inv)
    await session.flush()
    author = (await session.execute(select(AdminUser).where(AdminUser.id == author_id))).scalar_one_or_none()
    proj = (await session.execute(select(Project.id, Project.name).where(Project.id == project_id))).first() if project_id else None
    return {
        "id": inv.id,
        "title": inv.title,
        "body": inv.body,
        "status": inv.status,
        "attachment_urls": inv.attachment_urls or [],
        "project_id": inv.project_id,
        "project": {"id": proj[0], "name": proj[1]} if proj else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "author": author.display_name or author.user_id if author else "",
    }


async def get_inquiries_list(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
    project_id: int | None = None,
    q: str | None = None,
) -> tuple[list[dict], int]:
    """문의 목록 + total. status, project_id, q(검색어) 필터."""
    base = (
        select(
            Inquiry.id,
            Inquiry.title,
            Inquiry.status,
            Inquiry.project_id,
            Inquiry.created_at,
            Inquiry.updated_at,
            AdminUser.display_name,
            AdminUser.user_id,
            Project.name,
        )
        .join(AdminUser, Inquiry.author_id == AdminUser.id)
        .outerjoin(Project, Inquiry.project_id == Project.id)
    )
    count_q = select(func.count()).select_from(Inquiry)
    if status_filter and status_filter in ("pending", "in_progress", "completed"):
        base = base.where(Inquiry.status == status_filter)
        count_q = count_q.where(Inquiry.status == status_filter)
    if project_id is not None:
        base = base.where(Inquiry.project_id == project_id)
        count_q = count_q.where(Inquiry.project_id == project_id)
    if q and q.strip():
        search = q.strip()
        search_cond = or_(Inquiry.title.contains(search), Inquiry.body.contains(search))
        base = base.where(search_cond)
        count_q = count_q.where(search_cond)
    total = (await session.execute(count_q)).scalar() or 0
    rows = (await session.execute(
        base.order_by(Inquiry.created_at.desc()).limit(limit).offset(offset)
    )).all()
    items = [
        {
            "id": r[0],
            "title": r[1],
            "status": r[2],
            "project_id": r[3],
            "project": {"id": r[3], "name": r[8]} if r[3] and r[8] else None,
            "created_at": r[4].isoformat() if r[4] else None,
            "updated_at": r[5].isoformat() if r[5] else None,
            "author": r[6] or r[7] or "",
        }
        for r in rows
    ]
    return items, total


async def get_inquiry_detail(session: AsyncSession, inquiry_id: int) -> dict | None:
    """문의 상세 + replies."""
    row = (
        await session.execute(
            select(Inquiry, AdminUser.display_name, AdminUser.user_id, Project.id, Project.name)
            .join(AdminUser, Inquiry.author_id == AdminUser.id)
            .outerjoin(Project, Inquiry.project_id == Project.id)
            .where(Inquiry.id == inquiry_id)
        )
    ).first()
    if not row:
        return None
    inv, author_dn, author_uid, proj_id, proj_name = row
    reply_rows = (
        await session.execute(
            select(InquiryReply.id, InquiryReply.body, InquiryReply.created_at, AdminUser.display_name, AdminUser.user_id)
            .join(AdminUser, InquiryReply.author_id == AdminUser.id)
            .where(InquiryReply.inquiry_id == inquiry_id)
            .order_by(InquiryReply.created_at.asc())
        )
    ).all()
    replies = [
        {
            "id": r[0],
            "body": r[1],
            "created_at": r[2].isoformat() if r[2] else None,
            "author": r[3] or r[4] or "",
        }
        for r in reply_rows
    ]
    return {
        "id": inv.id,
        "title": inv.title,
        "body": inv.body,
        "status": inv.status,
        "attachment_urls": inv.attachment_urls or [],
        "project_id": inv.project_id,
        "project": {"id": proj_id, "name": proj_name} if proj_id and proj_name else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
        "author": author_dn or author_uid or "",
        "author_email": author_uid or "",
        "replies": replies,
    }


async def update_inquiry_status(
    session: AsyncSession, inquiry_id: int, status: str
) -> dict | None:
    """문의 상태 변경. 반환: id, status, updated_at 또는 None."""
    if status not in ("pending", "in_progress", "completed"):
        return None
    result = await session.execute(
        update(Inquiry).where(Inquiry.id == inquiry_id).values(status=status)
    )
    if result.rowcount == 0:
        return None
    await session.flush()
    row = (
        await session.execute(
            select(Inquiry.id, Inquiry.status, Inquiry.updated_at).where(Inquiry.id == inquiry_id)
        )
    ).first()
    if not row:
        return None
    return {
        "id": row[0],
        "status": row[1],
        "updated_at": row[2].isoformat() if row[2] else None,
    }


async def update_inquiry(
    session: AsyncSession, inquiry_id: int, **kwargs: str | int | list[str] | None
) -> dict | None:
    """문의 수정 (kwargs에 전달된 필드만 업데이트). inquiry 없으면 None."""
    values: dict = {}
    if "title" in kwargs:
        values["title"] = kwargs["title"]
    if "body" in kwargs:
        values["body"] = kwargs["body"]
    if "status" in kwargs and kwargs["status"] in ("pending", "in_progress", "completed"):
        values["status"] = kwargs["status"]
    if "project_id" in kwargs:
        values["project_id"] = kwargs["project_id"]
    if "attachment_urls" in kwargs:
        values["attachment_urls"] = kwargs["attachment_urls"]
    if not values:
        return await get_inquiry_detail(session, inquiry_id)
    result = await session.execute(
        update(Inquiry).where(Inquiry.id == inquiry_id).values(**values)
    )
    if result.rowcount == 0:
        return None
    await session.flush()
    return await get_inquiry_detail(session, inquiry_id)


async def delete_inquiry(session: AsyncSession, inquiry_id: int) -> bool:
    """문의 삭제. inquiry_reply는 CASCADE. 반환: 삭제됐으면 True, 없었으면 False."""
    result = await session.execute(delete(Inquiry).where(Inquiry.id == inquiry_id))
    return result.rowcount > 0


async def create_inquiry_reply(
    session: AsyncSession, inquiry_id: int, body: str, author_id: int
) -> dict | None:
    """문의 답변 등록. inquiry 없으면 None."""
    inv = (await session.execute(select(Inquiry).where(Inquiry.id == inquiry_id))).scalar_one_or_none()
    if not inv:
        return None
    reply = InquiryReply(inquiry_id=inquiry_id, body=body, author_id=author_id)
    session.add(reply)
    await session.flush()
    author = (await session.execute(select(AdminUser).where(AdminUser.id == author_id))).scalar_one_or_none()
    return {
        "id": reply.id,
        "body": reply.body,
        "created_at": reply.created_at.isoformat() if reply.created_at else None,
        "author": author.display_name or author.user_id if author else "",
    }

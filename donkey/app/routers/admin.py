"""Donkey Admin API. API_SPEC.md 준수."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth import create_access_token, decode_access_token, verify_password
from app.db import is_db_configured
from app.db.repository import (
    create_inquiry,
    create_inquiry_reply,
    delete_inquiry,
    get_admin_user_by_user_id,
    get_dashboard_stats,
    get_distinct_projects,
    get_errors_by_period,
    get_inquiry_detail,
    get_inquiries_list,
    get_request_detail_by_job_id,
    get_requests_list,
    get_usage_by_period,
    update_inquiry_status,
)
from app.db.session import get_session
from app.schemas.error import ERROR_401, error_response

router = APIRouter(prefix="/admin/api", tags=["admin"])

security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    user_id: str
    password: str


class InquiryCreateBody(BaseModel):
    title: str
    body: str
    project_id: int | None = None


class InquiryStatusBody(BaseModel):
    status: str


class InquiryReplyBody(BaseModel):
    body: str


@router.post("/login")
async def login(body: LoginRequest):
    """user_id / password 로그인 → access_token"""
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "관리자 로그인 미설정 (DB 연결 없음)"),
        )
    user_id = (body.user_id or "").strip()
    password = body.password or ""
    if not user_id or not password:
        raise HTTPException(status_code=401, detail=error_response(*ERROR_401))

    async with get_session() as session:
        admin = await get_admin_user_by_user_id(session, user_id)
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail=error_response(*ERROR_401))
    if not verify_password(password, admin.password_hash):
        raise HTTPException(status_code=401, detail=error_response(*ERROR_401))

    token = create_access_token(sub=admin.user_id)
    return {"access_token": token}


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail=error_response(*ERROR_401))
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail=error_response(*ERROR_401))
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "관리자 인증에 DB가 필요합니다."),
        )
    async with get_session() as session:
        admin = await get_admin_user_by_user_id(session, payload["sub"])
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail=error_response(*ERROR_401))
    return admin


@router.get("/projects")
async def list_projects(admin=Depends(get_current_admin)):
    """request 테이블에서 고유 project 목록 조회 (id, name)."""
    if not is_db_configured():
        return {"items": []}
    try:
        async with get_session() as session:
            items = await get_distinct_projects(session, admin.client_id)
        return {"items": items}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_response("COMMON_500_000", f"프로젝트 목록 조회 중 오류: {e!s}"),
        )


@router.get("/me")
async def me(admin=Depends(get_current_admin)):
    return {"user_id": admin.user_id, "display_name": admin.display_name}


@router.post("/refresh")
async def refresh(admin=Depends(get_current_admin)):
    token = create_access_token(sub=admin.user_id)
    return {"access_token": token}


@router.get("/dashboard")
async def dashboard(
    admin=Depends(get_current_admin),
    project_id: int | None = None,
):
    if not is_db_configured():
        return {
            "today_count": 0,
            "week_count": 0,
            "month_count": 0,
            "year_count": 0,
            "rate": {
                "week": {"total": 0, "completed": 0, "error": 0},
                "month": {"total": 0, "completed": 0, "error": 0},
                "year": {"total": 0, "completed": 0, "error": 0},
            },
            "avg_processing_sec": None,
            "daily_counts": [],
            "summary_eval": {"avg_hr": None, "avg_ssr": None, "avg_icr": None, "eval_count": 0},
            "summary_eval_trend": [],
        }
    try:
        async with get_session() as session:
            return await get_dashboard_stats(session, admin.client_id, project_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_response("COMMON_500_000", f"대시보드 조회 중 오류: {e!s}"),
        )


@router.get("/usage")
async def usage(
    admin=Depends(get_current_admin),
    from_date: str | None = None,
    to_date: str | None = None,
    project_id: int | None = None,
):
    if not is_db_configured():
        return {
            "daily_counts": [],
            "total_count": 0,
            "completed_count": 0,
            "error_count": 0,
            "avg_processing_sec": None,
        }
    today = date.today()
    try:
        from_d = date.fromisoformat(from_date) if from_date else today - timedelta(days=6)
        to_d = date.fromisoformat(to_date) if to_date else today
    except ValueError:
        from_d = today - timedelta(days=6)
        to_d = today
    if from_d > to_d:
        from_d, to_d = to_d, from_d
    if (to_d - from_d).days > 90:
        to_d = from_d + timedelta(days=90)
    try:
        async with get_session() as session:
            return await get_usage_by_period(session, from_d, to_d, admin.client_id, project_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_response("COMMON_500_000", f"사용량 조회 중 오류: {e!s}"),
        )


@router.get("/requests")
async def list_requests(
    admin=Depends(get_current_admin),
    page: int = 1,
    limit: int = 50,
    title: str | None = None,
    status: str | None = None,
    project_id: int | None = None,
):
    if not is_db_configured():
        return {"items": [], "total": 0}
    limit = max(1, min(limit, 100))
    offset = (page - 1) * limit
    title_query = title.strip() if title and title.strip() else None
    status_filter = status.strip() if status and status.strip() else None
    try:
        async with get_session() as session:
            items, total = await get_requests_list(
                session,
                limit=limit,
                offset=offset,
                title_query=title_query,
                status_filter=status_filter,
                client_id=admin.client_id,
                project_id=project_id,
            )
        return {"items": items, "total": total}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_response("COMMON_500_000", f"요청 목록 조회 중 오류: {e!s}"),
        )


@router.get("/requests/{job_id}")
async def get_request_detail(job_id: str, admin=Depends(get_current_admin)):
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "관리자 API에 DB가 필요합니다."),
        )
    async with get_session() as session:
        detail = await get_request_detail_by_job_id(
            session, job_id.strip().strip('"\''), admin.client_id
        )
    if detail is None:
        raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", "해당 요청을 찾을 수 없습니다."))
    return detail


# ---------------------------------------------------------------------------
# Inquiry (CS)
# ---------------------------------------------------------------------------


@router.post("/inquiries", status_code=201)
async def create_inquiry_endpoint(
    body: InquiryCreateBody,
    admin=Depends(get_current_admin),
):
    """문의 등록."""
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "DB 연결이 필요합니다."),
        )
    try:
        async with get_session() as session:
            result = await create_inquiry(
                session, body.title, body.body, admin.id, body.project_id
            )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_response("COMMON_500_000", f"문의 등록 중 오류: {e!s}"),
        )


@router.get("/inquiries")
async def list_inquiries(
    admin=Depends(get_current_admin),
    page: int = 1,
    limit: int = 50,
    status: str | None = None,
    project_id: int | None = None,
    q: str | None = None,
):
    """문의 목록."""
    if not is_db_configured():
        return {"items": [], "total": 0}
    limit = max(1, min(limit, 100))
    offset = (page - 1) * limit
    status_filter = status.strip() if status and status.strip() else None
    try:
        async with get_session() as session:
            items, total = await get_inquiries_list(
                session,
                limit=limit,
                offset=offset,
                status_filter=status_filter,
                project_id=project_id,
                q=q,
            )
        return {"items": items, "total": total}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_response("COMMON_500_000", f"문의 목록 조회 중 오류: {e!s}"),
        )


@router.get("/inquiries/{inquiry_id}")
async def get_inquiry_detail_endpoint(
    inquiry_id: int,
    admin=Depends(get_current_admin),
):
    """문의 상세."""
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "DB 연결이 필요합니다."),
        )
    async with get_session() as session:
        detail = await get_inquiry_detail(session, inquiry_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", "해당 문의를 찾을 수 없습니다."))
    return detail


@router.patch("/inquiries/{inquiry_id}")
async def patch_inquiry_status(
    inquiry_id: int,
    body: InquiryStatusBody,
    admin=Depends(get_current_admin),
):
    """문의 상태 변경."""
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "DB 연결이 필요합니다."),
        )
    async with get_session() as session:
        result = await update_inquiry_status(session, inquiry_id, body.status)
    if result is None:
        raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", "해당 문의를 찾을 수 없습니다."))
    return result


@router.delete("/inquiries/{inquiry_id}", status_code=204)
async def delete_inquiry_endpoint(
    inquiry_id: int,
    admin=Depends(get_current_admin),
):
    """문의 삭제."""
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "DB 연결이 필요합니다."),
        )
    async with get_session() as session:
        deleted = await delete_inquiry(session, inquiry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", "해당 문의를 찾을 수 없습니다."))


@router.post("/inquiries/{inquiry_id}/replies")
async def create_inquiry_reply_endpoint(
    inquiry_id: int,
    body: InquiryReplyBody,
    admin=Depends(get_current_admin),
):
    """문의 답변 등록."""
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=error_response("SERVICE_UNAVAILABLE", "DB 연결이 필요합니다."),
        )
    async with get_session() as session:
        result = await create_inquiry_reply(session, inquiry_id, body.body, admin.id)
    if result is None:
        raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", "해당 문의를 찾을 수 없습니다."))
    return result


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@router.get("/errors")
async def list_errors(
    admin=Depends(get_current_admin),
    period: str = "week",
    project_id: int | None = None,
):
    if not is_db_configured():
        return {"items": []}
    period = period.strip().lower()
    if period not in ("week", "month", "year"):
        period = "week"
    try:
        async with get_session() as session:
            items = await get_errors_by_period(session, period, admin.client_id, project_id)
        return {"items": items}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_response("COMMON_500_000", f"오류 목록 조회 중 오류: {e!s}"),
        )

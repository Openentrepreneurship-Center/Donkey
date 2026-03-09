from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Double, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

KST = timezone(timedelta(hours=9))


class Base(DeclarativeBase):
    pass


class AdminUser(Base):
    """관리자 로그인 계정. client_id로 연결된 클라이언트 데이터만 조회 가능."""
    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("client.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST), onupdate=lambda: datetime.now(KST))


class Client(Base):
    __tablename__ = "client"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # admin 브랜치 호환
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST), onupdate=lambda: datetime.now(KST))


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("client.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST), onupdate=lambda: datetime.now(KST))


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("client.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST), onupdate=lambda: datetime.now(KST))


class Request(Base):
    __tablename__ = "request"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("client.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("project.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    request_type: Mapped[str] = mapped_column(String(32), nullable=False, default="consultation")
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    stored_audio_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST), onupdate=lambda: datetime.now(KST))


class RequestLog(Base):
    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("request.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    request_timestamp: Mapped[datetime] = mapped_column(DateTime(6), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), nullable=True)
    audio_duration_sec: Mapped[float | None] = mapped_column(Double, nullable=True)
    stages: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    model_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    summary_eval: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class RequestSummary(Base):
    __tablename__ = "request_summary"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("request.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    simple_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    doctor_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    test_results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    symptom_record: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prescription_and_care: Mapped[list | None] = mapped_column(JSON, nullable=True)
    conversation_content: Mapped[list | None] = mapped_column(JSON, nullable=True)


class Inquiry(Base):
    __tablename__ = "inquiry"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    author_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("admin_user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST), onupdate=lambda: datetime.now(KST))


class InquiryReply(Base):
    __tablename__ = "inquiry_reply"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    inquiry_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("inquiry.id", ondelete="CASCADE"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("admin_user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))

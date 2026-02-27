from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import BigInteger, DateTime, Double, ForeignKey, Index, String, Text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

KST = timezone(timedelta(hours=9))


class Base(DeclarativeBase):
    pass


class Consultation(Base):
    __tablename__ = "consultation"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    stored_audio_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST))
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, default=lambda: datetime.now(KST), onupdate=lambda: datetime.now(KST))


class ConsultationLog(Base):
    __tablename__ = "consultation_log"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    consultation_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("consultation.id", ondelete="CASCADE"),
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


class ConsultationSummary(Base):
    __tablename__ = "consultation_summary"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(BigInteger(), "mysql"), primary_key=True, autoincrement=True)
    consultation_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BigInteger(), "mysql"),
        ForeignKey("consultation.id", ondelete="CASCADE"),
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

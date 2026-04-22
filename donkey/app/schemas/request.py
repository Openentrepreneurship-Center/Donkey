from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class AIRequest(BaseModel):
    file: HttpUrl = Field(..., description="처리할 오디오 파일의 URL")


class AIConsultationFileRequest(BaseModel):
    """상담 오디오는 히포 조회 API로 확보 후 전사 (실험·검증용 엔드포인트)."""

    file_id: UUID = Field(..., alias="fileId", description="상담 ID (UUID)")

    model_config = {"populate_by_name": True}

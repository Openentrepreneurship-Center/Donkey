from pydantic import BaseModel, Field, HttpUrl


class AIRequest(BaseModel):
    file: HttpUrl = Field(..., description="처리할 오디오 파일의 URL")

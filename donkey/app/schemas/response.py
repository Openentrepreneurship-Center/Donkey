from pydantic import BaseModel, Field


class ConversationItem(BaseModel):
    role: str = Field(..., description="발화자 역할 (의사/환자)")
    index: int = Field(..., description="대화 순서 인덱스")
    content: str = Field(..., description="발화 내용")


class Screening(BaseModel):
    names: list[str] = Field(default_factory=list, description="스크리닝된 이름 목록 (예: [홍길동])")
    phones: list[str] = Field(default_factory=list, description="스크리닝된 전화번호 목록")


class SoapSummary(BaseModel):
    """SOAP(Subjective, Objective, Assessment, Plan) 요약 구조."""
    S: list[str] = Field(default_factory=list, description="Subjective - 증상/주호소")
    O: list[str] = Field(default_factory=list, description="Objective - 소견/검사")
    A: list[str] = Field(default_factory=list, description="Assessment - 평가/진단")
    P: list[str] = Field(default_factory=list, description="Plan - 처방/계획")


class ConsultationSummary(BaseModel):
    doctorNotes: list[str] = Field(default_factory=list, description="의사 소견")
    testResults: list[str] = Field(default_factory=list, description="검사 결과")
    symptomRecord: list[str] = Field(default_factory=list, description="증상 기록")
    prescriptionAndCare: list[str] = Field(default_factory=list, description="처방 및 관리")
    conversationContent: list[ConversationItem] = Field(default_factory=list, description="대화 내용")


class AIResultBody(BaseModel):
    id: str = Field(..., description="작업 ID")
    title: str = Field(..., description="진료 제목")
    duration: float = Field(..., description="오디오 길이 (초)")
    isGenerated: bool = Field(..., description="생성 완료 여부")
    isAbusing: bool = Field(..., description="부적절한 콘텐츠 여부")
    abusingReason: str = Field(..., description="부적절 판정 사유")
    isScreening: bool = Field(..., description="스크리닝된 항목 존재 여부")
    screeningReason: str = Field(..., description="스크리닝 사유 (해당되는 내용 발견/없음)")
    screening: Screening = Field(..., description="스크리닝된 이름·전화번호 목록")
    simpleSummary: str = Field(..., description="간단 요약")
    soap: SoapSummary | None = Field(None, description="SOAP(S/O/A/P) 요약")
    consultationSummary: ConsultationSummary | None = Field(None, description="진료 요약")


class AIResponse(BaseModel):
    status: str = Field(..., description="응답 상태 (ok/error)")
    statusCode: int = Field(..., description="HTTP 상태 코드")
    body: AIResultBody = Field(..., description="응답 본문")


class AICreateBody(BaseModel):
    id: str = Field(..., description="생성된 작업 ID")


class AICreateResponse(BaseModel):
    status: str = Field(..., description="응답 상태 (ok/error)")
    statusCode: int = Field(..., description="HTTP 상태 코드")
    body: AICreateBody = Field(..., description="응답 본문")

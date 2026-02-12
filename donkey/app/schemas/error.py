"""오류 응답 규격: HTTP 200 외 오류 케이스 공통 포맷."""

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """오류 시 공통 응답 본문. code + message 만 반환."""

    code: str = Field(..., description="오류 코드 (예: COMMON_400_000)")
    message: str = Field(..., description="오류 메시지")


# 상태코드별 code / message (규격 문서 기준)
ERROR_400 = ("COMMON_400_000", "입력값 오류입니다. 안내 메시지에 따라 수정 후 재시도해주세요.")
ERROR_401 = (
    "COMMON_401_000",
    "인증되지 않는 요청입니다. x-api-key 헤더 값이나 key 파라미터 값이 잘못되었습니다.",
)
ERROR_404 = ("COMMON_404_000", "요청한 리소스를 찾을 수 없습니다.")
ERROR_422 = (
    "COMMON_422_000",
    "잘못된 요청입니다. Schema 이외의 path, query, body parameter가 잘못되었습니다.",
)
ERROR_429 = (
    "COMMON_429_000",
    "요청과다로 인한 Rate Limit 초과입니다. 나중에 다시 시도하세요.",
)
ERROR_500 = (
    "COMMON_500_000",
    "예상치 못한 오류가 발생하였습니다. 돈키 팀에 문의해주세요.",
)
ERROR_523 = (
    "COMMON_523_000",
    "AI 서버가 다운되었습니다. 나중에 다시 시도하세요 (에러 발생시 소통채널을 통해 장애가 안내됩니다.)",
)
ERROR_524_TIMEOUT = (
    "COMMON_524_000",
    "추론 시간이 초과되었습니다. 실시간 응답 API 를 사용하면서 9초를 넘어간 경우 발생합니다.",
)
ERROR_524_INFERENCE = (
    "COMMON_524_001",
    "AI 추론 중 오류가 발생하였습니다. 나중에 다시 시도하세요.",
)


def error_response(code: str, message: str) -> dict:
    """ErrorResponse 규격 dict 반환 (JSONResponse content용)."""
    return {"code": code, "message": message}

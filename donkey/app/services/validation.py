from app.services.openai_client import get_openai_client
from app.services.job_logger import JobLogger


def validate_medical_conversation(
    diarized_text: str,
    chat_model: str = "gpt-4o-mini",
    job_logger: JobLogger | None = None,
) -> tuple[bool, str]:
    """
    Validate if the transcribed text is a legitimate medical conversation.

    Returns:
        (is_valid, reason): True if valid medical conversation, False with reason if not.
    """
    if not diarized_text or len(diarized_text.strip()) < 50:
        return False, "대화 내용이 너무 짧습니다"

    client = get_openai_client()

    resp = client.chat.completions.create(
        model=chat_model,
        messages=[
            {
                "role": "system",
                "content": """당신은 의료 대화 검증 시스템입니다.
주어진 텍스트가 실제 의료 진료 대화인지 판별합니다.

판별 기준:
1. 의사와 환자 간의 대화인가?
2. 의료/건강 관련 내용을 포함하는가?
3. 증상, 진단, 처방, 검사 등 의료 행위와 관련된 대화인가?

응답 형식 (JSON):
{"is_valid": true/false, "reason": "판별 이유"}

예시 응답:
{"is_valid": true, "reason": ""}
{"is_valid": false, "reason": "진료 대화가 아님 - 일상 대화로 판단됨"}
"""
            },
            {
                "role": "user",
                "content": f"다음 텍스트가 의료 진료 대화인지 판별해주세요:\n\n{diarized_text[:2000]}"  # Limit for token efficiency
            },
        ],
        temperature=0.1,
        max_tokens=100,
    )
    if job_logger:
        usage = getattr(resp, "usage", None)
        if usage:
            job_logger.add_chat_tokens(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            )

    response_text = resp.choices[0].message.content.strip()

    # Parse JSON response
    try:
        import json
        result = json.loads(response_text)
        is_valid = result.get("is_valid", True)
        reason = result.get("reason", "")
        return is_valid, reason
    except json.JSONDecodeError:
        # If JSON parsing fails, assume valid (fail-open)
        return True, ""
